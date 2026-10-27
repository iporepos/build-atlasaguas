# Water Supply Nomenclature: Intakes, Catchments and Provisioning Areas

Working notes for the Atlas Águas urban water supply data system (Brazil). Status: draft, nomenclature under definition.

---

## 1. Scope

- Drinking-water supply systems for urban areas in Brazil, based on the Atlas Águas intake points.
- The system is described **from the catchment to the people served**. This deliberately extends the conventional view, which starts at the intake, upstream into the catchment.
- Raw water, treatment and distribution are in scope. Wastewater treatment is out of scope.

---

## 2. Spatial objects

| Term | Definition |
|---|---|
| **Intake** | Withdrawal point of raw water (river, reservoir or well). In hydrological terms it is an *outlet*. |
| **Catchment** | Reserved strictly for the area draining to **one outlet**. Each surface intake has exactly one catchment. |
| **Provisioning area** | Dissolve of all catchments that provision a municipality. It is **not** a catchment, because it has several outlets. It carries the ecosystem-service sense of *provisioning*. |
| **Delivery area** | Footprint (polygon) of the pipe network that distributes treated water. Gray infrastructure, urban. Always a different geometry from the provisioning area. |

Why "provisioning" and "delivery": *supply* alone is ambiguous between the producing side and the distributing side. Provisioning links to the ecosystem-service concept; delivery refers to the pipe network.

## 3. System objects

- **Supply system (drinking water)**: the whole chain: provisioning area, intake, raw-water conveyance, treatment plant, delivery network, people served.
- **Transfer**: an aqueduct or conveyance linking a distant intake to the system. It is a *link*, not an area. It matters because the provisioning area can lie in a different basin from the city (e.g. São Francisco water reaching Northeast municipalities).
- Chain structure is a **graph, not a line**: several intakes can feed one plant, one intake can feed several plants, a plant can feed several delivery areas. Shares belong on the **links** (intake → plant, plant → delivery area), not on the intake alone.

---

## 4. Canonical cases (by catchment topology)

1. **Single**: one intake, one catchment.
2. **Multiple, nested**: intakes on the same stem; the downstream catchment contains the upstream one. The *incremental area* is the difference.
3. **Multiple, disjoint**: intakes on different stems or networks.
   - *Adjacent*: share a divide; the dissolve is contiguous.
   - *Remote*: spatially separate; the dissolve is multipart.
4. **Multiple, mixed**: e.g. two nested intakes plus one disjoint.

Topology is a **state variable**. It changes when a city adds an intake (single becomes nested, and so on). It is kept as an optional descriptive attribute with a reference date, **not** as a classification key. Codes like `S`, `M-N`, `M-D`, `M-X` may be used if wanted.

Complications beyond the canonical cases:
- Non-surface sources (wells, springs, cisterns) have no catchment.
- Transfers can bring water from distant basins.
- Systems shared among municipalities (many-to-many between systems and cities).

---

## 5. Population fields

Two percentages that must **never be mixed**:

- **`share_alloc`**: allocation of the system's delivery across intakes. Always sums to 100%. This is a normalization, not a coverage measure. Believed (to be verified) to be the share of the *served* population, since values always sum to 100% even for municipalities with low coverage.
- **`coverage`**: served population ÷ total municipal population. This is the **universality indicator** for basic sanitation. Low coverage flags cities that need system expansion.

If `share_alloc` is relative to the system's served population:
`share of municipal population = share_alloc × coverage`

**Partition of municipal population** (sums to 100%):
- Served (inside delivery area and connected)
- Urban, not covered
- Rural
- Alternative sources (springs, cisterns, private wells): outside the engineered system

**Intake capacity**: changes over time (more pumps, etc.) and is unknown for Atlas Águas. Keep as an optional, time-stamped attribute, `null` by default. Do not use it as the share definition.

---

## 6. Structure vs. state

- **Structural / long-lived**: intake, catchment, provisioning area (fixed infrastructure and geography).
- **State variables** (change over time): capacity, `share_alloc`, topology, coverage.

---

## 7. Layer design

### Intake catchment layer (base)
- One polygon per surface intake. Keyed by intake.
- This is the source of truth for any national area total.

### `provisioning_area` (derived)
- **One row per municipality**, keyed by `municipio_code` (IBGE 7-digit).
- **Geometry always MultiPolygon**, even when there is a single part. This removes type checks downstream and keeps the schema stable when a city adds a second intake.
- Single-catchment system = MultiPolygon with one part.
- Built by dissolving all catchments linked to the municipality, so nested areas are never double-counted.

**Implementation notes**
- Force the type at write time: `ST_Multi` in PostGIS, or in geopandas dissolve then cast to MultiPolygon. A dissolve silently returns Polygon for single-part cases otherwise.
- Municipalities with no surface intake (wells only, or transfers with no mapped catchment) **still get a row**, with `geometry = NULL`, so `municipio_code` is a complete key across roughly 5,570 municipalities and "no polygon" differs from "not processed". Add a flag (`has_surface_intake` or `source_mix`) stating the reason.
- Derived attributes worth storing: `n_intakes`, `n_parts` (`n_parts > 1` flags disjoint cases), `area_total`, optionally topology with its reference date, and optionally the share of the largest intake.
- Holes: catchments have none, so a hole in the dissolve is a gap between neighbouring catchments (an area enclosed by catchments drains through them). Every hole is filled.
- Transfers: include transferred intakes' catchments in the dissolve and flag the row `has_transfer`, so "provisioning area" means everything that physically feeds the city.

### `provisioning_area_within` (derived)
- The provisioning area clipped to the municipality's own polygon, one row per municipality, parts under 0.01 km² dropped (border slivers).
- Not a link: the municipality–intake link is still the supply relation (rule 2). The intersection only clips an area already linked.
- NULL attributes without provisioning area; NULL geometry with area 0 when the municipality is supplied entirely from outside.

---

## 8. Rules to keep

1. **Catchment** is reserved for the outlet concept: one outlet, one catchment.
2. Municipal links go through the **supply relation** (intake → system → city), **never through spatial intersection**. A catchment often lies partly or wholly outside the municipality.
3. Shared systems produce **overlapping provisioning areas** across municipalities. This is expected. National totals must be computed from the intake-catchment layer, never by summing municipal rows.
4. The dissolve loses weighting: one part may supply 90% of the people and another 10%. Keep `share_alloc` at the intake level and derived attributes at the municipal level.
5. Keep raw-water geometry (provisioning area) and service geometry (delivery area) as separate objects.

## 9. Resulting chain

```
intake (outlet) -> catchment (1 per surface intake) -> provisioning_area (1 per municipality, MultiPolygon, key: municipio_code)
                                                    \-> treatment plant -> delivery area (pipe-network footprint) -> population served
```

---

## 10. Open questions

- Does Atlas Águas give the population share per **intake** or per **system**? This decides whether the intake → plant links must be reconstructed.
- Confirm that `share_alloc` is a share of the served population (sums to 100%), not of the total municipal population.
- Representation of **transfers** (link table with origin intake, destination system, conveyance type).
- Formal treatment of **shared systems** (one system, several cities, share matrix as a many-to-many relation).
- Final field names for the intake, system and provisioning-area tables.
