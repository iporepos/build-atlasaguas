#!/usr/bin/env python3
"""Build the Atlas Aguas T2 relational GeoPackage from T1 (standard).

Usage (project venv):  .venv/bin/python build_database.py --config build_database.local.json [--overwrite]

Config keys: input_folder (T1 standard), output_gpkg, report_folder, catalog_layers (T1 LAYERS csv),
  schema (JSON with every table: columns, types, keys, checks, bilingual descriptions; also drives the catalogs),
  provisioning (optional: area_crs, default ESRI:102033; nested_threshold, default 0.5; clean_tolerance, default 0.01;
  within_min_part_km2, default 0.01),
  municipio_aliases (optional list of {name, unidade_alias, to}: old or renamed municipality names in the intake and
  system municipality lists, resolved to the DTB name `to` in the same state).

T2 is NOT a copy of the T1 layout. It is a normalized schema (see build_database_schema.json, 15 tables: 8 plain + 7 spatial; 2 views):
  * naming: plural table names; `municipios` and `sedes` are the Portuguese exception; <entity>_<descriptor>;
  * spatial layers carry their own descriptive columns (no separate attribute tables, so QGIS needs no join):
    municipios (incl. region, operator and metropolitan region as simple columns), municipios_sedes (key only),
    intakes, aqueducts, catchments, provisioning_areas, provisioning_areas_within;
  * provisioning_areas (water-supply-nomenclature.md): one row per municipality, MultiPolygon dissolve of the catchments
    of the intakes linked by view provisioning_links = intakes_municipios (direct) UNION intakes_systems -> systems_supply
    (covered_percent > 0); never by spatial intersection. NULL geometry without surface intake (source_mix says why;
    n_intakes_system_only counts intakes reached only through an integrated system). Topology S / M-N / M-D /
    M-X from pairwise catchment overlap (intersection >= nested_threshold of the smaller one = nested, else disjoint;
    pairs not clean, between clean_tolerance and 1 - clean_tolerance, go to provisioning_partial_overlaps.csv).
    Every hole of the dissolve is filled: catchments have none, so a hole is a gap between neighbouring catchments (an
    area enclosed by catchments drains through them); filled holes go to provisioning_filled_holes.csv. A stored
    derived geometry (a dissolve cannot be a view in a GeoPackage); never sum its areas (shared intakes overlap);
    upstream: n_intakes_surface_upstream = surface intake points inside the filled area (spatial join) not linked to the
    municipality; covered_population_urban_upstream_2020 = covered population of their systems' surface supply rows in
    other municipalities, each row once (the whole system counts even if one intake is upstream); NULL without area;
  * provisioning_areas_within: the provisioning area clipped to the municipality's own polygon, polygon parts smaller
    than within_min_part_km2 dropped (border slivers, listed in provisioning_within_dropped_parts.csv). Same rows as
    provisioning_areas: NULL attributes without provisioning area; NULL geometry, area 0 and n_parts 0 when nothing is
    left inside; share = fraction of the provisioning area inside, municipio_percent = percent of the municipality covered. The link is still the supply relation: the intersection only clips an area already linked;
  * geometry checks after the dissolve and the clip: valid, non-empty MultiPolygon, no holes in the dissolve, area of
    the raw dissolve within [largest catchment, sum of catchments], clip within the provisioning area and the municipality;
  * relations instead of list columns: systems_supply (system x municipality x source, with the share),
    intakes_systems, intakes_municipios, proposals_municipios;
  * repeated column groups become rows: municipios_indicators (year; population, demand and ISH),
    municipios_investments (group, component, period); proposals are one row per proposal;
  * derived values (totals, counts, assigned/covered population) are not stored (view systems_supply_population);
  * catalogs `tables` and `fields` document every table/column (pt, en, unit).
Plain tables are created with real PRIMARY KEY / FOREIGN KEY / NOT NULL / CHECK constraints (foreign keys are
checked at the end with PRAGMA foreign_key_check). Spatial layers are written by GDAL and cannot carry constraints: their
key is unique-indexed (so plain tables can reference them), and their declared types, NOT NULL, CHECK (may use geom),
foreign keys, geometry type and geometry NOT NULL (unless geometry.nullable) are verified by SQL after loading.
'NA'/empty text of T1 become NULL.
Systems have no key in the source: a system is (name + the municipalities connected through the municipality
lists of SYSTEMS-MUNICIPALITIES in T1), found by connected components.
The intake's municipality text lists the municipalities it SUPPLIES (matches the system-derived set for 99% of intakes; it
is not the point location): it becomes intakes_municipios (direct link). Names resolve by normalized name + UF, then
municipio_aliases (config), then, for items cut at the source field length (no UF), a unique name prefix (ties broken by
the states of the other items of the list, then by the candidate containing the intake point). Intakes are linked to systems by name (exact, list-named system parts,
generic-prefix variants within the intake's municipalities, comma lists split); the intake municipalities disambiguate.
Unresolved items are written to report_folder (intake_municipality_unmatched.csv, intake_system_unmatched.csv).
Catchments: before reading T1, the T1 catchments file is checked against its geometry hashes
(revise_catchments.check_catchments): the build stops if a catchment was edited after the last revise_catchments.py
run (its area, n_parts and source would be stale) or if revise_catchments.py --init was never run.
Always built from zero: needs --overwrite if the output exists; builds <name>.part.gpkg then renames.
"""
import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

import revise_catchments

REQUIRED = ["input_folder", "output_gpkg", "catalog_layers", "schema"]
LIST_SEP = " | "
SYSTEM_PREFIXES = {"sistema", "ssistema", "isolado", "integrado", "eta", "poco", "pocos"}


def log(m):
    print(m, flush=True)


def norm(s):
    """Accent/case/punctuation-insensitive key for names."""
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())


class Source:
    def __init__(self, folder, catalog):
        self.folder = Path(folder)
        self.cat = pd.read_csv(self.folder / catalog, sep=";", dtype=str, keep_default_na=False).set_index("layer_name")

    def table(self, layer):
        r = self.cat.loc[layer]
        path = self.folder / r["file_name"]
        if r["file_type"] == "csv":
            df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False, na_values=["", "NA"])
        else:
            df = gpd.read_file(path, layer=r["gpkg_layer"])
        log(f"  read {layer}: {len(df)} rows")
        return df


def num(s):
    return pd.to_numeric(s, errors="coerce")


# --------------------------------------------------------------------------- transforms
def name_key(s):
    """Normalized system name without leading generic words (Sistema, Isolado, ETA, Poço...)."""
    w = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().split()
    while len(w) > 1 and w[0] in SYSTEM_PREFIXES:
        w = w[1:]
    return norm(" ".join(w))


def build_tables(src, report, opts):
    t = {}  # table -> DataFrame (plain tables) ; geo[table] -> GeoDataFrame (spatial layers with their attributes)
    geo = {}
    mun_g = src.table("MUNICIPALITIES")
    seat_g = src.table("SEATS")
    ish = src.table("ISH")
    ss = src.table("SOURCE-SYSTEMS")
    invd = src.table("INVESTMENT-DISTRIBUTION")
    invp = src.table("INVESTMENT-PRODUCTION")
    sm = src.table("SYSTEMS-MUNICIPALITIES")
    itk = src.table("INTAKES")
    aq = src.table("AQUEDUCTS")
    cat = src.table("CATCHMENTS")

    # region of each state (from ISH / INVESTMENT-DISTRIBUTION); states are not a table
    uni = pd.concat([ish[["unidade_alias", "regiao_name"]], invd[["unidade_alias", "regiao_name"]]]).drop_duplicates()
    if uni.unidade_alias.duplicated().any():
        sys.exit("a state maps to more than one region")
    region = dict(zip(uni.unidade_alias, uni.regiao_name))
    missing = (set(mun_g.unidade_alias) | set(aq.unidade_alias.dropna())) - set(region)
    if missing:
        sys.exit(f"region missing for states {missing}")

    # municipalities (DTB is the truth for name/state/area); operator and metropolitan region are plain attributes
    m = mun_g[["municipio_code", "municipio_name", "unidade_alias", "area_km2"]].copy()
    m.insert(3, "regiao_name", m.unidade_alias.map(region))
    ssi = ss.set_index("municipio_code")
    for col in ("metropolitan_region_name", "operator_name", "operator_type"):  # simple attributes, not tables
        m[col] = m.municipio_code.map(ssi[col])
    names = m.set_index("municipio_code").municipio_name
    for lay, df in (("ISH", ish), ("SOURCE-SYSTEMS", ss), ("SYSTEMS-MUNICIPALITIES", sm)):
        d = (df.municipio_code.map(names) != df.municipio_name).sum()
        if d:
            log(f"  note: {lay} has {d} rows whose municipio_name differs from the DTB name (DTB name kept)")
    for lay, df in (("ISH", ish), ("SOURCE-SYSTEMS", ss), ("SYSTEMS-MUNICIPALITIES", sm), ("INVESTMENT-DISTRIBUTION", invd), ("INVESTMENT-PRODUCTION", invp)):
        miss = set(df.municipio_code) - set(m.municipio_code)
        if miss:
            sys.exit(f"{lay}: municipio_code not in municipalities: {sorted(miss)[:5]}")
    geo["municipios"] = gpd.GeoDataFrame(m.reset_index(drop=True), geometry=mun_g.geometry.values, crs=mun_g.crs)

    # indicators by year: population/demand (2020, 2035) + ISH (2020)
    pop = []
    for y in (2020, 2035):
        pop.append(pd.DataFrame({"municipio_code": ss.municipio_code, "year": y, "population_urban": num(ss[f"population_urban_{y}"]),
                                 "demand_urban": num(ss[f"demand_urban_{y}"])}))
    pop = pd.concat(pop, ignore_index=True)
    chk = num(ish.set_index("municipio_code").population_urban_2020) - pop.query("year == 2020").set_index("municipio_code").population_urban.reindex(ish.municipio_code).values
    if chk.abs().max() > 1:
        sys.exit("ISH population differs from SOURCE-SYSTEMS population")
    i2 = ish.drop(columns=["municipio_name", "unidade_alias", "regiao_name", "population_urban_2020"]).copy()
    i2.columns = [c[:-5] if c.endswith("_2020") else c for c in i2.columns]
    i2.insert(1, "year", 2020)
    i2["supply_coverage"] = num(i2.supply_coverage)
    i2["supply_coverage_filled"] = num(i2.supply_coverage_filled)
    t["municipios_indicators"] = pop.merge(i2, on=["municipio_code", "year"], how="left")

    # investments: wide -> long (totals are derivable and checked)
    comps, rows = {"network": "network", "connections": "connections", "storage": "storage"}, []
    for grp in ("distribution", "replacement"):
        tot = 0
        for c in invd.columns:
            mm = re.fullmatch(rf"investment_{grp}_(network|connections|storage)_(until2025|2026to2030|2031to2035|until2035)", c)
            if mm:
                tot = tot + num(invd[c]).fillna(0)
                rows.append(pd.DataFrame({"municipio_code": invd.municipio_code, "investment_group": grp, "component": mm.group(1),
                                          "period": mm.group(2), "amount_brl": num(invd[c])}))
        if not np.allclose(tot, num(invd[f"investment_{grp}_total_until2035"]).fillna(0), rtol=1e-6):
            sys.exit(f"investment_{grp}_total_until2035 is not the sum of its components")
    inv = pd.concat(rows, ignore_index=True).dropna(subset=["amount_brl"])
    t["municipios_investments"] = inv.reset_index(drop=True)

    # production proposals: one row per distinct proposal, municipalities as relation
    p = invp.copy()
    kind = p.planning_type.map(lambda x: "alternatives" if x.startswith("Estudos") else ("potential" if "Potencial" in x else "recommended"))
    amount = np.select([kind == "alternatives", kind == "potential"], [num(p.alternatives_investment), num(p.investment_potential)], num(p.investment_recommended))
    served = p.alternatives_served_municipios_name.where(kind == "alternatives", p.served_municipios_name)
    served_uf = p.alternatives_served_unidades_alias.where(kind == "alternatives", p.served_unidades_alias)
    p = p.assign(investment_kind=kind, investment_million_brl=amount, _served=served.fillna("") + "#" + served_uf.fillna(""))
    cols = ["planning_type", "proposal_name", "intervention_type", "source_name", "complementary_study_required", "investment_kind", "investment_million_brl", "_served"]
    key = p[cols].astype("string").fillna("")
    uniq = key.drop_duplicates().sort_values(cols).reset_index(drop=True)
    uniq["proposal_id"] = range(1, len(uniq) + 1)
    p["_k"] = key.agg("\x1f".join, axis=1)
    uniq["_k"] = uniq[cols].agg("\x1f".join, axis=1)
    pid = dict(zip(uniq._k, uniq.proposal_id))
    p["proposal_id"] = p._k.map(pid)
    first = p.drop_duplicates("proposal_id").set_index("proposal_id").sort_index()
    t["proposals"] = first[["planning_type", "proposal_name", "intervention_type", "source_name",
                                      "complementary_study_required", "investment_kind", "investment_million_brl"]].reset_index()
    t["proposals_municipios"] = p[["proposal_id", "municipio_code"]].drop_duplicates().reset_index(drop=True)
    log(f"  production: {len(invp)} rows -> {len(first)} proposals, {len(t['proposals_municipios'])} proposal-municipality links; "
        f"sum investment {first.investment_million_brl.sum():,.0f} (summing the T1 rows would give {pd.Series(amount).sum():,.0f})")

    # municipality lookup by normalized name + UF; aliases (config) for old/renamed names; prefix for names cut at the source
    mk, amb = {}, set()
    for c, n_, u in zip(m.municipio_code, m.municipio_name, m.unidade_alias):
        k = (norm(n_), u)
        if k in mk:
            amb.add(k)
        mk[k] = c
    for k in amb:
        del mk[k]
    alias = {}
    for a_ in opts.get("municipio_aliases", []):
        c = mk.get((norm(a_["to"]), a_["unidade_alias"]))
        if not c:
            sys.exit(f"municipio_aliases: target {a_['to']} ({a_['unidade_alias']}) is not a municipality")
        alias[(norm(a_["name"]), a_["unidade_alias"])] = c
    mgeom = dict(zip(mun_g.municipio_code, mun_g.geometry.values))
    mnorm = list(zip(m.municipio_code, m.municipio_name.map(norm), m.unidade_alias))

    def resolve(name, uf, point=None, list_ufs=()):
        """(municipio_code, method) or (None, None). Prefix only for items without state (cut at the source); ties broken
        by the states of the other items of the same list, then by the municipality containing the point."""
        k = (norm(name), uf)
        if k in mk:
            return mk[k], "exact"
        if k in alias:
            return alias[k], "alias"
        if uf in ("", "NA", None) or pd.isna(uf):
            pre = norm(re.sub(r"\s*\([^)]*$", "", str(name)))
            cands = [(c, u) for c, n_, u in mnorm if n_.startswith(pre)] if len(pre) >= 4 else []
            if len(cands) > 1 and list_ufs:
                cands = [x for x in cands if x[1] in list_ufs]
            cands = [c for c, _ in cands]
            if len(cands) > 1 and point is not None:
                cands = [c for c in cands if mgeom[c].contains(point)]
            if len(cands) == 1:
                return cands[0], "prefix"
        return None, None

    # systems: connected components of (system name, municipality) nodes joined through the municipality lists
    sm = sm.copy()
    sm["cf"] = sm.system_name.str.casefold()
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for r in sm.itertuples():
        a = (r.cf, r.municipio_code)
        find(a)
        for nm, uf in zip(str(r.system_municipios_name).split(LIST_SEP), str(r.system_unidades_alias).split(LIST_SEP)):
            c = resolve(nm, uf)[0]
            if c:
                union(a, (r.cf, c))
    comp = {}
    for node in list(parent):
        comp.setdefault(find(node), []).append(node)
    ordered = sorted(comp.values(), key=lambda ns: (min(n[0] for n in ns), min(n[1] for n in ns)))
    node_sys, sys_rows, sysmun = {}, [], []
    display = sm.drop_duplicates("cf").set_index("cf").system_name
    stype = sm.groupby("cf").system_type.agg(lambda s: s.dropna().iloc[0] if s.notna().any() else None)
    conflicts = sm.groupby("cf").system_type.nunique().gt(1).sum()
    for sid, ns in enumerate(ordered, 1):
        cf = ns[0][0]
        sys_rows.append((sid, display[cf], stype[cf]))
        for node in ns:
            node_sys[node] = sid
            sysmun.append((sid, node[1]))
    t["systems"] = pd.DataFrame(sys_rows, columns=["system_id", "system_name", "system_type"])
    bad_mun = {c for _, c in sysmun} - set(m.municipio_code)
    if bad_mun:
        sys.exit(f"system municipalities: unknown municipalities {sorted(bad_mun)[:5]}")
    smun = pd.DataFrame(sysmun, columns=["system_id", "municipio_code"]).drop_duplicates().groupby("system_id").municipio_code.apply(set).to_dict()
    sup = pd.DataFrame({"system_id": [node_sys[(a, b)] for a, b in zip(sm.cf, sm.municipio_code)], "municipio_code": sm.municipio_code,
                        "source_name": sm.source_name, "intake_type": sm.intake_type, "covered_percent": num(sm.intake_covered_percent)})
    sup.insert(0, "supply_id", range(1, len(sup) + 1))
    t["systems_supply"] = sup
    sums = sup.groupby("municipio_code").covered_percent.sum()
    linked = sup[["system_id", "municipio_code"]].drop_duplicates()
    log(f"  systems: {len(sm)} supply rows -> {len(ordered)} systems (type conflicts by name: {conflicts}); "
        f"{sum(len(v) for v in smun.values()) - len(linked)} system-municipality links from the lists have no supply row (used only to resolve intakes); "
        f"covered_percent per municipality min {sums.min():.2f} max {sums.max():.2f}")

    # intakes (point layer with attributes); municipalities and systems are resolved, not stored as lists
    itk = itk.copy()
    if itk.intake_code.duplicated().any():
        sys.exit("intakes: intake_code not unique")
    wb = itk[["waterbody_code", "waterbody_name"]].dropna(subset=["waterbody_code"]).drop_duplicates()
    if wb.waterbody_code.duplicated().any():
        sys.exit("a water body code has more than one name")
    ia = itk[["intake_code", "intake_name", "intake_tradename", "intake_type", "intake_use_status", "treatment_type", "waterbody_code", "waterbody_name"]].copy()
    ia["location_method"] = itk.geometry_note
    geo["intakes"] = gpd.GeoDataFrame(ia.reset_index(drop=True), geometry=itk.geometry.values, crs=itk.crs)

    # intake municipalities: the intake's own list of SUPPLIED municipalities (direct link; also used to resolve systems)
    imun, unm, iml = {}, [], []
    for r in itk.itertuples():
        if pd.isna(r.municipio_name):
            continue
        pt = r.geometry.representative_point() if r.geometry is not None else None
        ufs = str(r.unidade_alias).split(LIST_SEP)
        for nm, uf in zip(str(r.municipio_name).split(LIST_SEP), ufs):
            c, how_ = resolve(nm, uf, pt, set(ufs) - {"NA", ""})
            if c:
                if c not in imun.setdefault(r.intake_code, set()):
                    iml.append((r.intake_code, c, how_))
                imun[r.intake_code].add(c)
            else:
                unm.append((r.intake_code, nm, uf))
    t["intakes_municipios"] = pd.DataFrame(iml, columns=["intake_code", "municipio_code", "match_method"])
    report["intake_municipality_unmatched.csv"] = pd.DataFrame(unm, columns=["intake_code", "municipality_text", "unidade_alias"])
    log(f"  intakes_municipios: {len(iml)} links {t['intakes_municipios'].match_method.value_counts().to_dict()}; unresolved items {len(unm)} "
        f"({itk.intake_code.nunique() - len(imun)} intakes without any municipality)")

    # intake -> systems. A system name may itself be a list ('Recanto | Lopes': one share for several names): any part matches.
    # Order: exact name with municipality overlap, unique exact name, name without generic prefix (Sistema/ETA/Poço...) among the
    # systems of the intake's municipalities; an unresolved comma list ('A, B') is split and each part tried the same way.
    by_name, by_key = {}, {}
    for sid, nm in zip(t["systems"].system_id, t["systems"].system_name):
        for part in {nm} | set(nm.split(LIST_SEP)):
            by_name.setdefault(part.strip().casefold(), set()).add(sid)
            by_key.setdefault(name_key(part), set()).add(sid)

    def match(item, mu):
        cands = sorted(by_name.get(item.strip().casefold(), set()))
        ov = [s_ for s_ in cands if smun.get(s_, set()) & mu]
        if ov:
            return ov, "overlap"
        if len(cands) == 1:
            return cands, "unique_name"
        local = [s_ for s_ in sorted(by_key.get(name_key(item), set())) if smun.get(s_, set()) & mu]
        if len(local) == 1:
            return local, "prefix_variant"
        return [], ("ambiguous name, no municipality overlap" if cands else "no system with this name")

    isy, unr, how = [], [], {"overlap": 0, "unique_name": 0, "prefix_variant": 0, "comma_part": 0}
    for r in itk.itertuples():
        if pd.isna(r.system_name):
            unr.append((r.intake_code, "", "no system name"))
            continue
        mu = imun.get(r.intake_code, set())
        for item in str(r.system_name).split(LIST_SEP):
            found, why = match(item, mu)
            if found:
                isy += [(r.intake_code, s_) for s_ in found]
                how[why] += 1
            elif "," in item:
                for part in filter(None, (x.strip() for x in item.split(","))):
                    found, why = match(part, mu)
                    if found:
                        isy += [(r.intake_code, s_) for s_ in found]
                        how["comma_part"] += 1
                    else:
                        unr.append((r.intake_code, part, why + " (part of a comma list)"))
            else:
                unr.append((r.intake_code, item, why))
    t["intakes_systems"] = pd.DataFrame(isy, columns=["intake_code", "system_id"]).drop_duplicates().reset_index(drop=True)
    unr = pd.DataFrame(unr, columns=["intake_code", "system_name_item", "reason"])
    unr["has_direct_municipio"] = unr.intake_code.isin(imun.keys())
    report["intake_system_unmatched.csv"] = unr
    log(f"  intakes_systems: {len(t['intakes_systems'])} links ({how}); unresolved {len(unr)} "
        f"({unr.intake_code.nunique()} intakes with at least one unresolved item, {itk.intake_code.nunique() - t['intakes_systems'].intake_code.nunique()} intakes without any system, "
        f"of these {len(set(itk.intake_code) - set(t['intakes_systems'].intake_code) - set(imun))} also without municipality)")

    # aqueducts, catchments, seats (spatial layers with their own attributes)
    geo["aqueducts"] = aq.reset_index(drop=True)
    geo["catchments"] = cat.reset_index(drop=True)
    log(f"  catchments: {len(cat)}, sources {cat.catchment_source.value_counts().to_dict()}, "
        f"multipart {int((num(cat.n_parts) > 1).sum())}")
    geo["municipios_sedes"] = gpd.GeoDataFrame(seat_g[["municipio_code"]], geometry=seat_g.geometry.values, crs=seat_g.crs)
    return t, geo


def polygon_parts(g):
    """Polygon parts of any geometry (lines and points left by an intersection or make_valid are dropped)."""
    return [p for p in shapely.get_parts(shapely.get_parts(g)) if p.geom_type == "Polygon" and not p.is_empty]


def multi(parts):
    return shapely.MultiPolygon(parts) if parts else None


def check_polygons(name, keys, gs, holes_allowed):
    """Stop unless every geometry is NULL or a valid, non-empty MultiPolygon (and, if asked, without holes)."""
    bad = {}
    for k, g in zip(keys, gs):
        if g is None:
            continue
        why = ("not MultiPolygon" if g.geom_type != "MultiPolygon" else "empty" if g.is_empty else
               "invalid: " + shapely.is_valid_reason(g) if not g.is_valid else
               "has holes" if not holes_allowed and any(len(p.interiors) for p in g.geoms) else None)
        if why:
            bad[k] = why
    if bad:
        sys.exit(f"{name}: {len(bad)} bad geometries {dict(list(bad.items())[:5])}")


def build_within(geo, pa, gs, area_crs, min_part, report):
    """provisioning_areas_within: each provisioning area clipped to its own municipality polygon; parts below min_part km2
    (border slivers) are dropped. NULL attributes without provisioning area; NULL geometry, area 0, n_parts 0 if none left.
    municipio_percent: area_km2 over the municipality polygon area, both in area_crs."""
    mun = geo["municipios"]
    mgeom = dict(zip(mun.municipio_code, shapely.make_valid(mun.geometry.values)))
    keys, parts = [], []
    for mu, g in zip(pa.municipio_code, gs):
        if g is not None:
            for p in polygon_parts(shapely.intersection(g, mgeom[mu])):
                keys.append(mu)
                parts.append(p)
    pk = pd.DataFrame({"municipio_code": keys, "a": gpd.GeoSeries(parts, crs=gs.crs).to_crs(area_crs).area.values / 1e6})
    keep = pk.a >= min_part
    report["provisioning_within_dropped_parts.csv"] = pk[~keep].rename(columns={"a": "part_area_km2"}).round(6)
    kept = {}
    for mu, p in zip(pk.municipio_code[keep], np.array(parts, dtype=object)[keep.values]):
        kept.setdefault(mu, []).append(p)
    wg = gpd.GeoSeries([multi(kept.get(mu, [])) for mu in pa.municipio_code], crs=gs.crs)
    check_polygons("provisioning_areas_within", pa.municipio_code, wg, holes_allowed=True)  # municipal enclaves are real holes
    has = pa.area_km2.notna().values
    w = pd.DataFrame({"municipio_code": pa.municipio_code.values, "municipio_name": pa.municipio_name.values})
    w["area_km2"] = np.where(has, wg.to_crs(area_crs).area.fillna(0).values / 1e6, np.nan)
    w["n_parts"] = pd.array([len(kept.get(mu, [])) if h else None for mu, h in zip(pa.municipio_code, has)], dtype="Int64")
    share = w.area_km2.values / pa.area_km2.values
    marea = mun.set_index("municipio_code").geometry.to_crs(area_crs).area.reindex(pa.municipio_code).values / 1e6
    if (share > 1 + 1e-9).any() or (w.area_km2.values > marea * (1 + 1e-6)).any():
        sys.exit("provisioning_areas_within: clipped area larger than the provisioning area or the municipality")
    w["share"] = np.minimum(share, 1.0)
    w["municipio_percent"] = np.minimum(w.area_km2.values / marea * 100, 100.0)
    geo["provisioning_areas_within"] = gpd.GeoDataFrame(w, geometry=wg.values, crs=gs.crs)
    s = w.share.dropna()
    log(f"  provisioning_areas_within: {int(wg.notna().sum())} with geometry, {int((s == 0).sum())} entirely outside the municipality, "
        f"{int((s > 0.999).sum())} at least 99.9% inside, median share {s.median():.3f}, median municipio_percent {w.municipio_percent.median():.1f}; "
        f"{int((~keep).sum())} parts below {min_part} km2 dropped ({pk.a[~keep].sum():.4f} km2)")


def build_provisioning(t, geo, opts, report):
    """Provisioning area per municipality: dissolve of the catchments of its intakes (direct link and/or through the system).

    Links = intakes_municipios (direct) UNION intakes_systems x systems_supply with covered_percent > 0; the same rule is the
    SQL of the view provisioning_links (checked against it after the build)."""
    area_crs = opts.get("area_crs", "ESRI:102033")
    tol = float(opts.get("clean_tolerance", 0.01))
    nested_at = float(opts.get("nested_threshold", 0.5))
    sup = t["systems_supply"]
    sup = sup[sup.covered_percent > 0]
    direct = t["intakes_municipios"][["intake_code", "municipio_code"]].assign(d=1, s=0)
    via = t["intakes_systems"].merge(sup[["system_id", "municipio_code"]], on="system_id")[["intake_code", "municipio_code"]].assign(d=0, s=1)
    link = pd.concat([direct, via]).groupby(["intake_code", "municipio_code"], as_index=False)[["d", "s"]].max()
    link["link_source"] = np.select([link.d.eq(1) & link.s.eq(1), link.d.eq(1)], ["both", "direct"], "system")
    t["provisioning_links"] = link[["intake_code", "municipio_code", "link_source"]]
    # convenience columns for QGIS (catchment revision): supplied municipality names per intake, intake name per catchment
    names = link.municipio_code.map(geo["municipios"].set_index("municipio_code").municipio_name)
    mun_list = names.groupby(link.intake_code).agg(lambda s: LIST_SEP.join(sorted(s, key=norm)))
    geo["intakes"].insert(geo["intakes"].columns.get_loc("intake_name") + 1, "municipios", geo["intakes"].intake_code.map(mun_list))
    cat = geo["catchments"]
    cat.insert(cat.columns.get_loc("intake_code") + 1, "intake_name", cat.intake_code.map(geo["intakes"].set_index("intake_code").intake_name))
    cat.insert(cat.columns.get_loc("intake_name") + 1, "municipios", cat.intake_code.map(mun_list))
    log(f"  municipios lists: {geo['intakes'].municipios.notna().sum()} of {len(geo['intakes'])} intakes, "
        f"{cat.municipios.notna().sum()} of {len(cat)} catchments")
    link = link.merge(geo["intakes"][["intake_code", "intake_type"]], on="intake_code")
    cat = geo["catchments"]
    geom = dict(zip(cat.intake_code, shapely.make_valid(cat.geometry.values)))
    area = dict(zip(cat.intake_code, cat.geometry.to_crs(area_crs).area.values / 1e6))
    surf = link[link.intake_type == "Superficial"]
    if not surf.intake_code.isin(geom.keys()).all():
        sys.exit("provisioning: linked surface intakes without catchment")
    orphan = set(geom) - set(surf.intake_code)
    log(f"  provisioning: {len(link)} municipality-intake links {link.link_source.value_counts().to_dict()}; "
        f"{len(orphan)} catchments reach no municipality")

    pair = {}  # (a, b) -> overlap as share of the smaller catchment, shared across municipalities

    def relation(a, b):
        k = (a, b) if a < b else (b, a)
        if k not in pair:
            ga, gb = geom[k[0]], geom[k[1]]
            share = 0.0 if not ga.intersects(gb) else shapely.area(shapely.intersection(ga, gb)) / min(ga.area, gb.area)
            pair[k] = share
        return pair[k]

    def topology(codes):
        if len(codes) == 1:
            return "S"
        parent = {c: c for c in codes}

        def find(x):
            while parent[x] != x:
                x = parent[x]
            return x
        for i, a in enumerate(codes):
            for b in codes[i + 1:]:
                if relation(a, b) >= nested_at:
                    parent[find(a)] = find(b)
        n = len({find(c) for c in codes})
        return "M-N" if n == 1 else ("M-D" if n == len(codes) else "M-X")

    counts = link.groupby(["municipio_code", "intake_type"]).size().unstack(fill_value=0)
    sys_only = link[link.link_source == "system"].groupby("municipio_code").size()
    rows, raw = [], []
    muns = geo["municipios"].municipio_code
    with_system = set(t["systems_supply"].municipio_code)
    for mu in muns:
        ns = int(counts.at[mu, "Superficial"]) if mu in counts.index and "Superficial" in counts else 0
        ng = int(counts.at[mu, "Subterrânea"]) if mu in counts.index and "Subterrânea" in counts else 0
        mix = ("surface_groundwater" if ng else "surface") if ns else ("groundwater" if ng else ("no_intake" if mu in with_system else "no_system"))
        g = topo = None
        if ns:
            codes = sorted(surf.intake_code[surf.municipio_code == mu])
            g = multi(polygon_parts(shapely.union_all([geom[c] for c in codes])))
            topo = topology(codes)
        rows.append((mu, mix, ns, ng, int(sys_only.get(mu, 0)), None, None, topo))
        raw.append(g)
    pa = pd.DataFrame(rows, columns=["municipio_code", "source_mix", "n_intakes_surface", "n_intakes_groundwater", "n_intakes_system_only",
                                     "n_parts", "area_km2", "topology"])
    pa.insert(1, "municipio_name", pa.municipio_code.map(geo["municipios"].set_index("municipio_code").municipio_name))
    # the raw dissolve never exceeds the sum of its catchments and never falls below the largest one
    summed = surf.assign(a=surf.intake_code.map(area)).groupby("municipio_code").a.agg(["sum", "max"])
    chk = pd.Series(gpd.GeoSeries(raw, crs=cat.crs).to_crs(area_crs).area.values / 1e6, index=pa.municipio_code).dropna().to_frame("a").join(summed)
    if ((chk.a > chk["sum"] * (1 + 1e-6)) | (chk.a < chk["max"] * (1 - 1e-6))).any():
        sys.exit("provisioning: dissolved area outside [largest catchment, sum of catchments]")
    # fill the holes: catchments have none, so a hole is a gap between neighbouring catchments
    geoms, holes = [], []
    for mu, g in zip(pa.municipio_code, raw):
        if g is not None and any(len(p.interiors) for p in g.geoms):
            holes += [(mu, shapely.Polygon(r)) for p in g.geoms for r in p.interiors]
            g = multi(polygon_parts(shapely.union_all([shapely.Polygon(p.exterior) for p in g.geoms])))
        geoms.append(g)
    gs = gpd.GeoSeries(geoms, crs=cat.crs)
    check_polygons("provisioning_areas", pa.municipio_code, gs, holes_allowed=False)
    pa["area_km2"] = gs.to_crs(area_crs).area / 1e6
    pa["n_parts"] = pd.array([None if g is None else shapely.get_num_geometries(g) for g in geoms], dtype="Int64")
    hp = gpd.GeoSeries([h for _, h in holes], crs=cat.crs).to_crs(area_crs)
    report["provisioning_filled_holes.csv"] = pd.DataFrame({"municipio_code": [mu for mu, _ in holes], "hole_area_km2": (hp.area / 1e6).round(6).values,
                                                            "hole_mean_width_m": (2 * hp.area / hp.length).round(1).values})
    log(f"  provisioning holes filled: {len(holes)} in {len({mu for mu, _ in holes})} areas, {hp.area.sum() / 1e6:.2f} km2 in total, "
        f"largest {hp.area.max() / 1e6 if len(hp) else 0:.3f} km2")
    # upstream: surface intake points inside the (filled) provisioning area that are not linked to the municipality; the covered
    # population of their systems in other municipalities (surface supply rows, each row once per area)
    itk = geo["intakes"]
    pts = itk.loc[itk.intake_type == "Superficial", ["intake_code", "geometry"]]
    has = gs.notna().values
    polys = gpd.GeoDataFrame({"area_of": pa.municipio_code[has].values}, geometry=gs[has].values, crs=gs.crs)
    up = gpd.sjoin(pts.to_crs(gs.crs), polys, predicate="intersects")[["intake_code", "area_of"]]
    own = link[["intake_code", "municipio_code"]].rename(columns={"municipio_code": "area_of"}).assign(own=True)
    up = up.merge(own, on=["intake_code", "area_of"], how="left")
    up = up[up.own.isna()].drop(columns="own").drop_duplicates()
    ind = t["municipios_indicators"].query("year == 2020")[["municipio_code", "population_urban", "supply_coverage"]]
    cov = t["systems_supply"].query("intake_type == 'Superficial'").merge(ind, on="municipio_code", how="left")
    cov["covered"] = cov.population_urban * cov.covered_percent / 100 * cov.supply_coverage / 100
    served = up.merge(t["intakes_systems"], on="intake_code").merge(cov[["supply_id", "system_id", "municipio_code", "covered"]], on="system_id")
    served = served[served.municipio_code != served.area_of].drop_duplicates(["area_of", "supply_id"])
    pa["n_intakes_surface_upstream"] = pd.array(np.where(has, up.groupby("area_of").size().reindex(pa.municipio_code).fillna(0).values, np.nan), dtype="Int64")
    pa["covered_population_urban_upstream_2020"] = np.where(has, served.groupby("area_of").covered.sum().reindex(pa.municipio_code).fillna(0).values, np.nan)
    n_up = pa.n_intakes_surface_upstream.dropna()
    log(f"  upstream: {len(up)} (area, surface intake) pairs, {int((n_up > 0).sum())} of {len(n_up)} provisioning areas with upstream intakes "
        f"(max {n_up.max()}); {served.municipio_code.nunique()} municipalities served upstream; "
        f"{int(served.drop_duplicates('supply_id').covered.isna().sum())} of their supply rows without coverage add nothing")
    geo["provisioning_areas"] = gpd.GeoDataFrame(pa, geometry=gs, crs=cat.crs)
    partial = [(a, b, round(v, 4), "nested" if v >= nested_at else "disjoint") for (a, b), v in pair.items() if tol < v < 1 - tol]
    report["provisioning_partial_overlaps.csv"] = pd.DataFrame(partial, columns=["intake_code_a", "intake_code_b", "overlap_share", "classified_as"])
    log(f"  provisioning_areas: {pa.area_km2.notna().sum()} with geometry; source_mix {pa.source_mix.value_counts().to_dict()}; "
        f"topology {pa.topology.value_counts().to_dict()}; multipart {int((pa.n_parts > 1).sum())}; "
        f"catchment pairs {len(pair)} ({len(partial)} not clean, overlap between {tol} and {1 - tol} of the smaller one: "
        f"{sum(r[3] == 'nested' for r in partial)} classified nested, {sum(r[3] == 'disjoint' for r in partial)} disjoint)")
    build_within(geo, pa, gs, area_crs, float(opts.get("within_min_part_km2", 0.01)), report)


# --------------------------------------------------------------------------- DDL / load
def ddl(tbl):
    parts = []
    single_int_pk = len(tbl["primary_key"]) == 1 and next(c for c in tbl["columns"] if c["name"] == tbl["primary_key"][0])["type"] == "INTEGER"
    for c in tbl["columns"]:
        s = f'"{c["name"]}" {c["type"]}'
        if single_int_pk and c["name"] == tbl["primary_key"][0]:
            s += " PRIMARY KEY"
        elif c.get("not_null"):
            s += " NOT NULL"
        parts.append(s)
    if tbl["primary_key"] and not single_int_pk:
        parts.append("PRIMARY KEY (" + ", ".join(f'"{c}"' for c in tbl["primary_key"]) + ")")
    for u in tbl.get("uniques", []):
        parts.append("UNIQUE (" + ", ".join(f'"{c}"' for c in u) + ")")
    for f in tbl["foreign_keys"]:
        parts.append("FOREIGN KEY (" + ", ".join(f'"{c}"' for c in f["columns"]) + f') REFERENCES "{f["ref_table"]}" (' + ", ".join(f'"{c}"' for c in f["ref_columns"]) + ")")
    for ck in tbl.get("checks", []):
        parts.append(f"CHECK ({ck})")
    return f'CREATE TABLE "{tbl["name"]}" (\n  ' + ",\n  ".join(parts) + "\n)"


def typed(g, tb):
    """The schema columns of a spatial layer, in schema order, cast to their declared type (GDAL takes the column type
    from the dtype; a value that does not convert stops the build)."""
    out = pd.DataFrame(index=g.index)
    for c in tb["columns"]:
        v = g[c["name"]]
        if c["type"] in ("INTEGER", "REAL"):
            n = pd.to_numeric(v, errors="coerce")
            if (n.isna() & v.notna()).any() or (c["type"] == "INTEGER" and (n.dropna() % 1 != 0).any()):
                sys.exit(f"{tb['name']}.{c['name']}: values that are not {c['type']}")
            v = n.astype("Int64" if c["type"] == "INTEGER" else "float64")
        else:
            v = v.astype(object).where(v.notna(), None)
        out[c["name"]] = v
    return out


def verify_spatial(con, tb):
    """What a CREATE TABLE would enforce on a plain table, checked on a spatial layer written by GDAL."""
    name = tb["name"]
    have = {r[1]: r[2] for r in con.execute(f'PRAGMA table_info("{name}")')}
    wrong = {c["name"]: have.get(c["name"]) for c in tb["columns"] if have.get(c["name"]) != c["type"]}
    gtype = con.execute("SELECT geometry_type_name FROM gpkg_geometry_columns WHERE table_name = ?", (name,)).fetchone()
    if wrong or gtype is None or gtype[0] != tb["geometry"]["type"].upper():
        sys.exit(f"{name}: column types {wrong} or geometry type {gtype} differ from the schema")
    tests = [(f'"{c["name"]}" IS NULL', f'{c["name"]} NOT NULL') for c in tb["columns"] if c.get("not_null")]
    if not tb["geometry"].get("nullable"):
        tests.append(("geom IS NULL", "geom NOT NULL"))
    tests += [(f"NOT ({ck})", f"CHECK ({ck})") for ck in tb.get("checks", [])]
    for f_ in tb["foreign_keys"]:
        col, ref = f_["columns"][0], f_["ref_columns"][0]
        tests.append((f'"{col}" IS NOT NULL AND "{col}" NOT IN (SELECT "{ref}" FROM "{f_["ref_table"]}")',
                      f'{col} references {f_["ref_table"]}'))
    for where, what in tests:
        n = con.execute(f'SELECT COUNT(*) FROM "{name}" WHERE {where}').fetchone()[0]
        if n:
            sys.exit(f"{name}: {n} rows violate {what}")


def py(v):
    if v is None or v is pd.NA:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    return v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    miss = [k for k in REQUIRED if k not in cfg]
    if miss:
        sys.exit(f"config: missing keys {miss}")
    out = Path(cfg["output_gpkg"])
    if out.exists() and not a.overwrite:
        sys.exit(f"{out} exists (use --overwrite)")
    schema_path = Path(cfg["schema"])
    if not schema_path.is_absolute():
        schema_path = Path(a.config).resolve().parent / schema_path
    schema = {t["name"]: t for t in json.loads(schema_path.read_text(encoding="utf-8"))}
    src = Source(cfg["input_folder"], cfg["catalog_layers"])
    r = src.cat.loc["CATCHMENTS"]
    problem = revise_catchments.check_catchments(src.folder / r["file_name"], r["gpkg_layer"])
    if problem:
        sys.exit(f"catchments: {problem}")
    log("catchments: geometry hashes and n_parts match T1")
    report = {}
    log("reading T1 and transforming")
    tables, geo = build_tables(src, report, cfg)
    build_provisioning(tables, geo, cfg.get("provisioning", {}), report)

    part = out.with_name(out.stem + ".part.gpkg")
    out.parent.mkdir(parents=True, exist_ok=True)
    if part.exists():
        part.unlink()
    # spatial layers first (creates the GeoPackage structure), schema columns cast to their declared types; keys must be unique
    spatial = [n for n in schema if schema[n]["kind"] == "spatial"]
    if set(spatial) != set(geo):
        sys.exit(f"spatial layers built {sorted(geo)} differ from schema {sorted(spatial)}")
    for name in spatial:
        tb = schema[name]
        g = geo[name]
        pk = tb["primary_key"][0]
        if g[pk].duplicated().any() or g[pk].isna().any():
            sys.exit(f"{name}: key {pk} duplicated or null")
        gtype = tb["geometry"]["type"]
        other = set(g.geometry.dropna().geom_type) - {gtype}
        if other:
            sys.exit(f"{name}: geometry types {other}, schema says {gtype}")
        g = gpd.GeoDataFrame(typed(g, tb), geometry=g.geometry.values, crs=g.crs)
        pyogrio.write_dataframe(g, part, layer=name, driver="GPKG", geometry_type=gtype, append=part.exists())
        log(f"  spatial {name}: {len(g)} rows")
    con = sqlite3.connect(part)
    con.execute("PRAGMA foreign_keys = ON")
    for name, tb in schema.items():  # unique key index first: plain tables reference these layers
        if tb["kind"] == "spatial":
            key = tb["primary_key"][0]
            con.execute(f'CREATE UNIQUE INDEX "ux_{name}_{key}" ON "{name}" ("{key}")')
            con.execute("UPDATE gpkg_contents SET description = ? WHERE table_name = ?", (tb["description_en"], name))
    order = [t for t in schema if schema[t]["kind"] == "table"]
    for name in order:
        tb = schema[name]
        con.execute(ddl(tb))
        df = tables[name][[c["name"] for c in tb["columns"]]]
        rows = [tuple(py(v) for v in r) for r in df.itertuples(index=False, name=None)]
        qs = ",".join("?" * len(tb["columns"]))
        con.executemany(f'INSERT INTO "{name}" VALUES ({qs})', rows)
        con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, last_change) "
                    "VALUES (?, 'attributes', ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (name, name, tb["description_en"]))
        log(f"  table {name}: {len(rows)} rows")
    for name, tb in schema.items():
        if tb["kind"] == "view":
            con.execute(f'CREATE VIEW "{name}" AS {tb["sql"]}')
            if name in tables:  # a view whose rows were also computed in Python: both must agree
                got = set(con.execute(f'SELECT * FROM "{name}"').fetchall())
                if got != set(tables[name].itertuples(index=False, name=None)):
                    sys.exit(f"view {name} differs from the rows computed in Python")
            # GDAL/QGIS only open what gpkg_contents lists
            con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, last_change) "
                        "VALUES (?, 'attributes', ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (name, name, tb["description_en"]))
    # catalogs
    con.execute('CREATE TABLE "tables" ("table_name" TEXT PRIMARY KEY, "table_kind" TEXT NOT NULL, "rows" INTEGER, "description_pt" TEXT, "description_en" TEXT)')
    con.execute('CREATE TABLE "fields" ("table_name" TEXT NOT NULL, "column_name" TEXT NOT NULL, "column_type" TEXT, "is_key" INTEGER, '
                '"not_null" INTEGER, "unit" TEXT, "description_pt" TEXT, "description_en" TEXT, PRIMARY KEY ("table_name", "column_name"))')
    for name, tb in schema.items():
        n = len(tables[name]) if name in tables else (len(geo[name]) if name in geo else con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
        con.execute('INSERT INTO "tables" VALUES (?,?,?,?,?)', (name, tb["kind"], n, tb["description_pt"], tb["description_en"]))
        for c in tb["columns"]:
            con.execute('INSERT INTO "fields" VALUES (?,?,?,?,?,?,?,?)', (name, c["name"], c["type"], int(c["name"] in tb["primary_key"]),
                                                                          int(bool(c.get("not_null"))), c.get("unit", ""), c["description_pt"], c["description_en"]))
        if tb["kind"] == "spatial":
            con.execute('INSERT INTO "fields" VALUES (?,?,?,?,?,?,?,?)', (name, "geom", tb["geometry"]["type"].upper(), 0,
                                                                          int(not tb["geometry"].get("nullable")), "", "Geometria", "Geometry"))
    for name in ("tables", "fields"):
        con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, last_change) "
                    "VALUES (?, 'attributes', ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (name, name, "Catalog"))
    con.commit()
    for name in spatial:
        verify_spatial(con, schema[name])
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    if bad:
        sys.exit(f"foreign key violations: {bad[:5]}")
    # spatial layers must also be present in `fields`: verify declared columns exist in the database
    for name, tb in schema.items():
        have = [r[1] for r in con.execute(f'PRAGMA table_info("{name}")')]
        want = [c["name"] for c in tb["columns"]] + (["geom"] if tb["kind"] == "spatial" else [])
        if tb["kind"] != "view" and sorted(h for h in have if h != "fid") != sorted(want):
            sys.exit(f"{name}: columns in database {have} differ from schema {want}")
    con.close()
    if out.exists():
        out.unlink()
    part.rename(out)
    if cfg.get("report_folder"):
        rf = Path(cfg["report_folder"])
        rf.mkdir(parents=True, exist_ok=True)
        for fn, df in report.items():
            df.to_csv(rf / fn, sep=";", index=False)
            log(f"  report {rf / fn}: {len(df)} rows")
    log(f"written {out}")


if __name__ == "__main__":
    main()
