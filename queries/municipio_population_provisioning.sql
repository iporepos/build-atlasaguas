-- Atlas Aguas T2: covered SURFACE population (2020) vs provisioning area, one row per municipality with a provisioning area.
-- Run in the QGIS DB Manager SQL window on the T2 GeoPackage (unique id column: municipio_code), or via plot_system_dispersion.py.
-- Surface share: sum of covered_percent of the municipality's systems_supply rows with intake_type 'Superficial'
--   (groundwater rows excluded; the shares of a municipality sum to 100).
-- Covered surface population = urban population 2020 x surface share / 100 x supply coverage 2020 / 100
--   (NULL where coverage is not reported; 0 where the Atlas gives no surface share although surface intakes are linked).
-- Urban population density: population_urban_per_km2 = urban population 2020 / provisioning area (for the population plot).
-- Region: first digit of the IBGE municipality code (1 Norte, 2 Nordeste, 3 Sudeste, 4 Sul, 5 Centro-Oeste).
-- Area: provisioning_areas.area_km2 (dissolve of the catchments; areas of municipalities sharing intakes overlap).
SELECT
    m.municipio_name || ' (' || m.unidade_alias || ')'                                      AS municipio_label,
    a.municipio_code,
    m.municipio_name,
    m.unidade_alias,
    CASE substr(a.municipio_code, 1, 1)
        WHEN '1' THEN 'Norte' WHEN '2' THEN 'Nordeste' WHEN '3' THEN 'Sudeste' WHEN '4' THEN 'Sul' WHEN '5' THEN 'Centro-Oeste'
    END                                                                                     AS regiao_name,
    a.area_km2                                                                              AS provisioning_area_km2,
    p.population_urban * sh.surface_percent / 100.0 * p.supply_coverage / 100.0             AS covered_surface_population_2020,
    p.population_urban * sh.surface_percent / 100.0 * p.supply_coverage / 100.0 / a.area_km2 AS covered_surface_population_per_km2,
    sh.surface_percent,
    p.population_urban                                                                      AS population_urban_2020,
    p.population_urban / a.area_km2                                                         AS population_urban_per_km2,
    p.supply_coverage                                                                       AS supply_coverage_2020,
    a.n_intakes_surface,
    a.n_parts,
    a.topology
FROM provisioning_areas AS a
JOIN municipios AS m
  ON m.municipio_code = a.municipio_code
LEFT JOIN municipios_indicators AS p
  ON p.municipio_code = a.municipio_code AND p.year = 2020
LEFT JOIN (
    SELECT
        municipio_code,
        SUM(CASE WHEN intake_type = 'Superficial' THEN covered_percent ELSE 0 END) AS surface_percent
    FROM systems_supply
    GROUP BY municipio_code
) AS sh ON sh.municipio_code = a.municipio_code
WHERE a.area_km2 IS NOT NULL
ORDER BY a.area_km2 DESC;
