# Provenance of T1 (legacy → T1)

`standardize_t1.py` turned the legacy ANA Atlas Águas 2021 files into the T1 files that `build_database.py` reads.
It was a one-shot job and is **archived**: kept to document how T1 was made, not part of the pipeline.

## Do not re-run it on the real T1
- It merges `legacy/catchments.gpkg` into the T1 catchments file. A re-run would overwrite every revised catchment.
- It generates `intake_code` from the intake location plus an ordinal (option `code_from_location`). Any change in the
  ordering or rounding renames intakes, and every link (`intakes_systems`, `intakes_municipios`, catchments) uses that key.
- Guard: the script refuses to write when any of its output files already exists in `output_folder`. There is no
  overwrite option. `--dry-run` still works.
- A new ANA Atlas (e.g. Y2025) is a new dataset: copy the script and its config as a template.

## Run
- Main T1 run: 2026-10-05 (file dates in `T1/ASSETS`). Catchments file and layer catalog rewritten 2026-10-21 with all
  4,063 catchments (backups `*_backup_20261021_18125*` next to them).
- Config: `standardize_t1.example.json` (the real paths were `input_folder = T1/ASSETS/legacy`, `output_folder = T1/ASSETS`).
- Original ANA downloads: `Y2021/SRC/` (xlsx and zip). The `T1/ASSETS/legacy` folder no longer exists.

| T1 layer | Legacy source | Rows in T1 |
|---|---|---|
| ISH | `indicadores_seguranca_hidrica.csv` | 5,570 |
| INVESTMENT-DISTRIBUTION | `investimentos_distribuicao_dados.csv` | 5,570 |
| INVESTMENT-PRODUCTION | `investimentos_producao_dados.csv` | 3,743 |
| SOURCE-SYSTEMS | `mananciais_sistemas_dados.csv` | 5,570 |
| SYSTEMS-MUNICIPALITIES | `municipios_systems.csv` | 9,667 |
| AQUEDUCTS | `aquedutos.gpkg` (layer `main`) | 443 |
| INTAKES | `pontos_captacao.gpkg` (layer `main`) | 18,252 |
| CATCHMENTS | `catchments.gpkg` (layers `catchments_*`, merged) | 4,063 |
| MUNICIPALITIES | `dtb_2022_municipios.gpkg` | 5,572 |
| SEATS | `pontos_municipios_sedes.gpkg` (layer `main`) | 5,570 |

All automatic fixes (renames, NA handling, whitespace, value maps, list separators, name/UF splits, codes) live in
the config and are counted in the script log.

## Manual steps (not in the script)
1. **`investimentos_producao` had swapped columns** in the legacy file. They were fixed by hand before the run;
   the header is now `code;alias;name`. Recorded from the 2026-10-05 session log; which columns were swapped, and
   in which file (data CSV or its glossary), is not written down. *To confirm.*
2. How the legacy CSVs were exported from the `SRC/` xlsx files is not recorded. *To confirm.*
