#!/usr/bin/env python3
"""Revise catchments in the T1 catchments GeoPackage: fix polygons and recompute their attributes.

Usage (project venv):  .venv/bin/python revise_catchments.py --config revise_catchments.local.json [--init] [--dry-run]

Only replacements: no catchment is added or deleted, and intake points are never moved. T2 is rebuilt afterwards.
Config keys: catchments_gpkg, catchments_layer, intakes_gpkg, intakes_layer, revisions[].
  Optional: intake_warning_m (default 500), distance_crs (default ESRI:102033).
  Relative paths resolve against the config file.
revisions: list of items, processed in order; the list keeps growing (items already processed are skipped).
  "IN..."                                    edit mode: the geometry was edited in T1 (e.g. QGIS); recompute only
  {"IN...": {"replace": "fix.fgb"}}          replace mode: write the FIRST feature's geometry of the file into T1
                                             (needs a CRS, reprojected to the layer's; other features and all columns ignored)
  Keep the replacement files: listed replace items are read again on every run (to see if they are already applied).
  Several intakes can share one identical polygon (same outlet): a fix applies only to the listed intake_code.
For each applied item: make_valid, keep polygon parts, force MultiPolygon (empty -> error); the distance from the
intake point to the polygon is reported, with a warning beyond intake_warning_m (information only, never an error: the
Atlas points are often ill-positioned and the catchments were derived from corrected points);
catchment_area_km2 = geodesic area (WGS84 ellipsoid, km2);
n_parts = number of polygons; catchment_source = manual_replaced (replace) or <source>_manual_edits (edit, suffix
never repeated); geometry hash updated.
Geometry hashes (table catchments_hashes in the same gpkg, not registered in gpkg_contents, not copied to T2):
  sha256 of the WKB of the geometry as MultiPolygon, coordinates rounded to 9 decimals, shapely.normalize'd.
  A row whose current hash differs from the stored one was edited. Edited rows that are not listed stop the run.
  build_database.py runs the same check (check_catchments) and refuses to build from stale catchments.
  A replace item whose row was also edited in T1 stops the run (the edit would be lost).
--init     first run: add column n_parts and create the hashes table for all rows; applies no revisions.
--dry-run  report per item (mode, status, source, area, parts, intake distance) and write nothing.
Writes: timestamped backup <name>_backup_YYYYMMDD_HHMMSS.gpkg first, then updates only the listed rows (one
transaction; the rtree triggers keep the spatial index in sync). Any error stops the run before writing.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
import shapely
from pyproj import Geod

REQUIRED = ["catchments_gpkg", "catchments_layer", "intakes_gpkg", "intakes_layer", "revisions"]
HASH_TABLE = "catchments_hashes"
EDIT_SUFFIX = "_manual_edits"
REPLACED = "manual_replaced"
HASH_DECIMALS = 9  # ~0.1 mm: survives a re-save, catches any real edit
GEOD = Geod(ellps="WGS84")
ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}  # GeoPackage blob envelope indicator -> size


def log(m):
    print(m, flush=True)


# --------------------------------------------------------------------------- GeoPackage geometry blobs
def gpb_parse(blob):
    """GeoPackage geometry blob -> (empty, envelope (minx, maxx, miny, maxy) or None, wkb)."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry blob")
    flags = blob[3]
    n = ENVELOPE_BYTES[(flags >> 1) & 7]
    env = struct.unpack(("<" if flags & 1 else ">") + "4d", blob[8:40]) if n else None
    return bool(flags & 16), env, bytes(blob[8 + n:])


def gpb_from_geom(geom, srs_id):
    minx, miny, maxx, maxy = geom.bounds
    header = b"GP" + bytes([0, 0b011]) + struct.pack("<i4d", srs_id, minx, maxx, miny, maxy)  # LE, xy envelope
    return header + shapely.to_wkb(geom, byte_order=1, output_dimension=2)


def envelope(blob):
    if blob is None:
        return None
    empty, env, wkb = gpb_parse(blob)
    if empty:
        return None
    if env is None:
        b = shapely.from_wkb(wkb).bounds
        env = (b[0], b[2], b[1], b[3])
    return env


def connect(path, readonly):
    """sqlite connection with the ST_* functions the GeoPackage rtree triggers call (GDAL provides them in QGIS)."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True) if readonly else sqlite3.connect(path)
    con.create_function("ST_IsEmpty", 1, lambda b: None if b is None else int(gpb_parse(b)[0]), deterministic=True)
    for i, name in enumerate(["ST_MinX", "ST_MaxX", "ST_MinY", "ST_MaxY"]):
        con.create_function(name, 1, lambda b, i=i: None if envelope(b) is None else envelope(b)[i], deterministic=True)
    return con


# --------------------------------------------------------------------------- geometry
def polygon_parts(geom):
    """Polygon parts of any geometry (nested collections included), in order, empty ones dropped."""
    if geom.geom_type == "Polygon":
        return [] if geom.is_empty else [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for g in shapely.get_parts(geom) for p in polygon_parts(g)]
    return []


def clean(geom):
    return shapely.MultiPolygon(polygon_parts(shapely.make_valid(geom)))


def geom_hash(geom, decimals=HASH_DECIMALS):
    g = shapely.MultiPolygon(polygon_parts(geom))
    g = shapely.normalize(shapely.transform(g, lambda c: np.round(c, decimals)))
    return hashlib.sha256(shapely.to_wkb(g, byte_order=1, output_dimension=2)).hexdigest()


def geodesic_km2(geom):
    return abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6


# --------------------------------------------------------------------------- config / data
def load_config(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding="utf-8"))
    miss = [k for k in REQUIRED if k not in cfg]
    if miss:
        sys.exit(f"config: missing keys {miss}")
    for k in ("catchments_gpkg", "intakes_gpkg"):
        cfg[k] = path.parent / cfg[k]
    cfg["items"] = parse_revisions(cfg["revisions"], path.parent)
    return cfg


def parse_revisions(revisions, base):
    items, seen = [], set()
    for r in revisions:
        if isinstance(r, str):
            code, opts = r, {}
        elif isinstance(r, dict) and len(r) == 1:
            code, opts = next(iter(r.items()))
        else:
            sys.exit(f"revisions: bad item {r!r} (a code, or {{code: {{\"replace\": file}}}})")
        unknown = set(opts) - {"replace"}
        if unknown:
            sys.exit(f"revisions: {code}: unknown options {sorted(unknown)}")
        if code in seen:
            sys.exit(f"revisions: {code} listed twice")
        seen.add(code)
        item = {"code": code, "mode": "replace" if "replace" in opts else "edit"}
        if "replace" in opts:
            item["replace"] = base / opts["replace"]
        items.append(item)
    return items


def read_layer(con, layer):
    gc = con.execute("SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name = ?", (layer,)).fetchone()
    if gc is None:
        sys.exit(f"layer {layer} not found in the catchments gpkg")
    gcol, srs_id = gc
    cols = [r[1] for r in con.execute(f'PRAGMA table_info("{layer}")')]
    has_parts = "n_parts" in cols
    sql = f'SELECT fid, "{gcol}", intake_code, catchment_source, catchment_area_km2{", n_parts" if has_parts else ""} FROM "{layer}"'
    rows = {}
    for r in con.execute(sql):
        if r[2] is None or r[2] in rows:
            sys.exit(f"catchments: intake_code null or repeated ({r[2]})")
        if r[1] is None:
            sys.exit(f"catchments: {r[2]} has no geometry")
        rows[r[2]] = {"fid": r[0], "geom": shapely.from_wkb(gpb_parse(r[1])[2]), "source": r[3], "area": r[4],
                      "parts": r[5] if has_parts else None}
    return rows, gcol, srs_id, has_parts


def has_table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def read_replacement(path, srs_id):
    info = pyogrio.read_info(path)
    gdf = pyogrio.read_dataframe(path, max_features=1)
    if gdf.crs is None:
        raise ValueError(f"{path.name} has no CRS")
    if len(gdf) == 0 or gdf.geometry.iloc[0] is None:
        raise ValueError(f"{path.name} has no geometry in its first feature")
    note = f"{path.name}: {info['features']} features, only the first is used" if info["features"] > 1 else ""
    return gdf.to_crs(srs_id).geometry.iloc[0], note


def backup(path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = path.with_name(f"{path.stem}_backup_{stamp}{path.suffix}")
    shutil.copy2(path, dst)
    log(f"backup: {dst}")


def check_not_in_use(path):
    for ext in ("-wal", "-journal"):
        if Path(f"{path}{ext}").exists():
            sys.exit(f"{path.name}{ext} exists: the gpkg is open elsewhere (QGIS?) or was not closed cleanly")


def check_catchments(path, layer):
    """None if every catchment matches its stored hash and n_parts, else the reason (used by build_database.py)."""
    con = connect(path, readonly=True)
    if not has_table(con, HASH_TABLE):
        return f"{HASH_TABLE} missing in {path.name}: run revise_catchments.py --init first"
    rows, _, _, has_parts = read_layer(con, layer)
    stored = dict(con.execute(f"SELECT intake_code, geom_hash FROM {HASH_TABLE}"))
    con.close()
    if not has_parts:
        return f"n_parts missing in {path.name}: run revise_catchments.py --init first"
    if set(stored) != set(rows):
        return "catchments added or deleted since the hashes were stored"
    edited = sorted(c for c, r in rows.items() if geom_hash(r["geom"]) != stored[c])
    if edited:
        return (f"{len(edited)} catchments edited since the last revise_catchments.py run (area, n_parts and source "
                f"would be stale): {edited[:10]}. List them in revisions and run revise_catchments.py first")
    stale = sorted(c for c, r in rows.items() if r["parts"] != len(polygon_parts(r["geom"])))
    if stale:
        return f"n_parts does not match the geometry for {len(stale)} catchments: {stale[:10]}"
    return None


# --------------------------------------------------------------------------- init
def run_init(cfg, args):
    path = cfg["catchments_gpkg"]
    con = connect(path, readonly=args.dry_run)
    if has_table(con, HASH_TABLE):
        sys.exit(f"{HASH_TABLE} already exists: already initialized")
    rows, _, _, has_parts = read_layer(con, cfg["catchments_layer"])
    hashes = {c: geom_hash(r["geom"]) for c, r in rows.items()}
    parts = {c: len(polygon_parts(r["geom"])) for c, r in rows.items()}
    off = [c for c, r in rows.items() if abs(geodesic_km2(r["geom"]) / r["area"] - 1) > 1e-9]
    log(f"init: {len(rows)} catchments, n_parts {'update' if has_parts else 'new column'} "
        f"(multipart {sum(v > 1 for v in parts.values())}), {len(set(hashes.values()))} distinct hashes")
    log(f"  stored area differs from the geodesic area (> 1e-9 relative) in {len(off)} rows{': ' + ', '.join(off[:10]) if off else ''}")
    if args.dry_run:
        log("dry run: nothing written")
        return
    check_not_in_use(path)
    backup(path)
    layer = cfg["catchments_layer"]
    with con:
        con.execute("BEGIN")
        if not has_parts:
            con.execute(f'ALTER TABLE "{layer}" ADD COLUMN n_parts INTEGER')
        con.executemany(f'UPDATE "{layer}" SET n_parts = ? WHERE intake_code = ?', [(v, c) for c, v in parts.items()])
        con.execute(f"CREATE TABLE {HASH_TABLE} (intake_code TEXT PRIMARY KEY NOT NULL, geom_hash TEXT NOT NULL)")
        con.executemany(f"INSERT INTO {HASH_TABLE} VALUES (?, ?)", sorted(hashes.items()))
    con.close()
    log(f"init done: {path}")


# --------------------------------------------------------------------------- revisions
def intake_distance(geom, point, crs):
    g = gpd.GeoSeries([geom, point], crs=4326).to_crs(crs)
    return float(g.iloc[0].distance(g.iloc[1]))


def new_source(old, mode):
    if mode == "replace":
        return REPLACED
    return old if old.endswith(EDIT_SUFFIX) else old + EDIT_SUFFIX


def run_revisions(cfg, args):
    path = cfg["catchments_gpkg"]
    con = connect(path, readonly=args.dry_run)
    rows, gcol, srs_id, has_parts = read_layer(con, cfg["catchments_layer"])
    if not has_table(con, HASH_TABLE) or not has_parts:
        sys.exit(f"{HASH_TABLE} table or n_parts column missing: run --init first")
    stored = dict(con.execute(f"SELECT intake_code, geom_hash FROM {HASH_TABLE}"))
    if set(stored) != set(rows):
        sys.exit(f"catchments added or deleted since the hashes were stored: "
                 f"new {sorted(set(rows) - set(stored))[:10]}, gone {sorted(set(stored) - set(rows))[:10]}")
    edited = {c for c, r in rows.items() if geom_hash(r["geom"]) != stored[c]}
    listed = {it["code"] for it in cfg["items"]}
    unknown = sorted(listed - set(rows))
    if unknown:
        sys.exit(f"revisions: intake_code not in the catchments layer: {unknown}")
    unlisted = sorted(edited - listed)
    if unlisted:
        sys.exit(f"STOP: {len(unlisted)} catchments edited in T1 but not listed in revisions: {unlisted}")
    if not cfg["items"]:
        log("no revisions listed, no unlisted edits: nothing to do")
        return

    intakes = pyogrio.read_dataframe(cfg["intakes_gpkg"], layer=cfg["intakes_layer"], columns=["intake_code"])
    intakes = intakes.to_crs(srs_id).set_index("intake_code").geometry
    crs = cfg.get("distance_crs", "ESRI:102033")
    warn_m = cfg.get("intake_warning_m", 500)
    report, todo, errors, warnings = [], [], 0, 0
    for it in cfg["items"]:
        code, mode, row = it["code"], it["mode"], rows[it["code"]]
        rec = {"code": code, "mode": mode, "status": "", "note": ""}
        report.append(rec)
        try:
            if mode == "edit":
                if code not in edited:
                    rec["status"] = "skip (geometry unchanged or already processed)"
                    continue
                raw = row["geom"]
            else:
                if code in edited:
                    raise ValueError("listed for replace but its geometry was also edited in T1 (the edit would be "
                                     "lost): list it as an edit item or restore the geometry")
                raw, rec["note"] = read_replacement(it["replace"], srs_id)
            geom = clean(raw)
            if geom.is_empty:
                raise ValueError("no polygon left after clean-up")
            if not raw.equals(geom):
                rec["note"] = "; ".join(x for x in (rec["note"], "geometry changed by clean-up") if x)
            h = geom_hash(geom)
            if mode == "replace" and h == stored[code]:
                rec["status"] = "skip (replacement already applied)"
                continue
            new = {"source": new_source(row["source"], mode), "area": geodesic_km2(geom),
                   "parts": len(geom.geoms), "hash": h, "geom": geom}
            rec.update(source=f"{row['source']} -> {new['source']}",
                       area=f"{row['area']:.3f} -> {new['area']:.3f} km2 (x{new['area'] / row['area']:.3f})",
                       parts=f"{row['parts']} -> {new['parts']}")
            if code in intakes.index:
                dist = intake_distance(geom, intakes.loc[code], crs)
                rec["distance"] = f"intake point {dist:.0f} m from the polygon"
                if dist > warn_m:
                    rec["distance"] += f"  WARNING > {warn_m} m: check the intake_code"
                    warnings += 1
            else:
                rec["distance"] = "WARNING: intake point not found in the intakes layer"
                warnings += 1
            rec["status"] = "apply"
            todo.append((row["fid"], code, new))
        except (ValueError, OSError, pyogrio.errors.DataSourceError) as e:
            rec["status"] = f"ERROR: {e}"
            errors += 1
    for rec in report:
        log(f"[{rec['code']}] {rec['mode']}: {rec['status']}")
        for k in ("source", "area", "parts", "distance", "note"):
            if rec.get(k):
                log(f"    {k}: {rec[k]}")
    log(f"{len(report)} items: {len(todo)} to apply, {len(report) - len(todo) - errors} skipped, {errors} errors, "
        f"{warnings} distance warnings")
    if errors:
        sys.exit("errors: nothing written")
    if args.dry_run or not todo:
        log("dry run: nothing written" if args.dry_run else "nothing to apply")
        return
    check_not_in_use(path)
    backup(path)
    layer = cfg["catchments_layer"]
    with con:
        con.execute("BEGIN")
        for fid, code, new in todo:
            con.execute(f'UPDATE "{layer}" SET "{gcol}" = ?, catchment_source = ?, catchment_area_km2 = ?, n_parts = ? '
                        f'WHERE fid = ?', (gpb_from_geom(new["geom"], srs_id), new["source"], new["area"], new["parts"], fid))
            con.execute(f"UPDATE {HASH_TABLE} SET geom_hash = ? WHERE intake_code = ?", (new["hash"], code))
        ext = con.execute(f'SELECT min(ST_MinX("{gcol}")), min(ST_MinY("{gcol}")), max(ST_MaxX("{gcol}")), '
                          f'max(ST_MaxY("{gcol}")) FROM "{layer}"').fetchone()  # exact (the rtree is float32)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"
        con.execute("UPDATE gpkg_contents SET last_change = ?, min_x = ?, min_y = ?, max_x = ?, max_y = ? "
                    "WHERE table_name = ?", (now, *ext, layer))
    con.close()
    log(f"written: {len(todo)} catchments in {path}. Rebuild T2 next.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--init", action="store_true", help="create the hashes table and n_parts; applies no revisions")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if not cfg["catchments_gpkg"].exists():
        sys.exit(f"{cfg['catchments_gpkg']} not found")
    run_init(cfg, args) if args.init else run_revisions(cfg, args)


if __name__ == "__main__":
    main()
