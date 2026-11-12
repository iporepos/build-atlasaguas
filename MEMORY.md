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
- Drainage declutter by map scale (2026-11-11): max_reaches counted reaches, which depends on how HydroRIVERS splits
  the network, not on what fits on the map. New drainage.cut {column (UPLAND_SKM), min_spacing_mm | value_ref+ref_km+
  exponent | table [[frame_km, value]] + interp loglog/loglin}: reaches below a threshold that grows with the frame width
  are dropped (cut_threshold()). min_spacing_mm: area = area_factor x (s x ground km per paper mm)^2 (map 230 mm wide).
  max_reaches is now only a guard (default 0 with a cut, 2000 without). "scale": "log" for color/width (UPLAND_SKM).
  Calibration (scratch, s = 2/3/4 mm): Fortaleza zoom 12 km and Caxias 80 km keep all (below the HydroRIVERS 10 km2
  floor); POA 482 km 10,649/7,548/5,972 of 19,127; Aracaju 1,935 km 30,943/21,835/16,959 of 138,714. Same look on
  POA and Aracaju at 4 mm (exponent 2 holds); 2 mm busy at print size. Chosen: 4 mm, max_reaches 20000.
  Configs updated: capitals + capitals_zoom (local + example), main example. The user kept the main local on ORD_STRA /
  max_reaches 10000.
- Optional countries layer (2026-11-11, user spec): Natural Earth 10m admin_0 (natearth_south_america.gpkg, EPSG:4326),
  deepest (zorder -1, below the municipalities), fill #e6e5e0, edge #a9a8a3 0.5 pt; names from label column
  (SOVEREIGNT) in light italic caps at the representative point of the part in the frame, only if >= 1% of the frame
  (label_min_fraction); filter = label values left OUT (["Brazil"]). Credit line, no legend entry. Added to all 6
  configs. Scratch: Uruguaiana (Argentina, Paraguay, Uruguay), Foz, Corumbá (Bolivia, Paraguay), Aracaju (none) fine.
  NE vs IBGE border mismatch leaves thin slivers (acceptable in the background). Bug caught: loop var `name` shadowed
  the municipio name (files came out *_PARAGUAY.jpeg) - renamed.
- Optional ocean layer (2026-11-11, user): Natural Earth ne_10m_ocean.shp (one global polygon, no spatial index):
  read_in_frame(clip=True) cuts it to the frame bbox in EPSG:4326 before projecting (the local LAEA cannot take the
  whole world). Very bottom (zorder -2), #dce9f2 (paler than inland water), no edge. grow_km (2): buffered into land
  (hidden under municipalities/countries) to fill gaps where the IBGE coast lies seaward of the 1:10m one; Florianópolis
  still has one small sliver S of Palhoça (3 km would cover it). Legend "Ocean" + credit.
- water_bodies.marine {column tipomassadagua, values Baía/Oceano/Enseada}: BC250 bays drawn in the ocean color, no edge,
  at the water-body level (they cover municipality fills reaching into the bays). Laguna stays inland. Florianópolis
  bays, Guanabara OK. Both keys added to all 6 configs. Scratch tests: Aracaju, Florianópolis, Rio, Uruguaiana,
  Fortaleza zoom, Brasília (inland, no ocean).
- Zoom mode reworked (2026-11-11, user): frame = union of the municipality bounds (core parts) and the square on the
  intake points (side = their larger side, centred) + zoom_buffer (0.2) x the larger side of that union on EACH side
  (zoom_scale / zoom_min_km removed). Fallback to the default frame kept when the zoom frame is not smaller. Zoom mode
  (also on fallback): file name <code>_<NAME>_ZOOM.jpeg, surface intakes labelled (intake_label, default intake_code:
  names repeat/are often NULL), blue bold 5.5 pt, white halo. skip_existing now mode-aware (zoom/default can share a
  folder). Intakes are MultiPoint: label at the centroid (first run crashed on .x). Capitals scratch: 27/27, 36 s;
  19 zoomed (Fortaleza 42 km ... Porto Velho 704 km, huge municipality), 8 default kept (Palmas, Natal, João Pessoa,
  SP, Florianópolis, Campo Grande, Brasília...): catchments small, default 4% margin tighter. BH labels cluster
  south of the city (accepted by the user).
- Zoom rule v3 (2026-11-11, user): intake square (side = larger side of the intake bounds) joined with the municipality
  bounds unless the municipality's larger side > zoom_max_ratio (3) x the square side -> square alone, floored at
  zoom_min_km (10; floor applied ONLY to the square-alone case: applied to the union it pushed Fortaleza to the default
  frame). Then zoom_buffer 0.2 per side. Labels: intake_name (user), code only when the name is empty. Capitals scratch
  27/27: intakes only for Porto Velho, Rio Branco, Manaus, Boa Vista, Belém, Macapá, Teresina, Fortaleza, Campo Grande,
  Cuiabá (mostly 16.6 x 14 km = 10 km floor + buffer + aspect); 7 default kept (Palmas, Natal, João Pessoa, SP,
  Florianópolis, Brasília...). Names repeat within a system (BH: 3x "Integrado - Paraopeba").
- (2026-11-11, user) Aqueducts: T2 layer `aqueducts` (443 lines, all statuses incl. planned: Operando 217, Existente
  64, Em Projeto 57, Em Obras 49, Planejado 38...; filter with aqueducts.where), magenta #d6198f 0.8 pt, zorder 3.2
  (above drainage, below seats); legend "Aqueduct (n)". Other intakes (other_intakes, default true): intakes in the
  frame not in provisioning_links of the municipality, 10 pt area, no border, darker colors (surface #174a8c,
  groundwater #a4520c), zorder 3.8 under the linked ones; legend with counts. Panel: italic "full view" / "zoom view"
  under the title (the frame actually used: a zoom run that falls back says "full view"); metropolitan region dropped.
  Added to all 6 configs. Scratch: Fortaleza, BH, Salvador in both modes OK (BH zoom: 7 aqueducts, 80 other intakes).
- Zoom intake labels "name - tradename" (2026-11-11, user): intake_label = column or list (default ["intake_name",
  "intake_tradename"]), joined " - ", empty/repeated (case-insensitive) values dropped, code when all empty. T2: 631 of
  18,252 intakes without tradename, 38 equal to the name. BH labels now distinct ("Integrado Ibirité - Bálsamo"...),
  still overlapping in the Ibirité/Catarina cluster (accepted).
- (2026-11-11) Legend: counts dropped from the other-intake entries (window artifact, user).
- Intake contrast (2026-11-11, user): other intakes faded (other_alpha 0.4, same darker hues, legend too); linked
  intakes stronger: surface #0a58ca (was #2a78d6), groundwater #f26b00 (was #ef7d1a), plus a dark ring (#1d1d1b,
  point_ring 0.5 pt, drawn as a thicker dark edge under the white-edged point); legend markers with the dark edge.
  Labels use the new surface blue. Checked on BH zoom (before/after crop).
- (2026-11-11) Aqueducts faded 30% in the full view only (aqueducts.full_view_alpha 0.7; legend matches); zoom view opaque.
- (2026-11-11, user) Other intakes: transparency dropped (close wells stacked into dark spots); light opaque colors
  instead: surface_other #8fb0d6, groundwater_other #e3ad84 (other_alpha removed). Drawn under the seats now (zorder
  3.3; a well hid the Sabará diamond), above the aqueducts.
- (2026-11-11, user) Catchment borders stronger: #256b25 (was #3f8f3f), 0.7 pt (was 0.4; catchment_linewidth), legend matches.
- Font (2026-11-11, user chose Fira): Fira Sans Regular/Bold/Italic/Medium .ttf + OFL.txt downloaded from the Google
  Fonts repo into plots/fonts (not installed on the system); set_font() registers plots/fonts/*.ttf at start and sets
  rcParams font.family = cfg "font" (default "Fira Sans"; DejaVu Sans with a log line if not found). Narrower than
  DejaVu: labels/panel fit better. BH full + zoom OK with the current configs. plots/fonts must be committed with
  the script (OFL allows redistribution with the licence).
- (2026-11-11, user) "full view"/"zoom view" now follows the MODE (zoom config -> "zoom view" even when the default frame is kept; was the frame used). Aqueduct fade follows it too (faded only in full mode). Checked: Brasília zoom (fallback) says zoom view, BH full says full view.
- Full-mode intake labels (2026-11-11, user): when the two modes' frames are close, the full view labels the surface
  intakes like the zoom view: full frame width < full_label_ratio (2) x the zoom frame width (linear; zoom frame
  computed quietly in full mode; 0 = never). Capitals: labels on for 9 (Palmas, Natal, João Pessoa, BH 1.3x, SP,
  Curitiba, Florianópolis, Goiânia 1.5x, Brasília), off for 18 (Maceió 2.3x, Vitória 2.4x, Fortaleza/Recife 2.8x
  the closest misses). 27/27 in scratch.
- Zoom-mode aqueducts (2026-11-11, user): split by "status - name", one warm pastel per group (AQ_PALETTE, 8 colors,
  cycled; the mauve #b5838d replaced by #e76f51: lost on the urban fill), linewidth_zoom 1.2, full opacity; list as an
  in-map legend in the lower right corner, 4 rows (legend_rows), columns as needed, names wrapped at 40 chars, title
  "Aqueducts (status - name)"; panel "Aqueduct (n)" entry dropped in zoom mode. aqueducts.split_zoom false = old
  magenta. Full mode unchanged (magenta, faded). Capitals zoom 27/27 (9 frames without aqueducts); BH 7 systems,
  Fortaleza 6 (incl. one "Em Projeto").
- Zoom aqueducts v2 (2026-11-11, user): status is a hierarchy, not merged into the label. Color family per status
  (AQ_STATUS_PALETTES): Operando magenta-purple, Em Obras reds, Planejado yellow-orange; other statuses gray
  (AQ_OTHER_PALETTE); one tone per aqueduct name within its status. In-map legend "Aqueducts": status as bold gray
  subheader (order Operando, Em Obras, Planejado, then others alphabetically), names only under it; 4 rows, filled
  down, a subheader never ends a column (blank inserted). Config: status_palettes / other_palette overrides.
  Capitals zoom 27/27. Open point told to the user: "Existente" (PR 10, RS 26, SC 21: the South's word for operating)
  and "Em Projeto" (CE 36, PE 11) / Em Estudo / Em Licitação / Emergencial fall in gray as specified (Curitiba: all its
  working systems gray).
- (2026-11-11, user) Full-mode intake labels REMOVED again (full view stays clean; labels only in zoom mode;
  full_label_ratio gone). Aqueduct status families (user ok): Existente -> Operando colors, Em Projeto / Em Estudo /
  Em Licitação / Emergencial -> Planejado colors, each keeps its own subheader (AQ_STATUS_FAMILY, override
  aqueducts.status_family); shades counted over the family. NOT tested (user asked to skip testing); compiles only.

## 2026-11-11 - Transfers between intakes, case A (prompts/PLAN_catchments_transfers.md)
- build_database.py: build_transfers() (after build_tables) reads INTAKES-TRANSFERS.json from the T1 folder (config
  `transfers`, optional; no file -> empty layer) {source: [targets]}, validates (object of non-empty string lists,
  duplicated source key via object_pairs_hook, duplicated pair, self-link, chain = code both source and target, unknown
  code, not Superficial, no catchment; all listed in one stop message) and writes the new spatial layer
  catchments_transfers (transfer_id 1..n by (source, target), intake_code = TARGET, source_intake_code nullable for
  case B, catchment_area_km2/n_parts/geometry copied from catchments). build_provisioning: dissolve over codes + extra
  (sources of the linked targets minus the linked codes); n_intakes_transfer = len(extra); bounds check over the same
  set; topology/source_mix/n_intakes_surface unchanged; transfer overlap computed outside relation() (its cache is the
  partial-overlaps report). transfers_check.csv report. main(): schema `uniques` of spatial layers now unique-indexed
  (ux_catchments_transfers_intake_code_source_intake_code).
- Schema: catchments_transfers after catchments (FKs to intakes on both codes, CHECKs n_parts >= 1 and no self-link);
  provisioning_areas.n_intakes_transfer after n_intakes_system_only + 2 CHECKs; n_intakes_surface description updated.
  Docs: module docstring (16 tables: 8 plain + 8 spatial), example config, README section, nomenclature sections 3/7/10,
  zenodo html (16 data tables, layer, version line "[version to confirm]" at the top). publish.py: *.json not skipped
  (JSON goes into the T1 zip). synthesis_municipios.py picks n_intakes_transfer up from `fields` (no change needed).
- Tested in scratch (T1 symlinked, catchments copied), 27 s per build: (1) no JSON vs HEAD build: every table/layer/view
  and every report identical, only the new empty layer, n_intakes_transfer = 0 and the catalogs differ. (2) JSON
  Assaré -> Potengi + Araripe, Altaneira -> Araripe + Aurora (CE), Areado's own 2nd intake -> its 1st (MG): only the 3 CE
  rows change in provisioning_areas(_within); Araripe 109 -> 721 km2, independent dissolve matches (0.16 km2 = 16 filled
  holes), n_intakes_transfer 2/1/1. (3) copies byte-identical to catchments; after a revise_catchments replace of
  Altaneira (60.9 -> 38.1 km2) the copies and dissolves follow. (4) 11 negative cases stop with clear messages.
  (5) FKs, unique indexes, CHECKs, verify_spatial, columns pass. (6) Areado: n_intakes_transfer 0, area unchanged.
- Effect told to the user (open point 1): source intake points fall inside the target city's area and count as
  upstream (Araripe/Aurora: 1 upstream intake, 4,448 people). Scope exception (new layer + column) and the Zenodo
  version number left to the user. The user must create the real JSON in T1 and rebuild T2. Not committed.
- Case B (2026-11-11, user: name CATCHMENTS-TRANSFERS.gpkg, no fingerprints, overlap warning ok; count column
  explained, decision pending): T1 GeoPackage (config transfer_areas), layer catchments_transfers, intake_code (target)
  + optional note, any CRS. read_transfer_areas(): reproject to the catchments CRS, revise_catchments.clean, geodesic
  area, n_parts; source_intake_code NULL, after case A rows in file order; T2 layer got a nullable `note` column.
  Stops: missing layer/column/CRS, feature without code, target not surface/with catchment, no polygon left, target
  that is a case A source. Dissolve: drawn polygons of the city's targets (deduped by transfer_id) added, bounds check
  includes their area_crs area; NOT counted in n_intakes_transfer (count column to decide). transfers_check.csv now per
  row with transfer_id (overlap with the target catchment for drawn ones).
  Scratch: 7 polygons (UTM input, one shared by 2 cities, one shared by both Barroso intakes -> +12.49 km2 once, a bow
  tie -> repaired, 2 parts, one over Potengi's own catchment -> overlap 1.0 in the report): only the 4 target cities
  change, Potengi equals an independent dissolve exactly; 9 negative cases stop; build without both files: only case A
  rows differ from the case-A build.
- Renamed (2026-11-11, user): config keys transfers_intakes / transfers_catchments, files TRANSFERS-INTAKES.json /
  TRANSFERS-CATCHMENTS.gpkg (both optional; input layer still catchments_transfers). Scratch build with the new names:
  same 12 rows and report as before.
- (2026-11-11, user yes to both) Input layer renamed transfers_catchments (inside TRANSFERS-CATCHMENTS.gpkg; the old
  name stops the build: "layer transfers_catchments not found"). New provisioning_areas.n_transfer_areas (after
  n_intakes_transfer, NOT NULL, CHECKs >= 0 and 0 without surface intake): drawn polygons in the dissolve, identical
  geometries (normalized WKB) drawn for two targets of the same city counted once (Barroso: 1, was 2 per feature).
  Scratch: Araripe 2/1, Aurora 1/2, Potengi 1/2, Barroso 0/1; areas unchanged; synthesis CSV picks the column up.
  Docs (README, nomenclature, zenodo, schema descriptions) updated.
- Relevant aqueducts (2026-11-11, user): plot_municipio_check.py reads the whole T2 aqueducts layer (aqueducts.where),
  relevant = every line whose aqueduct_name (= system; 426 names / 443 lines, repeats are real multi-part systems) has a
  line intersecting the municipality polygon or one of its catchments. Their extent is added to the frame in both modes
  (aqueducts.extend_frame, default true; zoom: before zoom_buffer); zoom mode colors + map legend only for them, the
  others light magenta (full_view_alpha) like the full view; panel entry "Aqueduct (n)" now in both modes.
  aqueducts.relevant false = off. Scratch (6 capitals, both modes): BH zoom good (131.9 x 111.3 km, 7 systems). Issue
  reported, decision pending: long systems crossing large catchments without supplying the city (Recife, Maceió:
  Adutora do Agreste, Sistema Integrado do Agreste/Garanhuns) blow the frame up to Maceió/Arapiraca; and in zoom the 20%
  buffer applied after adding the aqueducts makes the zoom frame larger than the default (Fortaleza, Natal, João
  Pessoa, Recife, Maceió fall back to the default frame).
- (2026-11-11, user chose) Relevance narrowed: municipality polygon OR within aqueducts.intake_km (2) of a linked intake
  point (ESRI:102033); catchments no longer used. Zoom: zoom_buffer applied to the intake/municipality box first, then
  the relevant aqueduct extent added with the default margin (0.04) only when it reaches out. Recife zoom 96.9 x 81.7 km
  (8 systems; was ~183,000 km2 with the catchment rule), Maceió 62.8 x 53.0 (3), BH 115.9 x 97.8 (7), João Pessoa
  77.2 x 65.1 (1); Fortaleza zoom = default (Acarape do Meio-Gavião line). Capitals scratch: 27/27 both modes, zoom
  21 zoomed / 6 default kept. Configs unchanged (defaults).
- Minor direct intakes (2026-11-11, user; plots only, T2 unchanged): plot_municipio_check.py minor_direct (default
  true): linked intakes with link_source direct in a municipality that has systems_supply rows with covered_percent > 0
  (so none for the intake's systems) -> gray (#9a9994) point with the dark ring, label in gray (zoom), legend "Minor
  direct intake (n)", catchment not drawn, excluded from the frame, the relevant-aqueduct search and the intake counts.
  New configs plots/plot_municipio_check_rio_zoom.{local,example}.json (3304557, zoom, output municipio_checks).
  Scratch Rio zoom: Imunana (IN06731581370495001) is the minor one; frame now Guandu + Lajes only (default kept, 10,667
  km2); the Imunana point lies outside the frame (legend says 1 but nothing drawn). Panel values (provisioning area
  3,635 km2, topology M-X / 2, upstream 18) still come from T2 and include the Imunana catchment. Only Rio tested.
- Transfers in the plots (2026-11-11, user): plot_municipio_check.py `transfers` (default true) reads T2
  catchments_transfers when the gpkg has it: rows whose target is a linked, non-minor intake, sources linked to the
  municipality left out, a polygon reached through two targets drawn once (source code / identical WKB). "Transfer
  catchment" #c9d43a (alpha +0.1), dashed #7c8a14 edge, zorder 1.9 under the catchments; source intakes "Transfer
  intake" #a4b81c points with the dark ring, labelled in zoom (#7c8a14). Both always in the side legend, also 0. Frame:
  points = linked + minor + transfer intakes (both modes); the full frame also gets the transfer catchments; minor
  points now in both frames. Other intakes exclude the transfer intakes. Scratch: Araripe full + zoom on the scratch T2
  with transfers (3 transfer catchments incl. 1 drawn, 2 transfer intakes); Rio zoom on the real T2 (which already has
  the empty catchments_transfers layer: legend 0/0; Imunana gray point now in the frame at the right edge, default
  frame kept, label clipped by the edge).
- (2026-11-11, user) Side legend: bold gray "Intakes" subheader (handle.subheader flag, bolded in side_panel), then
  Surface (n), Surface - minor (n), Surface - transfer (n), Groundwater (n) (all always listed), Surface (others),
  Groundwater (others). Checked on Rio zoom only.
- (2026-11-11, user) Side legend: "Catchments" subheader with Local (n) and Transfer (n), right after the Intakes group;
  a blank spacer ends each group; Aqueduct and the context layers follow ungrouped. Checked on Rio zoom only.
- (2026-11-11, user) Legend subheaders (side legend Intakes/Catchments and the zoom aqueduct legend statuses): dark ink
  (#0b0b0b) instead of ink2, moved left over the empty handle (subheader(): ScaledTranslation of (handlelength +
  handletextpad) x fontsize) so they align with the symbols. Checked on Rio zoom.
- (2026-11-11, user) Side legend last block reordered: Municipal seat, Municipality, Other municipalities, Urban area, Water body, Ocean, Aqueduct, Drainage. Checked on Rio zoom.
- (2026-11-11, user) Intakes legend: Surface - transfer now above Surface - minor (compile check only).
- (2026-11-11, user) Transfer catchment edge solid (was dashed), map and legend (compile check only).
- (2026-11-11, user) Side legend: aqueduct count dropped (window artifact, like the other intakes): entry is just "Aqueduct" (log line keeps the count). Compile check only.
- Case C transfers (2026-11-11, user): TRANSFERS-INTAKES.json may hold "catchments_only": {source: [targets]} = only the
  source catchment counts (e.g. it feeds an open channel of a transfer aqueduct), the intake point is not relevant.
  New catchments_transfers.transfer_type NOT NULL: intake (A) / catchment (C) / polygon (B), CHECKs on the values and
  (polygon) = (source NULL); ids A, then C (each by source, target), then B. Dissolve: C sources (not linked, not already
  an A source of the city) added; n_intakes_transfer = A only; n_transfer_areas = C + drawn. transfers_check.csv has
  transfer_type. Plot: transfer intake points only for transfer_type intake (fallback: source not null on older T2).
  Validation: pair in both A and C, catchments_only not an object / empty list, repeated key in any object, chains
  across A/C/B. Scratch: Assaré C -> Aurora (+551 km2), Bom Sucesso C -> Potengi (+19.4 km2); n_transfer_areas 3/3,
  n_intakes_transfer unchanged; Potengi map: 1 transfer intake (Assaré), 4 transfer catchments. README, nomenclature,
  zenodo, schema descriptions updated.
- (2026-11-11) Chain rule relaxed for case C: only a case A source that is also a target (any kind) stops the build; a
  catchments_only source may be a target elsewhere (only its own catchment is copied). Drawn-polygon targets must not
  be case A sources. Needed by the user's real T1 JSON: Santa Cecília (IN06751861361611001) -> Parque Santana, Piraí,
  Guandu (A) + catchments_only Parque Santana (IN06747761361967001, 716.7 km2) -> Guandu: validates (4 rows). Not built
  on the real T2 (user rebuilds).
- (2026-11-11, user) Transfer intake points purple #7b3fa0 (dark ring kept), zoom labels in the same purple. Checked on Araripe zoom (scratch T2).
- (2026-11-11, user) Intake labels (zoom) no longer colored: all kinds (surface, transfer, minor) in dark ink #0b0b0b, bold 5.5 pt, white halo. Checked on Araripe zoom.
- 2026-11-11: added plots/plot_municipio_check_sul{,_zoom}.local.json (Curitiba, Florianópolis, Porto Alegre; full and zoom), copies of the capitals configs with the same output folder. Not run.
- 2026-11-11: added plots/plot_municipio_check_centro_oeste{,_zoom}.local.json (Campo Grande, Cuiabá, Goiânia, Brasília; full and zoom), same output folder as the capitals. Not run.
- 2026-11-11: added plots/plot_municipio_check_nordeste{,_zoom}.local.json (9 Nordeste capitals; full and zoom), same output folder as the capitals. Not run.
- (2026-11-12, user) Transfers file may also be TOML: read_transfer_pairs picks the format by extension (.json/.toml,
  else stop; tomllib, stdlib, rejects repeated keys itself), same structure (top-level `source = [targets]`, then a
  [catchments_only] table). Config transfers_intakes now has no default: the build looks for TRANSFERS-INTAKES.json or
  .toml in T1, both present = stop. README updated. Tested in scratch: JSON and TOML give identical pairs; dup/syntax/
  bad value/chain/unknown extension errors; default lookup (toml only; both = stop). No full build run.
- (2026-11-12, user) Converted the real T1 TRANSFERS-INTAKES.json (had // comments: invalid JSON, the build would have
  stopped) to TOML in the scratchpad, comments kept. Same content as the JSON without comments; passes
  read_transfer_pairs against the real T1 intakes/catchments: 37 pairs (3 A, 34 C). User copies it to T1 and removes the JSON.
- (2026-11-12, user) Plot aqueducts: the light background lines (every line in the full view, the non-relevant ones in
  zoom mode) keep only the Operando family (Operando + Existente, via AQ_STATUS_FAMILY / status_family). New
  aqueducts key "background_family" (default "Operando", null = all statuses); side legend "Aqueduct (operating)".
  Zoom relevant systems unchanged (all statuses, colored). Checked on Rio full (16 of 20 lines) and zoom (3 of 5).
- (2026-11-12, user) Transfer catchments greener (were too yellow): fill #c9d43a -> #a8cf4a, edge #7c8a14 -> #5f8a1a
  (hue ~78°, between the old olive-yellow and the local #7cc47c). Checked on Rio zoom.
- Recursive transfers (2026-11-12, user: chains needed, too many copies otherwise). catchments_transfers still one row
  per declared pair / drawn polygon (no expanded rows). transfer_closure(tr, codes): rows whose target is in codes or is
  the source of a row already reached (BFS; polygons end a chain), used by the dissolve (kinds from each row's own
  transfer_type; each source once; A wins over C). Chain errors removed (A source as target, drawn target as A source);
  transfer_cycles() stops the build. redundant_pairs(): declared pair already reached via a chain -> WARNING log line.
  New report transfers_closure.csv (target, transfer_id, depth, ...). Plot: reads the whole layer and follows chains the
  same way. Schema descriptions (catchments_transfers, n_intakes_transfer, n_transfer_areas), README, nomenclature
  updated. Scratch (T1 symlinked, catchments copied): real TOML (37 pairs) -> 11 redundancy warnings; a chained TOML
  without them (26 pairs) gives identical provisioning_areas; HEAD code on the same inputs gives an identical T2 (all
  layers). Plot Rio zoom identical (2 transfer catchments, 1 transfer intake). Real T2 is stale vs T1 (9 CE munis differ,
  older JSON / catchments). User: simplify the TOML (drop the warned pairs), then rebuild.
- (2026-11-12, user, explicit request despite the frozen-scope rule) municipios_sedes gets municipio_name and
  unidade_alias, copied from municipios at build (merge on municipio_code; a seat without municipality stops the
  build). Schema: 2 columns (same descriptions as in municipios) + table description. Plot reads only
  municipio_code from the seats (it merges the names from municipios; a second name column would collide).
  Scratch build OK (5,570 seats, no NULLs); Rio zoom labels OK. User rebuilds T2.
- (2026-11-12, user) plot_municipio_check: "author" key -> "Author: <text>" above the credits (6.5 pt, ink, wrapped at
  42; credits stay 5.5 pt ink2). "font" presets: "default"/"fira" = Fira Sans, "helvetica" = TeX Gyre Heros (Helvetica
  clone, GUST Font License) shipped in plots/fonts (4 .otf + GUST-FONT-LICENSE.txt, copied from the system tex-gyre);
  any other value = installed family. All 18 plot_municipio_check*.json: font "helvetica", author "Iporã Possantti
  (2026). IPH/UFRGS" (local) / "Name (year). Institution" (example). Rewritten with json.dumps: inline lists reflowed
  (content same); git checkout of the 4 example files to undo the reflow was denied. Checked on Rio zoom.
- (2026-11-12, user) Plot credits: author shown without the "Author:" prefix; new "version" key (default "1.0.0")
  as the first credit line "Version: <v>". Local configs 2.0.0, examples 1.0.0 (keys inserted as text, no reflow).
  Checked on Rio zoom.
- (2026-11-12) Zenodo 2.0.0 prep: version log "[version to confirm]" -> 2.0.0 (same number as the plot configs; examples
  of transfers, chains, T1 transfer files), provisioning bullet mentions chains. publish.py --dry-run stops: T2 has a
  -wal (QGIS open / unclean close). Synthesis CSV in T2/REPORT dated 10-27 (stale: rerun synthesis_municipios.py).
  Old 1.1.0 zips in SRC/ZENODO (need --overwrite or move). User runs the steps.
- (2026-11-12, user) Zenodo extras: plots/maps_to_pdf.py (own minimal PDF writer, JPEG embedded as is, page = image
  size at its dpi, bookmarks; folder mode for the maps with municipios order + gpkg names, files mode for any JPEGs).
  plots/plot_fonts.py: shared FONT_PRESETS/set_font (plot_municipio_check imports it; dispersion too, without forcing
  Agg). plot_system_dispersion.py: highlight "values" (list or text file), "label_all", "each" (one plot per value,
  {value}/{label} in title/subtitle/output, value_labels), "font". New configs: plot_municipio_population_{states,
  capitals}.{local,example}.json (output REPORT/dispersion_2020/), maps_to_pdf_capitals.*, dispersion_to_pdf.* (29
  pages: Brazil, capitals, 27 states by name). Population (Brazil) config got font helvetica. Natal: no provisioning
  area (groundwater) -> 26 capitals in the scatter (subtitle says so). Tested in scratch: Rio + Campina maps PDF,
  Brazil/capitals/PB/RS dispersion + PDF. Zenodo html: 2 PDFs in Files + version log. User runs the full batches.
- (2026-11-12, user) dispersion_to_pdf.{local,example}.json: state pages in IBGE state code order (RO 11 ... DF 53),
  after Brazil and capitals; subject says so.
- (2026-11-12, user) Dispersion title: one line (no char-count wrap), font title_size (default 12/13) shrinks in
  0.25 pt steps (min 8) until it ends inside the figure; checked before and after tight_layout. RN, PB, Brazil OK.
