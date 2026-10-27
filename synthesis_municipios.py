#!/usr/bin/env python3
"""Municipality synthesis table from the T2 GeoPackage: one row per municipality (5,572), every per-municipality value.

Usage (project venv):  .venv/bin/python synthesis_municipios.py --config synthesis_municipios.local.json [--overwrite]

Config keys: gpkg (T2, opened read-only), output (CSV). Optional: sep (default ';').
Writes <output> and <output stem>_GLOSSARY.csv (column_name;description_pt;description_en;unit, the T1 convention;
descriptions of copied columns come from the T2 `fields` catalog).
Columns, in blocks:
  municipality    municipios attributes (area_km2 -> municipio_area_km2)
  indicators      municipios_indicators, wide: <column>_<year>; years and columns with no value at all are dropped
                  (ISH exists for 2020 only)
  supply          systems_supply: n_systems, n_systems_integrado, surface_percent, groundwater_percent (sums of
                  covered_percent by intake type); covered_population_urban_2020 = urban population x coverage;
                  covered_surface_population_2020 = urban population x surface share x coverage (NULL where coverage is
                  not reported)
  provisioning    provisioning_areas attributes (area_km2 -> provisioning_area_km2, n_parts -> provisioning_n_parts);
                  NULL area where there is no surface intake (source_mix says why); provisioning_areas_within attributes
                  (-> provisioning_within_area_km2, provisioning_within_share, provisioning_within_municipio_percent,
                  provisioning_within_n_parts)
  investments     municipios_investments, wide: investment_<group>_<component>_<period>_brl, + investment_total_brl
  proposals       n_proposals, n_proposals_<kind> (counts only: a proposal's investment is stored once, not per
                  municipality, so it cannot be summed per municipality)
Text values (and the header) are always in double quotes (" inside doubled), numbers are not quoted, an empty
unquoted cell is NULL in any column. Derived only from T2: no new data.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

REQUIRED = ["gpkg", "output"]

DERIVED = {  # column -> (description_pt, description_en, unit)
    "n_systems": ("Sistemas de abastecimento que atendem o município", "Supply systems serving the municipality", ""),
    "n_systems_integrado": ("Sistemas integrados (atendem mais de um município)", "Integrated systems (serving more than one municipality)", ""),
    "surface_percent": ("Parcela da população urbana atendida por mananciais superficiais", "Share of the urban population supplied by surface water", "%"),
    "groundwater_percent": ("Parcela da população urbana atendida por mananciais subterrâneos", "Share of the urban population supplied by groundwater", "%"),
    "covered_population_urban_2020": ("População urbana atendida em 2020 (população urbana x cobertura; vazio sem cobertura informada)",
                                      "Covered urban population 2020 (urban population x coverage; empty where coverage is not reported)", "inhabitants"),
    "covered_surface_population_2020": ("População urbana atendida por manancial superficial em 2020 (população x parcela superficial x cobertura)",
                                        "Covered urban population supplied by surface water 2020 (population x surface share x coverage)", "inhabitants"),
    "investment_total_brl": ("Soma de todos os investimentos do município (distribuição e reposição, todos os períodos)",
                             "Sum of all municipality investments (distribution and replacement, all periods)", "BRL"),
    "n_proposals": ("Propostas de produção de água que atendem o município", "Water production proposals serving the municipality", ""),
}
ORDER = {"distribution": 0, "replacement": 1, "network": 0, "connections": 1, "storage": 2,  # investment column order
         "until2025": 0, "2026to2030": 1, "2031to2035": 2, "until2035": 3}
RENAME = {("municipios", "area_km2"): "municipio_area_km2",
          ("provisioning_areas", "area_km2"): "provisioning_area_km2",
          ("provisioning_areas", "n_parts"): "provisioning_n_parts",
          ("provisioning_areas_within", "area_km2"): "provisioning_within_area_km2",
          ("provisioning_areas_within", "share"): "provisioning_within_share",
          ("provisioning_areas_within", "municipio_percent"): "provisioning_within_municipio_percent",
          ("provisioning_areas_within", "n_parts"): "provisioning_within_n_parts"}


def log(m):
    print(m, flush=True)


def quote(v):
    return '"' + str(v).replace('"', '""') + '"'


def write_csv(df, path, sep):
    """Text always quoted, numbers bare, NULL empty (pandas quoting would also quote empty numeric cells)."""
    text = [pd.api.types.is_object_dtype(t) or pd.api.types.is_string_dtype(t) for t in df.dtypes]
    lines = [sep.join(quote(c) for c in df.columns)]
    for row in df.itertuples(index=False, name=None):
        lines.append(sep.join("" if pd.isna(v) else (quote(v) if is_text else str(v)) for v, is_text in zip(row, text)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read(con, sql):
    return pd.read_sql_query(sql, con)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    miss = [k for k in REQUIRED if k not in cfg]
    if miss:
        sys.exit(f"config: missing keys {miss}")
    out = Path(cfg["output"])
    gloss = out.with_name(f"{out.stem}_GLOSSARY.csv")
    if (out.exists() or gloss.exists()) and not a.overwrite:
        sys.exit(f"{out} or its glossary exists (use --overwrite)")
    con = sqlite3.connect(f"file:{cfg['gpkg']}?mode=ro", uri=True)
    fields = read(con, "SELECT table_name, column_name, unit, description_pt, description_en FROM fields")
    fdesc = {(r.table_name, r.column_name): (r.description_pt, r.description_en, r.unit) for r in fields.itertuples()}
    glossary = {}

    def copy(table, df):
        for c in df.columns:
            if c == "municipio_code" and table != "municipios":
                continue
            glossary[RENAME.get((table, c), c)] = fdesc[(table, c)]
        return df.rename(columns={c: RENAME.get((table, c), c) for c in df.columns})

    def attributes(table):
        """The columns of a spatial layer listed in `fields`, without the geometry (and the name, except in municipios)."""
        skip = {"geom"} | ({"municipio_name"} if table != "municipios" else set())
        cols = fields.column_name[(fields.table_name == table) & ~fields.column_name.isin(skip)]
        return copy(table, read(con, f'SELECT {", ".join(cols)} FROM "{table}"'))

    # municipality
    syn = attributes("municipios")
    n = len(syn)

    # indicators, wide by year
    ind = read(con, "SELECT * FROM municipios_indicators")
    wide = []
    for year, g in ind.groupby("year"):
        g = g.drop(columns="year").set_index("municipio_code").dropna(axis=1, how="all")
        for c in g.columns:
            pt, en, unit = fdesc[("municipios_indicators", c)]
            glossary[f"{c}_{year}"] = (f"{pt} ({year})", f"{en} ({year})", unit)
        wide.append(g.add_suffix(f"_{year}"))
    syn = syn.join(pd.concat(wide, axis=1), on="municipio_code")

    # supply
    sup = read(con, """
        SELECT ss.municipio_code,
               COUNT(DISTINCT ss.system_id) AS n_systems,
               COUNT(DISTINCT CASE WHEN s.system_type = 'Integrado' THEN ss.system_id END) AS n_systems_integrado,
               SUM(CASE WHEN ss.intake_type = 'Superficial' THEN ss.covered_percent ELSE 0 END) AS surface_percent,
               SUM(CASE WHEN ss.intake_type = 'Subterrânea' THEN ss.covered_percent ELSE 0 END) AS groundwater_percent
        FROM systems_supply ss JOIN systems s ON s.system_id = ss.system_id
        GROUP BY ss.municipio_code""")
    syn = syn.merge(sup, on="municipio_code", how="left")
    if not {"population_urban_2020", "supply_coverage_2020"} <= set(syn.columns):
        sys.exit("indicators: population_urban_2020 or supply_coverage_2020 missing")
    syn["covered_population_urban_2020"] = (syn.population_urban_2020 * syn.supply_coverage_2020 / 100).round(2)
    syn["covered_surface_population_2020"] = (syn.covered_population_urban_2020 * syn.surface_percent / 100).round(2)
    for c in ("n_systems", "n_systems_integrado", "surface_percent", "groundwater_percent",
              "covered_population_urban_2020", "covered_surface_population_2020"):
        glossary[c] = DERIVED[c]

    # provisioning
    syn = syn.merge(attributes("provisioning_areas"), on="municipio_code", how="left")
    syn = syn.merge(attributes("provisioning_areas_within"), on="municipio_code", how="left")

    # investments, wide
    inv = read(con, "SELECT * FROM municipios_investments")
    inv["column"] = "investment_" + inv.investment_group + "_" + inv.component + "_" + inv.period + "_brl"
    piv = inv.pivot(index="municipio_code", columns="column", values="amount_brl")
    piv = piv[sorted(piv.columns, key=lambda c: [ORDER[x] for x in c.split("_")[1:4]])]
    for c in piv.columns:
        _, group, component, period, _ = c.split("_")
        glossary[c] = (f"Investimento: grupo {group}, componente {component}, período {period}",
                       f"Investment: group {group}, component {component}, period {period}", "BRL")
    piv["investment_total_brl"] = piv.sum(axis=1)
    glossary["investment_total_brl"] = DERIVED["investment_total_brl"]
    syn = syn.join(piv, on="municipio_code")

    # proposals, counts
    pro = read(con, "SELECT pm.municipio_code, p.investment_kind FROM proposals_municipios pm "
                    "JOIN proposals p ON p.proposal_id = pm.proposal_id")
    cnt = pro.groupby(["municipio_code", "investment_kind"]).size().unstack(fill_value=0).add_prefix("n_proposals_")
    cnt.insert(0, "n_proposals", cnt.sum(axis=1))
    glossary["n_proposals"] = DERIVED["n_proposals"]
    for c in cnt.columns[1:]:
        kind = c.removeprefix("n_proposals_")
        glossary[c] = (f"Propostas do tipo {kind} que atendem o município", f"Proposals of kind {kind} serving the municipality", "")
    syn = syn.join(cnt, on="municipio_code")
    syn[list(cnt.columns)] = syn[list(cnt.columns)].fillna(0).astype("int64")
    con.close()

    # checks
    if len(syn) != n or syn.municipio_code.duplicated().any():
        sys.exit(f"synthesis: {len(syn)} rows for {n} municipalities, or repeated codes")
    missing = [c for c in syn.columns if c not in glossary]
    if missing:
        sys.exit(f"glossary: no description for {missing}")
    for c in [c for c in syn.columns if c.startswith("n_") or c.endswith("_n_parts")]:
        syn[c] = syn[c].astype("Int64")

    out.parent.mkdir(parents=True, exist_ok=True)
    sep = cfg.get("sep", ";")
    write_csv(syn, out, sep)
    g = pd.DataFrame([(c, *glossary[c]) for c in syn.columns], columns=["column_name", "description_pt", "description_en", "unit"])
    write_csv(g, gloss, sep)
    log(f"written {out}: {len(syn)} rows, {len(syn.columns)} columns; glossary {gloss}")
    log(f"  with provisioning area {syn.provisioning_area_km2.notna().sum()}, with systems {syn.n_systems.notna().sum()}, "
        f"with proposals {(syn.n_proposals > 0).sum()}")


if __name__ == "__main__":
    main()
