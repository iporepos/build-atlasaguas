# Session log

History before this repo: `Bench/MEMORY.md`, entries 2026-10-05, 2026-10-21 and 2026-10-22. Plan: `prompts/plan.md`.

## 2026-10-22 — repo hygiene (plan section 7, step 1)
- Unstaged `plot_municipio_provisioning.json` and `plot_system_dispersion.json` (real `/media` paths; renamed to
  `*.local.json` by the user, git-ignored). Re-staged `build_database.example.json` and `archive/standardize_t1.example.json`
  (the staged copies still had `/media` paths). `build_database.local.json` and `.idea/` were not staged.
- Added `plot_system_dispersion.example.json`, `plot_municipio_provisioning.example.json` (placeholder paths) and
  `requirements.txt` (adds pyproj for the geodesic areas of `revise_catchments.py`).
- Plot configs: `sql` now `queries/<file>.sql` (relative to the config at the repo root); also fixed in both `*.local.json`.
- Usage lines in the script docstrings pointed to `atlasaguas/`; now point to the repo layout and `*.local.json`.
- `CLAUDE.md` filled (scope policy, pipeline, never re-run standardize_t1, data paths, `--config`, no writes to /media).
  Note: `CLAUDE.md`, `prompts/`, `.claude/` and `scripts/` are git-ignored by the user's `.gitignore`.
- Not decided: moving scripts into `scripts/` (it is git-ignored now, so they stay at the root).
- Nothing committed. Next: step 2 (guard in `archive/standardize_t1.py` + provenance note).
- Moved the plot machinery to `plots/`: `plot_system_dispersion.py` and its `.example.json`/`.local.json` configs
  (both plots). Queries stay in `queries/` (shared with QGIS); configs use `sql: ../queries/<file>.sql`.
  Run: `python plots/plot_system_dispersion.py --config plots/plot_municipio_provisioning.local.json`.

## 2026-10-22 — standardize_t1 guard + provenance (plan section 7, step 2)
- `archive/standardize_t1.py`: `--overwrite` removed; refuses to write (before reading anything) when any output file of
  the selected layers (data + glossary, + LAYERS catalog on a full run) exists in `output_folder`. `--dry-run` unaffected.
  Tested against the real T1 (existence check only): full run refused (21 files), `--only CATCHMENTS` refused (2);
  empty scratch folder passes the guard.
- `archive/PROVENANCE.md`: why not to re-run, run dates, layer -> legacy source -> rows, manual steps.
- Found: `T1/ASSETS/legacy` no longer exists; originals are in `Y2021/SRC/` (xlsx/zip).
- To confirm with user: exact investimentos_producao column swap (which columns, which file); how legacy CSVs were
  exported from SRC xlsx.
- Agent git writes are now denied in `.claude/settings.json`; the user stages and commits.

## 2026-10-22 — revise_catchments.py (plan section 7, step 3)
- Area method (get-catchments-fast, read only): vector catchments take the HydroBASINS SUB_AREA sum, raster-refined a
  geodesic area (Geod WGS84, compute_area_crs null). BUT the T1 stored areas equal `Geod(WGS84)` of the current geometry
  for ALL 4,063 rows, every source (max diff 0.0 km2): acceptance test passed, geodesic method adopted.
- T1 catchments: all valid, all single-part (n_parts = 1 everywhere), 13 manual_replaced already.
- Intake-to-own-polygon distance (ESRI:102033): 3,811 inside/on, p99 568 m, 49 > 500 m, 11 > 5 km (max 70.5 km,
  IN09000591290039001 vector_upper): revision candidates. 714 intakes share 308 identical polygons (same outlet).
- `revise_catchments.py` + `.example.json` (+ `.local.json` with real paths, empty revisions). Defaults taken (open
  questions in plan section 8): hashes = unregistered table `catchments_hashes` in the T1 catchments gpkg (GDAL/QGIS
  still list it as a plain table; build_database reads layers by name so it is not copied).
  Intake distance is INFORMATION ONLY (user: Atlas points are ill-positioned, some via aqueducts/canals; catchments were
  derived from corrected points): reported per item, warning beyond `intake_warning_m` (default 500), never an error. Hash: MultiPolygon parts, coords rounded 9 decimals, normalize, sha256 WKB.
- Writes through sqlite3 (no osgeo in the Bench venv): GPKG blobs encoded in the script, ST_IsEmpty/ST_Min*/ST_Max*
  registered so the rtree triggers run. Refuses if -wal/-journal exists (file open in QGIS).
- Tested on a scratch copy of T1: --init; GDAL re-save of unchanged features = no change; GDAL edit not listed = STOP;
  edit/replace apply + idempotent rerun; replace from EPSG:3857 with 2 features; bowtie -> make_valid (2 parts);
  far polygon / no CRS / missing file = errors, file byte-identical; replace + T1 edit conflict = error; source suffix
  rules; after writes GDAL reads OK, GDAL-read hashes == stored, rtree matches, integrity_check ok, exact extent.
  NOT tested: a real QGIS open/save (user).

## 2026-10-22 — build_database.py: n_parts + hash check (plan section 7, step 4)
- Correction: before this step a T1 with n_parts would NOT have broken the build (tables are loaded with the schema's
  columns only, so n_parts would have been dropped silently). The "columns differ" check is DB vs schema.
- Schema `catchments_attributes`: + n_parts INTEGER NOT NULL, CHECK (n_parts >= 1); catchment_source description lists
  the automatic sources + manual_replaced + <method>_manual_edits; catchment_area_km2 says geodesic WGS84.
- build_database.py calls `revise_catchments.check_catchments()` before reading T1: stops if catchments_hashes or
  n_parts missing (no --init), if a geometry no longer matches its hash (unlisted edit), or if n_parts is stale.
  One hash definition, imported (revise_catchments.HASH_DECIMALS = 9 is now a constant; `hash_decimals` config key removed).
- Tested full builds in scratch (T1 symlinked read-only, catchments copied): no init -> stop; after init -> OK
  (n_parts all 1, hashes table not in T2); unlisted QGIS-like edit -> stop; after revise -> OK, new source in T2, and
  the Imunana test edit (buffer 1.3 -> 127.6 km2) reaches provisioning areas of 3301900/3303302/3304904.
- Note: build_database.py imports revise_catchments, so run it as `python build_database.py` from the repo (python -I
  would drop the script folder from sys.path).
- Next for the user: QGIS open/save test on a copy, then real `--init`, then rebuild T2. Then step 5 (Imunana fix).

## 2026-10-22 — publish.py (Zenodo zips)
- `publish.py` + `publish.example.json` / `publish.local.json` (output `Y2021/SRC/ZENODO`): one zip per archive
  (T1_/T2_ANA_ATLASAGUAS_DB_BRAZIL_2021.zip), files inside a top folder named after the zip, skip globs from config,
  stops on -wal/-journal (gpkg open), on an existing zip (--overwrite), on an empty folder; .part then rename, testzip,
  prints size + md5. --dry-run lists files. Tested on scratch folders; real dry run lists 21 T1 files + 1 T2 file.
- Skipped in T1: backups, and the stale `ANA_ATLAS-AGUAS_MUNICIPALITY-SYSTEMS_BRASIL_2021.csv` (+ glossary, 2026-10-05
  16:09, not in the LAYERS catalog; current name SYSTEMS-MUNICIPALITIES) via the local skip list. User may delete it.
  Skipped in T2: old `ANA_ATLASAGUAS_DB_BRAZIL_2021.gpkg.zip`.
- T1 zip includes the catchments_hashes table (inside the catchments gpkg).
- docs/zenodo_description.html: Files section (T2 = database, T1 = standardized sources), getting started names the T2
  zip, n_parts + revision sources mentioned, counts fixed (19 data tables, 2 catalogs, 2 views; was 16/1), provisioning
  areas described, version log 1.1.0 (number to confirm).

## 2026-10-22 — local venv
- `.venv` created in the repo from requirements.txt (python 3.12.3): geopandas 1.2.0, pandas 3.1.0, numpy 2.5.4,
  pyogrio 0.13.0 (GDAL 3.12.4), shapely 2.2.0, pyproj 3.8.0, matplotlib 3.11.2.
- Hashes stored with Bench (shapely 2.1.2) verified identical with shapely 2.2.0 (scratch copy, all 4,063); scratch
  build OK with .venv. Use `.venv/bin/python` from now on.
