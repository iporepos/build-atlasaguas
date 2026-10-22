-- Atlas Aguas T2: covered population (2020) vs catchment area, one row per supply system.
-- Run in the QGIS DB Manager SQL window on ANA_ATLAS-AGUAS_BD_BRASIL_2021.gpkg (unique id column: system_id).
-- Population: municipal urban population 2020 x system share (systems_supply) [x municipal supply coverage = covered].
-- Area: sum of the catchments of the system's intakes (no overlap correction; an intake shared by two systems
-- counts for both). Only systems with at least one catchment appear.
SELECT
    y.system_name,
    mu.municipios_name,
    pop.covered_population_2020,
    ca.catchment_area_km2,
    pop.covered_population_2020 / NULLIF(ca.catchment_area_km2, 0) AS covered_population_per_km2,
    pop.assigned_population_2020,
    mu.municipios_count,
    ca.intakes_with_catchment,
    pop.rows_without_coverage,
    y.system_type,
    y.system_id
FROM systems AS y
JOIN (
    SELECT
        s.system_id,
        SUM(p.population_urban * s.covered_percent / 100.0)                              AS assigned_population_2020,
        SUM(p.population_urban * s.covered_percent / 100.0 * p.supply_coverage / 100.0) AS covered_population_2020,
        SUM(CASE WHEN p.supply_coverage IS NULL THEN 1 ELSE 0 END)                       AS rows_without_coverage
    FROM systems_supply AS s
    JOIN municipios_indicators AS p
      ON p.municipio_code = s.municipio_code AND p.year = 2020
    GROUP BY s.system_id
) AS pop ON pop.system_id = y.system_id
JOIN (
    SELECT
        d.system_id,
        COUNT(*)                   AS municipios_count,
        GROUP_CONCAT(d.nm, ' | ')  AS municipios_name
    FROM (
        SELECT DISTINCT s.system_id, a.municipio_name || ' (' || a.unidade_alias || ')' AS nm
        FROM systems_supply AS s
        JOIN municipios_attributes AS a ON a.municipio_code = s.municipio_code
        ORDER BY s.system_id, nm
    ) AS d
    GROUP BY d.system_id
) AS mu ON mu.system_id = y.system_id
JOIN (
    SELECT
        i.system_id,
        COUNT(*)                     AS intakes_with_catchment,
        SUM(c.catchment_area_km2)    AS catchment_area_km2
    FROM intakes_systems AS i
    JOIN catchments_attributes AS c ON c.intake_code = i.intake_code
    GROUP BY i.system_id
) AS ca ON ca.system_id = y.system_id
ORDER BY ca.catchment_area_km2 DESC;
