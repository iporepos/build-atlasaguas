# build-atlasaguas

Scripts that build the **ANA Atlas Águas 2021, harmonized and enhanced** database: one GeoPackage, published on Zenodo.

## Scope

The dataset is frozen. The only change allowed is **fixing catchments**: replacing a bad polygon and recomputing its
attributes. New columns, tables or sources go into a separate, extended dataset, not into this one.

## Pipeline

```
legacy ANA files --(archive/standardize_t1.py, done once, archived)--> T1 --(build_database.py)--> T2 gpkg --> Zenodo
                                                                       ^
                                         revise_catchments.py ---------+  (changes the T1 catchments file only)
```

- **T1** is a folder of standardized files. It is the source for every build.
- **T2** is the published GeoPackage. It is always rebuilt from T1 and never edited by hand.
- A catchment fix goes into T1 and reaches T2 at the next build, together with everything computed from it
  (catchment attributes, provisioning areas and their part inside each municipality, overlap and holes reports).
- History lives in the Zenodo versions: each release is a new version under the same concept DOI.

## Setup

```
pip install -r requirements.txt
```

Every script takes `--config <file.json>`. Copy the `*.example.json` next to the script to `*.local.json`, then put your
paths in it. `*.local.json` is git-ignored. Relative paths in a config are read from the config file's folder.

Do not run `archive/standardize_t1.py`: see `archive/PROVENANCE.md`.

## Workflow

### 1. Once: initialize the catchments file

```
python revise_catchments.py --config revise_catchments.local.json --init --dry-run   # check the summary
python revise_catchments.py --config revise_catchments.local.json --init
```

`--init` adds to the T1 catchments GeoPackage:
- the column `n_parts` (number of polygons per catchment), for every row;
- the table `catchments_hashes`, one fingerprint of the current geometry per catchment.

It changes no geometry. Run it once: a second `--init` is refused. Every later run compares the geometries with these
fingerprints to find which catchments changed.

### 2. When a catchment is wrong: revise it

Close the file in QGIS first. The script refuses to write while the GeoPackage is open.

Add one item per catchment to `revisions` in `revise_catchments.local.json`. Choose one of two ways:

| You did | Item in `revisions` | Result |
|---|---|---|
| Edited the polygon directly in the T1 layer (QGIS) | `"IN06731581370495001"` | Attributes recomputed. Source becomes `<old source>_manual_edits` |
| Drew a new polygon in a separate file | `{"IN06731581370495001": {"replace": "fixes/imunana.fgb"}}` | The file's first feature replaces the T1 polygon. Source becomes `manual_replaced` |

Then:

```
python revise_catchments.py --config revise_catchments.local.json --dry-run   # read the report
python revise_catchments.py --config revise_catchments.local.json
```

For each item, the report shows the source, the area (old → new), `n_parts` (old → new) and the distance from the
intake point. A distance warning is information only: Atlas points are often ill-positioned.

The real run saves a backup first (`<name>_backup_YYYYMMDD_HHMMSS.gpkg`), then updates the listed catchments:
- geometry, cleaned (made valid, polygon parts only, MultiPolygon);
- `catchment_area_km2`: geodesic area on the WGS84 ellipsoid;
- `n_parts`, `catchment_source` and the fingerprint.

**Keep the list.** `revisions` only grows: items already applied are skipped. Keep the replacement files, because
they are read again on every run.

**The run stops, and writes nothing, when:**
- a catchment was edited in T1 but is not listed. List it, or undo the edit.
- a catchment listed for `replace` was also edited in T1. The edit would be lost.
- an `intake_code` is not in the layer, or is listed twice.
- a replacement file is missing or has no CRS, or its polygon is empty after clean-up.

Catchments can only be replaced: none is added or deleted, and intake points never move. Several intakes can share
one identical polygon. A fix changes only the `intake_code` you list.

### 3. Rebuild T2

```
python build_database.py --config build_database.local.json --overwrite
```

Rebuild after every set of revisions. The build reads the revised catchments from T1 and recomputes everything that
depends on them.

Before reading T1, the build checks the catchments against their fingerprints. **It refuses to build** when:
- `--init` was never run;
- a catchment was edited in T1 after the last `revise_catchments.py` run, because its area, `n_parts` and source
  would be stale. List it in `revisions` and run step 2 first.

The fingerprints table stays in T1. It is not copied to T2.

### Transfers between intakes (optional)

Some intakes take water from a river that also receives water from another river through a pipe or canal. The
provisioning area of the city must then include the catchment of the **source** river too. When the source is an
official intake of the Atlas, list it in `TRANSFERS-INTAKES.json` in the T1 folder (config key `transfers_intakes` changes
the file name). One key per source intake, with the list of the target intakes it feeds:

```json
{
  "IN08304511400594001": ["IN08291861399164001", "IN08292001398220001"],
  "IN08303171402724001": ["IN08292001398220001"],
  "catchments_only": {
    "IN06898911352570001": ["IN08291861399164001"]
  }
}
```

Top-level entries are transfers between intakes: the source intake is relevant (case A, `transfer_type` `intake`).
Entries under `catchments_only` use only the source catchment, because the intake point itself plays no part, for
example a catchment that feeds an open channel of a transfer aqueduct (case C, `transfer_type` `catchment`). Both kinds
copy the catchment the same way; they differ in the counts and the maps: the source of case A counts in
`n_intakes_transfer` and is drawn as a transfer intake, the source of case C counts in `n_transfer_areas` and gets no point.

At every build:
- the layer `catchments_transfers` gets one row per (target, source) pair, with a **copy** of the source catchment
  (a later catchment revision reaches the copies at the next build). `intake_code` is the target, the intake that
  receives the water;
- the provisioning area of each municipality linked to a target also includes the source catchments;
  `n_intakes_transfer` counts the case A sources that are not already linked to it, `n_transfer_areas` the case C
  catchments and the drawn polygons;
- `transfers_check.csv` in the report folder lists each pair with both areas, their overlap and the target's
  municipalities. A high overlap suggests the two intakes are on the same river, not a real transfer.

When no official intake exists at the source (for example a reservoir chain), draw the area as a polygon in
`TRANSFERS-CATCHMENTS.gpkg` in the T1 folder (config key `transfers_catchments`), layer `transfers_catchments`: one
feature per target, with the column `intake_code` (the target intake), an optional free-text `note`, any CRS. A polygon
that feeds two targets is drawn twice. At every build each polygon is reprojected, cleaned like a catchment revision
and measured (geodesic area, `n_parts`), then added to the layer with `source_intake_code` empty (`transfer_type` `polygon`, case B) and included
in the provisioning areas of the target's municipalities, where `n_transfer_areas` counts them. Edit the file freely: it is read again at every build, with no
fingerprints. The build stops on a missing layer, column or CRS, an unknown or groundwater target, a target without a
catchment, a feature with no polygon, or a target that is also a case A source in the JSON.

Transfers are not followed in chains: a code that is both a case A source and a target stops the build. If C receives
water from B, and B from A, write both sources for C. A `catchments_only` source may be a target elsewhere: only its
own catchment is copied, nothing that reaches it. A drawn polygon's target must not be a case A source either. The build also stops on an unknown code, a groundwater intake, an intake
without a catchment, a self-link, a pair listed twice (also once at the top and once in `catchments_only`) or a key repeated in one object. Without the file the layer is empty.
The catchments themselves never change: a catchment is one outlet, one polygon.

### 4. Publish

```
python publish.py --config publish.local.json --dry-run   # check the file lists
python publish.py --config publish.local.json
```

This writes `T1_ANA_ATLASAGUAS_DB_BRAZIL_2021.zip` and `T2_ANA_ATLASAGUAS_DB_BRAZIL_2021.zip` to the output folder.
Backups, old zips and the files in `skip` are left out. Close QGIS first: an open GeoPackage stops the run.
Upload both zips as a new version of the Zenodo record, with the description in `docs/zenodo_description.html`.

## Municipality synthesis table

`synthesis_municipios.py` writes one CSV row per municipality (5,572) with every per-municipality value in T2:
attributes, indicators (2020 and 2035), supply shares and covered population, provisioning area attributes
(total and inside the municipality),
investments and proposal counts. A glossary CSV (pt/en, units) is written next to it.

```
python synthesis_municipios.py --config synthesis_municipios.local.json
```

Run it after each T2 build. It only reads T2.

## Plots

`plots/plot_system_dispersion.py` draws scatter plots from the T2 GeoPackage. It uses the SQL queries in `queries/`.

```
python plots/plot_system_dispersion.py --config plots/plot_municipio_provisioning.local.json
```
