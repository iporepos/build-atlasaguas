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

## 2026-10-22 — synthesis_municipios.py
- One CSV row per municipality (5,572) from T2 (read-only) + <stem>_GLOSSARY.csv (T1 convention; copied columns take
  the T2 `fields` descriptions). 53 columns: municipios_attributes (area_km2 -> municipio_area_km2); indicators wide
  <col>_<year> (ISH only 2020; empty columns dropped); n_systems, n_systems_integrado, surface/groundwater_percent,
  covered_population_urban_2020, covered_surface_population_2020; provisioning_areas_attributes (provisioning_area_km2,
  provisioning_n_parts); 14 investment columns + total; n_proposals (+ per kind; counts only, proposal money is
  per proposal and would double count).
- Facts: surface+groundwater shares sum 99.96-100.03 (Atlas rounding, 345 munis). Totals on scratch T2: urban pop 2020
  185.16 M, covered 169.51 M, investments 107.04 bi BRL. assigned population (view) == urban population, not included.
- Output default T2/REPORT (local config). Not zipped by publish.py unless moved to T2/ASSETS: user to decide.
- Tested on the scratch T2 (no revisions); Porto Alegre and São Gonçalo checked by hand.
- CSV quoting (user): text values and header always in double quotes, numbers bare, NULL = empty unquoted cell
  (own writer `write_csv`; pandas QUOTE_NONNUMERIC/QUOTE_STRINGS would also quote empty numeric cells). Same for the
  glossary. Values identical to the previous output.

## 2026-10-22 — municipio plot: area on y
- plot_municipio_provisioning.{example,local}.json: x = covered_surface_population_2020, y = provisioning_area_km2
  (labels swapped, title "Provisioning area vs covered surface-water population"), legend upper left (lower left now
  has dots). Identity line still reads "1 km² per inhabitant" (y/x = km²/inhabitant). Script unchanged except docstring.
- Tested: rendered from the real T2 (read-only) to the scratchpad. User to re-run to update T2/REPORT.

## 2026-10-22 — municipio plot: urban population vs area
- New configs plots/plot_municipio_population.{example,local}.json (same SQL and script): x = population_urban_2020
  (all urban inhabitants, any source), y = provisioning_area_km2, output municipio_population_dispersion.jpg.
- SQL municipio_population_provisioning.sql gained population_urban_per_km2 (query column only, used as ratio_column
  for labels and hover; not a dataset column).
- Tested on the real T2 (read-only): 3,379 points, 0 dropped. User to run it to write to T2/REPORT.
- Added a second dashed line, 1 ha per inhabitant (y = 0.01 x). Script: `identity_line` now takes an optional
  `factor` (y = factor * x) and may be a list of lines; the single-object form renders the same as before (the
  provisioning plot was checked pixel-identical).

## 2026-10-22 — municipio plot: RS highlight
- New configs plots/plot_municipio_population_rs.{example,local}.json (population vs area, both reference lines):
  RS municipalities navy #1c2f6e (alpha 0.9) drawn on top of the other states in opaque light gray #aeada8 (alpha 1;
  first try was dark gray #5f5e5a at alpha 0.45, user asked lighter and not transparent);
  output municipio_population_dispersion_RS.jpg.
- Script: new optional `highlight` key {column, value, label, other_label, alpha} replacing `category`; direct labels
  name highlighted rows only, and only highlighted dots block label placement (gray dots would push leaders far away).
- SQL gained m.unidade_alias (query column only). Other two plots re-rendered pixel-identical. RS: 187 municipalities.

## 2026-10-22 — 1 m² per inhabitant line
- Added {"label": "1 m² per inhabitant", "factor": 1e-6} to identity_line in the three municipio configs
  (provisioning, population, population_rs; example + local). Lines now: 1 km² (provisioning: only km² + m²;
  population plots: km², ha, m²). System dispersion plot (area on x, no reference lines) left as is.
- Added "10 m² per inhabitant" (factor 1e-5) to the same three configs; identity_line lists sorted by factor, largest first.
- Then replaced the 10 m² line with "100 m² per inhabitant" (factor 1e-4) in the same three configs.
- RS dots 20% bigger: new highlight key `scale` (diameter factor; s = marker_size x scale², s is an area), 1.2 in the
  RS configs (s 12 -> 17.3). Population plot re-rendered pixel-identical.
- RS plot labels without "(RS)": SQL gained m.municipio_name (query column only); RS configs use label_column
  municipio_name. National plots keep municipio_label "Name (UF)".
- Without "(RS)", Osório and Itaara labels touched ("OsórioItaara"). New script key `label_gap` (points of extra
  horizontal clearance per name label, default 0), 4 in the RS configs. Applied globally it made the national
  plots' labels worse, so it stays opt-in; national plots unchanged (pixel check).
- y_label of the three municipio plots shortened to "Provisioning area (km²)" (user: no explanations).
- Reference lines now solid, color REF #aaa9a4 (was dashed MUTED #8a8984).

## 2026-10-27 — T2 refactor: attributes in spatial layers, provisioning_areas_within, hole filling
- Scope exception decided by the user (new layer provisioning_areas_within; structure change). CLAUDE.md/README scope
  text not changed: user to decide whether to reword the frozen-scope policy.
- `*_attributes` tables removed: municipios, intakes, aqueducts, catchments, provisioning_areas carry their columns
  (QGIS friction). FKs of plain tables now point to the spatial layers (unique index on the key). Schema: 15 tables
  (8 plain + 7 spatial) + 2 views. geometry.nullable flag (provisioning_areas, _within); `fields.geom.not_null` follows it.
- Spatial layers: columns cast to the schema type before pyogrio (INTEGER -> Int64, REAL, TEXT), geometry_type passed;
  after loading, `verify_spatial` checks declared types, gpkg geometry type, NOT NULL, CHECKs (may use geom), FKs, geom
  NOT NULL. Negative tests (share 1.5, bad FK, NULL geom, bad intake_type) all stop the build.
- Holes: catchments have 0 holes; the dissolve had 3,666 holes in 228 areas (median width 19 m, max 5 km2, 110.75 km2
  total) = gaps between catchments. All filled (hydrology: an enclosed area drains through its neighbours); report
  provisioning_filled_holes.csv. Area-bounds check now on the raw dissolve; check_polygons: valid, non-empty
  MultiPolygon, no holes (holes allowed in _within: municipal enclaves).
- provisioning_areas_within: clip to own municipio polygon, parts < within_min_part_km2 (config, default 0.01) dropped
  (provisioning_within_dropped_parts.csv: 1,521 parts, 3.38 km2). Columns area_km2, share (0-1), n_parts. NULL attrs
  without WPA; NULL geom + area 0 + n_parts 0 when nothing inside. Scratch: 3,084 with geometry, 295 entirely outside
  (Rio, Fortaleza, Niterói, São Gonçalo), median share 0.209.
- Tested on scratch (T1 symlinked, catchments copied): every non-provisioning layer/table/view identical to the real T2
  (values and geometry blobs); provisioning attributes identical except area_km2 (223 rows grow exactly by their holes).
- synthesis_municipios.py: reads spatial layers without geom (columns from `fields`); + provisioning_within_area_km2,
  _share, _n_parts (56 columns; other 53 identical except provisioning_area_km2). queries/*.sql renamed tables; both run.
- Docs: zenodo_description.html (layout, counts 15, version log 1.1.0 extended: confirm number), README,
  water-supply-nomenclature.md (_within is a clip, not a link; holes), plan.md references.
- User to run: build_database.py --overwrite (real T2), then synthesis_municipios.py --overwrite and the plots. Add
  `"within_min_part_km2": 0.01` to the local config if wanted explicit (default is 0.01).

## 2026-10-27 — provisioning_areas: upstream intakes
- User design: spatial join of intake POINTS (not catchment nesting) with the filled provisioning polygon; groundwater
  dropped; intakes linked to the municipality (provisioning_links) dropped; all use statuses kept (as the dissolve).
- New columns n_intakes_surface_upstream, covered_population_urban_upstream_2020 (served = covered: population x
  share x coverage, surface rows of systems_supply of the upstream intakes' systems, other municipalities, each supply
  row once per area; approach "c": whole system counts even if one intake is upstream). NULL without area; CHECKs tie
  them to n_intakes_surface. Intakes without system count but add no population; rows without coverage add nothing.
- Scratch: 1,618 of 3,379 areas with upstream intakes (max 919, Foz do Iguaçu, 48.5 M). Integrated systems inflate the
  number (Cabreúva/Itu ~21.7 M: the RMSP integrated system counts whole) — known effect of "c", accepted by the user.
- Verified independently for 7 municipalities from the gpkg (point-in-polygon + provisioning_links + view
  systems_supply_population): exact match. Synthesis: 58 columns (2 new, auto). Docs updated.

## 2026-10-27 — municipio_name + municipio_percent
- provisioning_areas and provisioning_areas_within: + municipio_name (copy from municipios, after the key, NOT NULL).
- provisioning_areas_within: + municipio_percent (0-100) = area_km2 / municipality polygon area, both ESRI:102033
  (not the DTB area_km2; max diff vs DTB is small). Checks: BETWEEN 0 AND 100, NULL together with area_km2.
  Scratch: median 15.3%; Porto Alegre 100%, São Paulo 15.75%, Manaus 82%.
- `share` stays a 0-1 fraction (percent asked only for the new column): possible inconsistency to raise with the user.
- synthesis: skips municipio_name of non-municipios layers; + provisioning_within_municipio_percent (59 columns).

## 2026-11-10 — catchment revision run prep; municipios / intake_name columns
- revise_catchments.local.json: replace items were `{code: path}`, fixed to `{code: {"replace": path}}`. Dry run:
  7 replacements apply (2 intake-distance warnings: IN07646941409296001 1,872 m, IN07028561320631001 1,852 m);
  3 edit items skipped (IN05984471297669001, IN08714461380733001, IN06699651356994001: geometry unchanged in T1, the
  QGIS edits were never saved). 13 rows already manual_replaced from before (Guaíba x12, IN07101421305821001).
- Which were revised: catchment_source (manual_replaced / *_manual_edits) + the run log; exact set = diff vs backup.
- User request (scope exception, for the Brazil-wide catchment revision in QGIS): intakes + `municipios` (after
  intake_name), catchments + `intake_name`, `municipios` (after intake_code). municipios = DTB names of the
  provisioning_links municipalities (direct + via system), sorted (accent-insensitive), " | "; NULL without a link.
  Names only, no UF (homonyms possible). Scratch build: all checks pass; 18,252 intakes and 4,063 catchments all have
  a list (max 30 names); 6 catchments with NULL intake_name (source); other columns + geometry identical to real T2.
  Zenodo version log line updated.
- User to run: revise_catchments.py (real), then build_database.py --overwrite.

## 2026-11-10 — plots/plot_municipio_check.py (catchment revision maps)
- Strategy (prompts/revision_plan.md): by state; capital system first (visual + sanitation plans), then metropolitan
  municipalities, then suspicious ones (provisioning area < 100 m2/inhabitant, later 1 ha).
- New script (user asked tool/, then plots/): one municipality -> <code>_<NAME>.jpeg, 20 cm, 300 dpi. Intakes =
  provisioning_links (direct + system); catchments of those; frame = municipio + catchments + 4% margin (points
  outside only logged); UTM (estimate_utm_crs); scale bar, small legend with counts, title "code  Name (UF)".
  Drainage optional: HydroRIVERS sa shp read in place via /vsizip with bbox + where (GDAL quirk: `where` with
  columns=[] returns 0 rows, so all columns are read). Local config output -> T2/REPORT/municipio_checks.
- Tested Caxias do Sul 4305108 in scratch: 6 surface intakes, 6 catchments, 412 drainage lines, 1.6 s.
- Drainage styled by a column (drainage.column, e.g. ORD_STRA): cmap (Blues cut to cmap_range [0.35, 1]) + width
  (linewidth_range [0.2, 0.6]) on the local min-max in the frame; column absent / not found -> single style.
- Layout: A4 landscape (29.7 x 21 cm, 3507 x 2480 px at 300 dpi). Map box left (frame grows on its short side to the
  box aspect), framed, 3-4 inward lon/lat ticks placed where meridians/parallels cross each edge (UTM frame), labels
  bottom/left. 5 cm right panel: code, name (UF), metro region, operator, facts from T2 (municipality area, urban pop
  2020, provisioning area, m2/urban inhabitant, source_mix, topology/parts, upstream intakes), legend, sources.
  width_cm and title keys removed. Caxias do Sul: 295 m2/inhabitant, M-X / 3.
- Background: other municipalities in the frame (light gray #f1f0ec, edges #c4c3be 0.3 pt); target municipio fill +
  stronger border (#3d3c39, 0.9 pt) drawn above the catchments. Seats (municipios_sedes) as small diamonds with names
  (white halo; own name bold), labels under the intake points so no intake is hidden. Legend + 2 entries.
- Intakes restyled: surface blue #2a78d6 (was light purple #a78bfa), groundwater orange #ef7d1a, both larger (point_size 32) with a white border (point_edge 0.9 pt); legend markers to match.
- Seat labels capped: max_labels (default 20), own municipio first then by urban population 2020; all diamonds drawn. São Paulo 3550308: 54 seats, 20 labelled; only 5 surface intakes/catchments linked, 84 m2/inhabitant (Cantareira not in the links: revision/link candidate).
- Unlabelled seats: smaller (seat_unlabelled_scale 0.55 of the marker area) and lighter (#9a9994); labelled ones unchanged.
- Optional water_bodies polygon layer (IBGE BC250 hid_massa_dagua_a, EPSG:4674, spatial index: fast): light blue #b9dcf2, edge #7fb3d5 0.2 pt, above municipality fills, below catchments (zorder 1.5; tried above catchments + drainage, user reverted); path accepts QGIS "file|layername=x". Shared reader read_in_frame (drainage uses it too). Legend + credit line.
- Projection: default "local" = Lambert azimuthal equal-area centred on the bounds of municipio + catchments (was UTM of the municipio: wrong for catchments spanning zones); "utm" or any CRS via the projection key. Reading bboxes from a densified frame (curved edges in lat/long). Porto Alegre (85,403 km2 Guaíba, ~5° wide) renders fine: 391 seats, 19k drainage lines.
- Batch: config key `municipios` = code | list | txt file (one code per line, '#' comments, extra text after the code
  ignored) | list mixing both; old `municipio_code` still read. --municipio takes several codes/files (cwd-relative).
  Per-municipio errors logged, batch goes on, exit 1 at the end; skip_existing / --skip-existing. Refactor: plot_one().
  Tested: list with comment, repeat, unknown code 9999999 (logged, exit 1); skip-existing. Configs: municipios list
  (local config had 4322400 set by the user, kept).
- Phases (user): 1 = 27 state capitals; 2 = 20 largest municipalities per state (proxy for urban centres; the 1,000+
  metropolitan municipalities are too many); then suspicious cases (< 100 m2/inhabitant).
- plots/lists/capitals.txt (27 codes, names checked in T2) + plot_municipio_check_capitals.{example,local}.json, output
  T2/REPORT/municipio_checks/phase1_capitals (the script creates folders). Scratch run: 27/27 in 2 min 41 s.
  Notes: Natal 109 groundwater intakes, 0 catchments, 6 points outside the frame (frame = municipio + catchments);
  Aracaju 630,351 km2 (São Francisco), 2,479 seats in frame.
- Frame = core municipio parts + catchments + linked intake points (+ margin); projection centre from the same extent.
  core_parts: parts > part_max_distance_km (50, ESRI:102033) from the largest part dropped from the frame only (still
  drawn if inside). Vitória: 5 parts dropped (Trindade, Martim Vaz); Florianópolis: none (mainland part kept).
  Natal: all 109 groundwater points now inside the frame.
- Title 11 pt (title_size), wrapped at 24 chars, shrinks by 0.5 pt down to 8 pt until each line fits the panel
  (measured with the renderer). Belo Horizonte (MG) now fits.
- Optional urban_areas (IBGE BC250 lml_area_densamente_edificada_a, 8,391 polygons, EPSG:4674): #814446, no border, alpha (1), zorder 1.2 just above the municipality fills; legend + credit; added to all 4 configs. BH: 115 polygons.
- Drainage declutter: drop_fraction (0.1) of the local min-max scale dropped. With ORD_STRA (integers, local min always 1) it only ever drops order 1 (~50% of reaches): Caxias 284/587, BH 433/855, POA 9,748/19,127, Aracaju 70,164/138,714. Does not scale with extent until max order >= 11: alternatives offered to the user (larger fraction, UPLAND_SKM on log scale, target count).
- Declutter replaced (user chose option 3): drainage.max_reaches (2000; 0 = all) largest by column kept, ties broken by tie_column (UPLAND_SKM: downstream reaches of a partly kept order stay; without it whole classes dropped). drop_fraction removed. Color/width scaled on the min-max of ALL reaches in the frame before the cut (scaling on the kept range made order 7 thin and light on Aracaju, São Francisco invisible). Caxias 587/587, POA 2000/19,127 (orders 4-7), Aracaju 2000/138,714 (7-8). Configs: "where": "ORD_STRA >= 1" removed (no-op), max_reaches + tie_column added.
- Zoom mode: "zoom": "intakes" (optional) -> square centred on the intake points' bounds, side = zoom_scale (5) x
  their larger side, min zoom_min_km (10); projection centred there; then grown to the map box aspect. No points ->
  default frame. Config plot_municipio_check_capitals_zoom.{local,example}.json -> phase1_capitals_zoom. Scratch:
  27/27 in 55 s (after fix). Squares 10 km (Fortaleza, intakes clustered at Gavião) to 478 km (Rio): with spread intakes
  5x zooms OUT (BH 270 km > default frame) - told the user.
- Fix: draw() helper skips empty layers (geopandas hands an empty frame to pandas: "no numeric data to plot";
  Fortaleza 10 km frame had no seat).
- Zoom falls back to the default frame when its frame (after aspect growth) is not smaller in area (both LAEA, equal-area) - make_frame() builds both. Capitals: 14 zoomed, 13 default (Natal, João Pessoa, Recife, BH, Vitória, Rio, SP, Curitiba, Florianópolis, Campo Grande, Brasília...): intakes spread, 5x too wide.
