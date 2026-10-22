#!/usr/bin/env python3
"""Standardize Atlas Aguas T1 (legacy -> standard): file, layer and column names.

ARCHIVED (provenance only, see archive/PROVENANCE.md). Never run it on the real T1: it would overwrite the revised
catchments and could rename intakes. It refuses to write when any of its output files already exists in output_folder
(there is no overwrite option): write to a new, empty folder.

Usage (project venv):  .venv/bin/python archive/standardize_t1.py --config archive/standardize_t1.local.json
                       [--only ISH,SEATS] [--dry-run]

Config keys: input_folder, output_folder, prefix, extent, year, na_text, layers[].
Each layer: name, source, type (csv|gpkg), layer_in (gpkg), description_pt/en,
  drop [source columns purged on purpose], value_maps {new_column: {old: new}}, columns[] {from, to, description_pt, description_en,
  kind (text|number|integer), unit, check (regex on non-null values),
  list {separators: [..], known: {layer, column}} (optional, text columns),
  layer_pattern (gpkg: glob of layer names, e.g. "catchments_*"; all matching layers are merged into one layer; they must
    share columns and CRS; exact duplicate rows (same attributes and geometry) are dropped and logged),
  unique_key (column that must be unique after the merge/dedup; conflicting duplicates stop the run),
  column option `references` {layer, column}: every value must exist in that column of a layer processed earlier,
  code_from_location {to, prefix, decimals, ordinal_width, order_by[]} (point gpkg layers; the `to` column is declared
    in columns[] with "from": null): code = prefix + (lat+90) and (lon+180) in 10**-decimals units (digits only,
    7+7 for 4 decimals, ~11 m) + ordinal (1..n, zero padded) among rows at the same location, ordered by the `order_by` columns (then all other columns, then source order). Deterministic:
    independent of row order; unique; changes only if a point (or the text of the ordering columns) changes.
  split_suffix {to: new_column, separator (default ","), pattern (default 'Name (UF)')} (optional: 'Name (UF)' or a
  list of them -> this column = names, `to` = UFs in the same order, ' | ' joined; the `to` column is declared
  in columns[] with "from": null and is derived, not read)}.

List-like fields use " | " as the only item separator (config list_separator). A column with `list` has its
listed separators rewritten to " | ". A separator that is just "," is ambiguous (commas also occur inside names), so
it is only applied (outside parentheses) when `known` is given and EVERY item is a value of that reference column
(layer processed earlier in the same run); otherwise the value is left untouched and counted in the log.

Output per layer (never touches the input):
  <prefix>_<NAME>_<extent>_<year>.csv|gpkg          data (csv: ';', UTF-8, LF; gpkg layer '<prefix>_<name>' lowercase)
  <prefix>_<NAME>_<extent>_<year>_GLOSSARY.csv           column_name;description_pt;description_en;unit
  <prefix>_LAYERS_X_X.csv                           layer catalog

Rules: columns are renamed/ordered by the config; unexpected or missing source columns stop the layer.
Text: trimmed, inner whitespace collapsed; csv '-' / blank -> na_text (gpkg stays NULL).
Numbers: '-' / blank -> empty (csv) / NULL (gpkg); non numeric values stop the layer.
Every change is counted in the log. Swapped/shifted columns are caught by `check` and are NOT repaired.
"""
import argparse
import csv
import fnmatch
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pyogrio

REQUIRED = ["input_folder", "output_folder", "prefix", "extent", "year", "layers"]
LIST_SEP = " | "
KNOWN = {}  # (layer, column) -> set of lowercase values (items of list columns included), for `known` references


def split_outside_parens(text, sep):
    parts, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        depth += ch == "("
        depth -= ch == ")"
        if depth <= 0 and text.startswith(sep, i):
            parts.append(cur)
            cur, i = "", i + len(sep)
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return parts


def read_merged(src, lay, stats):
    import geopandas as gpd
    names = sorted(n for n, _ in pyogrio.list_layers(src) if fnmatch.fnmatch(n, lay["layer_pattern"]))
    if not names:
        sys.exit(f"  no layer matches {lay['layer_pattern']} in {src.name}")
    parts = [gpd.read_file(src, layer=n) for n in names]
    for n, p in zip(names, parts):
        if list(p.columns) != list(parts[0].columns) or p.crs != parts[0].crs:
            sys.exit(f"  layer {n} differs in columns or CRS from {names[0]}")
    gdf = pd.concat(parts, ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=parts[0].crs)
    before = len(gdf)
    key = gdf.drop(columns="geometry").astype("string").fillna("")
    key["_wkb"] = gdf.geometry.to_wkb(hex=True)
    gdf = gdf[~key.duplicated()].reset_index(drop=True)
    stats.append(f"merged {len(names)} layers ({', '.join(f'{n}: {len(p)}' for n, p in zip(names, parts))}) = {before} rows; "
                 f"exact duplicate rows dropped {before - len(gdf)}")
    if lay.get("unique_key") and gdf[lay["unique_key"]].duplicated().any():
        d = gdf[lay["unique_key"]][gdf[lay["unique_key"]].duplicated()].unique()[:5]
        sys.exit(f"  unique_key {lay['unique_key']} has conflicting duplicates, e.g. {list(d)}")
    return gdf


def location_digits(lat, lon, decimals):
    """Digits only: (lat + 90) and (lon + 180) scaled by 10**decimals, rounded, zero padded (7 + 7 digits for 4 decimals).
    The offsets keep both numbers positive, so the code is plain digits and can be read back: lat = n/10**d - 90."""
    k = 10 ** decimals
    la, lo = int(lat * k + 90 * k + 0.5), int(lon * k + 180 * k + 0.5)
    return f"{la:0{len(str(180 * k))}d}{lo:0{len(str(360 * k))}d}"


def add_location_code(df, gdf, cf, columns, stats):
    """prefix + lat/lon digits + ordinal among rows at the same location (ordered by order_by, then all columns, then source order)."""
    pts = []
    for g in gdf.geometry:
        if g is None or g.is_empty or len(getattr(g, "geoms", [g])) != 1:
            sys.exit("  code_from_location: every geometry must be a single point")
        p = g.geoms[0] if hasattr(g, "geoms") else g
        pts.append(p)
    gh = [location_digits(p.y, p.x, cf["decimals"]) for p in pts]
    key = df.drop(columns=[cf["to"]]).astype("string").fillna("")
    cols = cf["order_by"] + [c for c in key.columns if c not in cf["order_by"]]
    work = key[cols].copy()
    work["_gh"] = gh
    work["_src"] = range(len(work))
    work = work.sort_values(["_gh"] + cols + ["_src"], kind="mergesort")
    work["_ord"] = work.groupby("_gh").cumcount() + 1
    if work["_ord"].max() > 10 ** cf["ordinal_width"] - 1:
        sys.exit("  code_from_location: ordinal_width too small")
    work = work.sort_values("_src")
    df[cf["to"]] = [f"{cf['prefix']}{g}{o:0{cf['ordinal_width']}d}" for g, o in zip(work["_gh"], work["_ord"])]
    pat = next((c.get("check") for c in columns if c["to"] == cf["to"]), None)
    if pat and not df[cf["to"]].str.match(pat).all():
        sys.exit(f"  CHECK FAILED {cf['to']}: values not matching {pat}")
    if df[cf["to"]].duplicated().any():
        sys.exit(f"  code_from_location: {cf['to']} not unique")
    stats.append(f"{cf['to']}: {cf['prefix']}+lat/lon digits ({cf['decimals']} decimals)+ordinal{cf['ordinal_width']}; "
                 f"{len(set(gh))} distinct locations, {int(pd.Series(gh).duplicated(keep=False).sum())} rows share a location "
                 f"(max {int(work['_ord'].max())} per location)")


def split_suffix(df, col, alias, na_text, stats, sep=",", pattern=r"^(.*?)\s*\(([A-Z]{2})\)$"):
    """'Name (UF)' or a list 'A (UF), B (UF)' -> col 'Name' / 'A | B', alias 'UF' / 'UF | UF' (aligned items).
    `sep` splits the items (outside parentheses), `pattern` has 2 groups: name, UF ('-' or blank values stay null).
    Items without a '(UF)' suffix (e.g. cut at the source field length) keep the name and get na_text as alias."""
    n = {"cells": 0, "multi": 0, "no_uf": 0, "dropped": 0}
    names, ufs = [], []
    for v in df[col]:
        if v is pd.NA or v is None or pd.isna(v):
            names.append(pd.NA)
            ufs.append(pd.NA)
            continue
        txt = re.sub(r"[\s\u00a0]+", " ", str(v)).strip()
        if txt in ("", "-"):
            names.append(pd.NA)
            ufs.append(pd.NA)
            continue
        nm, uf = [], []
        for item in (x.strip() for x in split_outside_parens(txt, sep)):
            if item in ("", "()"):
                n["dropped"] += 1
                continue
            m = re.match(pattern, item)
            nm.append(m.group(1) if m else item)
            uf.append(m.group(2) if m else na_text)
            n["no_uf"] += m is None
        n["cells"] += 1
        n["multi"] += len(nm) > 1
        names.append(LIST_SEP.join(nm) if nm else pd.NA)
        ufs.append(LIST_SEP.join(uf) if uf else pd.NA)
    df[col] = pd.Series(names, index=df.index, dtype="object")
    df[alias] = pd.Series(ufs, index=df.index, dtype="object")
    stats.append(f"{col}: 'Name (UF)' split into {col} + {alias} in {n['cells']} cells ({n['multi']} multi-municipality lists, "
                 f"joined by '{LIST_SEP}' with aligned UFs); items without UF {n['no_uf']} (alias '{na_text}'), empty items dropped {n['dropped']}")


def to_list(value, spec, known, counts):
    """Rewrite list separators of one value to ' | '."""
    if value is pd.NA or value is None or pd.isna(value):
        return value
    for sep in spec["separators"]:
        if sep.strip() == ",":
            parts = [x.strip() for x in split_outside_parens(value, ",")]
            if len(parts) > 1:
                if known is not None and all(x.lower() in known for x in parts):
                    value = LIST_SEP.join(parts)
                    counts["comma_split"] += 1
                else:
                    counts["comma_kept"] += 1
        elif sep in value:
            value = value.replace(sep, LIST_SEP)
            counts["converted"] += 1
    return value


def log(msg):
    print(msg, flush=True)


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        sys.exit(f"config: missing keys {missing}")
    for lay in cfg["layers"]:
        tos = [c["to"] for c in lay["columns"]]
        if len(tos) != len(set(tos)):
            sys.exit(f"config: duplicate target columns in {lay['name']}")
    return cfg


def clean_text(s):
    """Trim and collapse whitespace; returns series and number of changed cells."""
    nn = s.notna()
    new = s.where(~nn, s.astype("string").str.replace(r"[\s\x{00a0}\x{2007}\x{202f}]+", " ", regex=True).str.strip())
    changed = int(((new != s) & nn).sum())
    return new, changed


def convert(df, lay, na_text, is_csv, stats):
    """Apply cleaning, kind rules, value maps and checks to a frame already renamed to target names."""
    for c in lay["columns"]:
        to, kind = c["to"], c.get("kind", "text")
        s = df[to]
        if kind == "text":
            s, n = clean_text(s)
            if n:
                stats.append(f"{to}: whitespace normalised in {n} cells")
            nul = s.isna() | (s == "") | (s == "-")
            dashes = int((s == "-").sum())
            if dashes:
                stats.append(f"{to}: '-' -> null in {dashes} cells")
            s = s.mask(nul, pd.NA)
            if c.get("list") and c["list"]["separators"]:
                spec = c["list"]
                ref = spec.get("known")
                known = None
                if ref:
                    known = KNOWN.get((ref["layer"], ref["column"]))
                    if known is None:
                        sys.exit(f"  list reference {ref['layer']}.{ref['column']} not processed yet (layer order / --only)")
                counts = {"converted": 0, "comma_split": 0, "comma_kept": 0}
                s = s.map(lambda v: to_list(v, spec, known, counts))
                stats.append(f"{to}: list separators -> '{LIST_SEP}' in {counts['converted']} cells"
                             + (f", comma lists split {counts['comma_split']} (all items known), left unchanged {counts['comma_kept']}"
                                if any(x.strip() == "," for x in spec["separators"]) else ""))
            maps = lay.get("value_maps", {}).get(to)
            if maps:
                for old, new in maps.items():
                    n = int((s == old).sum())
                    if n:
                        stats.append(f"{to}: '{old}' -> '{new}' in {n} cells")
                s = s.replace(maps)
            if c.get("check"):
                bad = s.dropna()[~s.dropna().astype(str).str.match(c["check"])]
                if len(bad):
                    sys.exit(f"  CHECK FAILED {to}: {len(bad)} values not matching {c['check']}, e.g. {list(bad.unique()[:5])}"
                             " (shifted/swapped columns?)")
            if is_csv and na_text is not None:
                s = s.fillna(na_text)
        else:
            raw = s.astype("string").str.strip()
            nul = raw.isna() | (raw == "") | (raw == "-")
            n = int((nul & s.notna()).sum())
            if n:
                stats.append(f"{to}: '-'/blank -> null in {n} cells")
            num = pd.to_numeric(raw.mask(nul, pd.NA), errors="coerce")
            bad = raw[~nul & num.isna()]
            if len(bad):
                sys.exit(f"  CHECK FAILED {to}: {len(bad)} non numeric values, e.g. {list(bad.unique()[:5])}")
            if kind == "integer":
                frac = num.dropna() % 1 != 0
                if frac.any():
                    sys.exit(f"  CHECK FAILED {to}: non integer values in integer column")
                s = num.astype("Int64")
            else:
                s = raw.mask(nul, pd.NA) if is_csv else num  # csv: keep original number text
        df[to] = s
    return df


def read_csv(path, lay):
    df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False, na_values=[], encoding="utf-8-sig")
    df = df.replace({"": pd.NA})
    return df


def validate_columns(have, lay):
    want = [c["from"] for c in lay["columns"] if c["from"]]
    miss = [c for c in want if c not in have]
    extra = [c for c in have if c not in want and c not in lay.get("drop", []) and c != "geometry"]
    if miss or extra:
        sys.exit(f"  columns differ from config: missing {miss}, unexpected {extra}")


def out_names(cfg, lay):
    p, e, y, n = cfg["prefix"], cfg["extent"], cfg["year"], lay["name"]
    ext = "csv" if lay["type"] == "csv" else "gpkg"
    return (f"{p}_{n}_{e}_{y}.{ext}", f"{p}_{n}_{e}_{y}_GLOSSARY.csv", f"{p}_{n.lower()}".replace("-", "").lower())


def write_glossary(path, lay):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["column_name", "description_pt", "description_en", "unit"])
        for c in lay["columns"]:
            pt, en = c["description_pt"], c["description_en"]
            if c.get("list"):
                pt, en = f"{pt}. Lista separada por '{LIST_SEP}'", f"{en}. List separated by '{LIST_SEP}'"
            w.writerow([c["to"], pt, en, c.get("unit", "")])


def process(cfg, lay, args, catalog):
    indir, outdir = Path(cfg["input_folder"]), Path(cfg["output_folder"])
    data_name, gloss_name, layer_name = out_names(cfg, lay)
    src = indir / lay["source"]
    log(f"[{lay['name']}] {lay['source']} -> {data_name}")
    stats = []
    mapping = {c["from"]: c["to"] for c in lay["columns"] if c["from"]}
    order = [c["to"] for c in lay["columns"]]
    is_csv = lay["type"] == "csv"
    if is_csv:
        df = read_csv(src, lay)
        validate_columns(list(df.columns), lay)
        gdf = None
    else:
        import geopandas as gpd
        if lay.get("layer_pattern"):
            gdf = read_merged(src, lay, stats)
        else:
            gdf = gpd.read_file(src, layer=lay.get("layer_in"))
        validate_columns(list(gdf.columns), lay)
        df = pd.DataFrame(gdf.drop(columns="geometry"))
    if lay.get("drop"):
        log(f"    purged columns: {', '.join(lay['drop'])}")
    df = df.rename(columns=mapping)
    if lay.get("code_from_location"):
        df[lay["code_from_location"]["to"]] = pd.NA  # filled after cleaning (needs clean order_by text)
    for c in lay["columns"]:
        if c.get("split_suffix"):
            sp = c["split_suffix"]
            split_suffix(df, c["to"], sp["to"], cfg.get("na_text", "NA"), stats, sp.get("separator", ","),
                         sp.get("pattern", r"^(.*?)\s*\(([A-Z]{2})\)$"))
    df = df[order]
    df = convert(df, lay, cfg.get("na_text", "NA"), is_csv, stats)
    if lay.get("code_from_location"):
        add_location_code(df, gdf, lay["code_from_location"], lay["columns"], stats)
    for c in lay["columns"]:
        ref = c.get("references")
        if ref:
            known = KNOWN.get((ref["layer"], ref["column"]))
            if known is None:
                sys.exit(f"  reference {ref['layer']}.{ref['column']} not processed yet (layer order / --only)")
            miss = sorted(set(df[c["to"]].dropna().astype(str).str.lower()) - known)
            if miss:
                sys.exit(f"  REFERENCE FAILED {c['to']}: {len(miss)} values not in {ref['layer']}.{ref['column']}, e.g. {miss[:3]}")
            stats.append(f"{c['to']}: all values exist in {ref['layer']}.{ref['column']}")
    wanted = {(c["list"]["known"]["layer"], c["list"]["known"]["column"]) for l in cfg["layers"] for c in l["columns"]
              if c.get("list", {}).get("known")}
    wanted |= {(c["references"]["layer"], c["references"]["column"]) for l in cfg["layers"] for c in l["columns"]
               if c.get("references")}
    for (ln, cn) in wanted:
        if ln == lay["name"] and cn in df.columns:
            vals = set()
            for v in df[cn].dropna().astype(str):
                vals.update(x.strip().lower() for x in v.split(LIST_SEP))
            KNOWN[(ln, cn)] = vals
    for s in stats:
        log(f"    {s}")
    n_key = None
    if "municipio_code" in df.columns and not (df["municipio_code"].duplicated().any()):
        n_key = "unique"
    log(f"    rows {len(df)}, columns {len(df.columns)}, municipio_code {'unique' if n_key else 'repeated or absent'}")
    catalog.append([lay["name"], data_name, layer_name if not is_csv else "", lay["type"], len(df),
                    lay["description_pt"], lay["description_en"]])
    if args.dry_run:
        return
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / data_name
    if is_csv:
        df.to_csv(target, sep=";", index=False, encoding="utf-8", lineterminator="\n")
    else:
        import geopandas as gpd
        out = gpd.GeoDataFrame(df, geometry=gdf.geometry.values, crs=gdf.crs)
        out.to_file(target, layer=layer_name, driver="GPKG")
    write_glossary(outdir / gloss_name, lay)


def existing_outputs(cfg, layers, with_catalog):
    """Output files of this run that already exist (the guard against overwriting T1)."""
    outdir = Path(cfg["output_folder"])
    names = [n for lay in layers for n in out_names(cfg, lay)[:2]]
    if with_catalog:
        names.append(f"{cfg['prefix']}_LAYERS_X_X.csv")
    return [outdir / n for n in names if (outdir / n).exists()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--only", help="comma list of layer names")
    ap.add_argument("--dry-run", action="store_true", help="read, validate and log; write nothing")
    args = ap.parse_args()
    cfg = load_config(args.config)
    only = set(args.only.split(",")) if args.only else None
    layers = [lay for lay in cfg["layers"] if not only or lay["name"] in only]
    if not args.dry_run:
        found = existing_outputs(cfg, layers, not only)
        if found:
            sys.exit(f"REFUSED: {len(found)} output files already exist in {cfg['output_folder']}, e.g. {found[0].name}.\n"
                     "This script is archived; a re-run would overwrite T1 (revised catchments, intake codes). "
                     "Write to a new, empty output_folder.")
    catalog = []
    for lay in layers:
        process(cfg, lay, args, catalog)
    if not args.dry_run and not only:
        path = Path(cfg["output_folder"]) / f"{cfg['prefix']}_LAYERS_X_X.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";", lineterminator="\n")
            w.writerow(["layer_name", "file_name", "gpkg_layer", "file_type", "rows", "description_pt", "description_en"])
            w.writerows(catalog)
        log(f"catalog: {path}")


if __name__ == "__main__":
    main()
