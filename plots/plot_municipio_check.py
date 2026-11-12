#!/usr/bin/env python3
"""Check map of one municipality's supply: municipality polygon, linked intakes and their catchments (catchment revision).

Usage (project venv):  .venv/bin/python plots/plot_municipio_check.py --config plots/plot_municipio_check.local.json
                         [--municipio 4305108 4314902 | --municipio capitals.txt] [--skip-existing]

Batch: one JSON per assessment. `municipios` = a 7-digit IBGE code, a list of codes, or a text file (one code per line,
'#' comments and blank lines skipped, extra text after the code ignored), or a list mixing codes and files; relative
files resolve against the config. --municipio overrides it (files relative to the working directory). One map per code;
an error in one municipality is logged and the batch goes on (exit 1 at the end if any failed). skip_existing (config)
or --skip-existing leaves maps already drawn.

Reads the T2 GeoPackage (read-only). Intakes = those linked to the municipality by the view provisioning_links (direct
link or through the system, the same set that builds its provisioning area); catchments = theirs (surface intakes).
Frame = bounds of the municipality + the catchments + the linked intake points (plus margin); municipality parts farther
than part_max_distance_km (50) from its largest part (ocean islands, e.g. Trindade for Vitória) are left out of the frame.
Zoom mode ("zoom": "intakes", optional): a square centred on the linked intake points (side = the larger side of their
bounds, at least zoom_min_km, 10), joined with the municipality bounds (core parts) unless the municipality's larger
side is more than zoom_max_ratio (3) x the square side (then the square alone), plus a buffer of zoom_buffer (0.2) x the
larger side of that box on each side; everything else is drawn as usual (what falls outside is cut). No intake
points, or a zoom frame not smaller than the default one -> default frame. The frame grows on its short side to the map
box. Zoom mode also labels the surface intakes (intake_label: column or list of columns, default ["intake_name",
"intake_tradename"], joined as "name - tradename", the tradename left out when empty or equal to the name; the code
when all are empty) and the file name ends in _ZOOM (also when the default frame is kept).
Layers, bottom to top: ocean (optional), countries (optional, neighbours named), other municipalities (light gray, subtle borders), municipality (gray, stronger border),
urban areas (optional, dark red, no border),
water bodies (optional, light blue), catchments (light green, transparent: nested ones show darker),
drainage (optional), aqueducts (optional, T2 layer, magenta), municipal seats (diamonds, named), other intakes in the
frame (not linked; small, darker, no border; other_intakes true by default), linked intake points (surface blue,
groundwater orange, white border).
Page: A4 landscape. Map on the left (frame with 3-4 inward lat/long ticks, scale bar; the frame grows on its short side
to the map box), a 5 cm side panel on the right: code, name, view ("full view" or "zoom view"), operator, supply facts from T2
(urban population 2020, provisioning area, m2 per urban inhabitant, source mix, topology, upstream intakes), legend,
sources. Output: <output_folder>/<code>_<NAME>.jpeg (name upper case, no accents, spaces -> '-') at dpi.
Projection (key projection): "local" (default) Lambert azimuthal equal-area centred on the frame, "utm" (zone of the
municipality) or any CRS string.
Config keys: gpkg, municipios (old name municipio_code still read), output_folder. Relative paths resolve against the config file.
  Optional: minor_direct (true: a linked intake reached only by a direct link (provisioning_links link_source direct)
  in a municipality with supply shares, none for its systems, e.g. Imunana -> Rio (Paquetá): gray point "Minor direct
  intake", its catchment ignored, its point in the frame, not used for the relevant aqueducts; T2 unchanged),
  transfers (true: T2 layer catchments_transfers when present; rows whose target is a linked, not minor, intake, chains followed upstream, sources
  linked to the municipality left out, a polygon reached through two targets drawn once: "Transfer catchment" yellower
  green, solid olive edge, under the catchments; their source intakes "Transfer intake" purple points, labelled in
  zoom mode; both always in the legend, also with 0; catchments in the full frame, points in both frames), aqueducts (true or {"where", "color" (#d6198f magenta), "linewidth" (0.8), "full_view_alpha" (0.7: the light magenta of every line in the full view and of the non-relevant ones in zoom mode); "background_family" ("Operando": these light lines keep only the statuses of that family, i.e. Operando and Existente; null = every status; the side legend entry says "Aqueduct (operating)"); relevant systems: every line whose aqueduct_name has a line intersecting the municipality or passing within "intake_km" (2) of a linked intake point ("relevant" true; catchments not used: trunk lines cross large catchments far from the intakes); their whole extent is added to the frame in both modes ("extend_frame" true; zoom mode: after the zoom_buffer, with the default margin when they reach out of it); zoom mode: only the relevant systems get "split_zoom" (true: color family by status, Operando magenta-purple, Em Obras reds, Planejado yellow-orange; Existente drawn with the Operando family, Em Projeto / Em Estudo / Em Licitação / Emergencial with Planejado ("status_family" overrides), each with its own subheader; any other status gray ("status_palettes", "other_palette"); one tone per aqueduct name, counted over the family; "linewidth_zoom" 1.2; listed in the lower right corner of the map, status as subheader, names under it, "legend_rows" 4, names wrapped at "wrap" 40)}: T2 layer aqueducts, all
  statuses unless filtered), other_intakes (true: intakes in the frame not linked to the municipality, other_point_size
  10, colors surface_other / groundwater_other), ocean ({"path" (e.g. Natural Earth ne_10m_ocean.shp), "layer", "color" (#dce9f2, paler than the inland
  water bodies), "grow_km" (2: grown into land, hidden under the land layers, fills the gaps where the IBGE coast lies
  seaward of the 1:10m one), "credit"}: very bottom, no edge (the land layers draw the coast); clipped in the source
  CRS first),
  countries ({"path" (QGIS-style "file|layername=x" accepted) or "layer", "where", "label" (name column,
  e.g. SOVEREIGNT), "filter" (label values left out, e.g. ["Brazil"]: its municipalities are drawn), "color",
  "edgecolor", "linewidth" (0.5), "label_size" (7), "label_color", "label_min_fraction" (0.01: a name only when that
  much of the frame area is the country), "credit"}: deepest layer, below the municipalities), urban_areas ({"path" (QGIS-style "file|layername=x" accepted) or "layer", "where", "color" (#814446),
  "alpha" (1), "credit"}: no border, just above the municipality fills), water_bodies ({"path": polygon layer, QGIS-style "file.gpkg|layername=x" accepted, or "layer"; "where",
  "color" (light blue), "edgecolor", "linewidth" (0.2), "credit", "marine" ({"column" (tipomassadagua), "values"
  (["Baía", "Oceano", "Enseada"])}: those features drawn in the ocean color, no edge)}: inland water, drawn above the
  municipality fills, below the catchments), drainage ({"path": shp/gpkg (GDAL path, e.g. /vsizip/...zip/x.shp), "where": SQL filter such as
  "ORD_STRA >= 2", "linewidth": 0.25, "color": hex; "column": e.g. "UPLAND_SKM" -> color (cmap, default Blues, cut to
  cmap_range [0.35, 1]) and width (linewidth_range [0.2, 0.6]) scaled on the local min-max of the column in the frame
  ("scale": "linear" (default) or "log");
  declutter by map scale: "cut": {"column" (UPLAND_SKM), one of "min_spacing_mm" (area column: rivers about s mm apart on
  paper, threshold = area_factor (1) x (s x ground km per paper mm)^2; 4 mm calibrated), "value_ref" + "ref_km" (100) +
  "exponent" (2) (power law, any magnitude column), "table" [[frame_km, value], ...] + "interp" ("loglog" default,
  "loglin" for order columns)}: reaches below the threshold for the frame width are dropped;
  guard: the max_reaches largest kept (default 2000 without a cut, 0 = all with one), ties broken by tie_column (e.g.
  UPLAND_SKM; without it whole classes of the smallest values are dropped, the largest class kept whole);
  column absent or not found -> single color and linewidth; "credit": panel text}), dpi (300), jpeg_quality (92), margin (0.04 of the
  frame), part_max_distance_km (50), title_size (11, shrinks to fit the panel), point_size (32), point_edge (0.9, white border), point_ring (0.5 pt dark ring outside the white border, 0 = off), other intakes in light opaque colors (surface_other, groundwater_other: no transparency, close wells do not stack), seat_size (9), max_labels (20: seat names shown, own first, then by urban population 2020; every seat keeps its diamond; unlabelled ones smaller, seat_unlabelled_scale 0.55 of the area, and lighter), colors ({background, background_edge, seat, seat_unlabelled, municipio, municipio_edge, catchment, catchment_edge, surface, groundwater,
  drainage}), catchment_alpha (0.3), catchment_linewidth (0.7, edge #256b25), font ("default" = Fira Sans or "helvetica" =
  TeX Gyre Heros, a Helvetica clone: both shipped in plots/fonts, registered at start, same result on every platform;
  any installed family name also works; DejaVu Sans if not found), author (optional text, e.g. "Name (2026).
  Institution": shown above the credits, a little larger than them), version ("1.0.0": "Version: <v>", first credit line).
"""
import argparse
import json
import re
import sqlite3
import sys
import textwrap
import unicodedata
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import CRS, Transformer

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.transforms import ScaledTranslation  # noqa: E402

from plot_fonts import FONT_PRESETS  # noqa: E402,F401  (plots/plot_fonts.py: shipped fonts and presets)
from plot_fonts import set_font as _set_font  # noqa: E402


def set_font(family):
    _set_font(family, log)

REQUIRED = ["gpkg", "output_folder"]
COLORS = {"background": "#f1f0ec", "background_edge": "#c4c3be", "seat": "#3d3c39", "seat_unlabelled": "#9a9994",
          "municipio": "#d9d8d4", "municipio_edge": "#3d3c39", "catchment": "#7cc47c", "catchment_edge": "#256b25",
          "surface": "#0a58ca", "groundwater": "#f26b00", "drainage": "#3b78b0", "urban": "#814446", "water": "#b9dcf2", "water_edge": "#7fb3d5",
          "surface_other": "#8fb0d6", "groundwater_other": "#e3ad84", "aqueduct": "#d6198f", "intake_ring": "#1d1d1b", "minor": "#9a9994", "transfer": "#a8cf4a", "transfer_edge": "#5f8a1a", "transfer_intake": "#7b3fa0",
          "ocean": "#dce9f2", "country": "#e6e5e0", "country_edge": "#a9a8a3", "country_label": "#8f8e89","ink": "#0b0b0b", "ink2": "#52514e"}
CM = 1 / 2.54
# zoom mode aqueducts: the status is a hierarchy, each with its own color family (one tone per aqueduct name, cycled);
# statuses not listed here are gray. Legend order = this order, then the others alphabetically.
AQ_STATUS_PALETTES = {
    "Operando": ["#c2187a", "#8e24aa", "#e0479e", "#6a1b9a", "#d81b60", "#ab47bc"],   # magenta to purple
    "Em Obras": ["#d62828", "#9d0208", "#e85d5d", "#c1121f", "#f07167"],              # reds
    "Planejado": ["#e9b100", "#f59e0b", "#fb8500", "#f4c430", "#e76f00"],             # yellow to orange
}
AQ_OTHER_PALETTE = ["#8a8985", "#5f5e5a", "#a9a8a3", "#74736e"]                       # grays
# statuses drawn with another status's family (they keep their own legend subheader): "Existente" is the South's
# word for operating; the stages before construction go with Planejado. Legend order follows this dict.
AQ_STATUS_FAMILY = {"Operando": "Operando", "Existente": "Operando", "Em Obras": "Em Obras",
                    "Planejado": "Planejado", "Em Projeto": "Planejado", "Em Estudo": "Planejado",
                    "Em Licitação": "Planejado", "Emergencial": "Planejado"}


def log(m):
    print(m, flush=True)


def file_name(code, name, zoom=False):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    return f"{code}_{re.sub(r'[^A-Z0-9]+', '-', s).strip('-')}{'_ZOOM' if zoom else ''}.jpeg"


def sql_list(values):
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values)


def scale_bar(ax, x0, x1, y0, y1, color):
    """Scale bar (metres, projected CRS) in the lower left corner: about a fifth of the frame width, a round length."""
    target = (x1 - x0) / 5
    step = max(s * 10 ** e for e in range(0, 7) for s in (1, 2, 5) if s * 10 ** e <= target)
    bx, by = x0 + (x1 - x0) * 0.03, y0 + (y1 - y0) * 0.03
    ax.plot([bx, bx + step], [by, by], color=color, lw=1.2, solid_capstyle="butt", zorder=10)
    ax.text(bx + step / 2, by + (y1 - y0) * 0.008, f"{step / 1000:g} km" if step >= 1000 else f"{step:g} m",
            ha="center", va="bottom", fontsize=6, color=color, zorder=10)


PAGE = (29.7, 21.0)  # A4 landscape, cm
PANEL_W = 5.0  # right side panel, cm
MAP_BOX = (1.3, 1.0, PAGE[0] - PANEL_W - 1.3 - 0.4, PAGE[1] - 1.0 - 0.6)  # left, bottom, width, height (cm)


def draw(ax, g, **kw):
    """Plot a GeoDataFrame/GeoSeries; an empty one is skipped (geopandas hands it to pandas, which fails)."""
    if len(g):
        g.plot(ax=ax, **kw)


def cm_text(fig, x, y, s, **kw):
    """Text at (x, y) cm from the lower left corner of the page."""
    return fig.text(x / PAGE[0], y / PAGE[1], s, **kw)


def dense(poly, n=100):
    """The polygon with n points per edge: a straight frame edge is curved in lat/long, the corners alone miss the bulge."""
    return shapely.segmentize(poly, max(poly.length / 4 / n, 1e-9))


def core_parts(geom, crs, max_km):
    """The municipality without its remote parts (ocean islands such as Trindade for Vitória): parts farther than max_km
    from the largest part are dropped (distance in ESRI:102033). Returns (geometry, number of parts dropped)."""
    parts = list(shapely.get_parts(geom))
    if len(parts) < 2:
        return geom, 0
    m = gpd.GeoSeries(parts, crs=crs).to_crs("ESRI:102033")
    main = m.iloc[int(m.area.values.argmax())]
    keep = [p for p, q in zip(parts, m) if q.distance(main) <= max_km * 1000]
    return shapely.MultiPolygon(keep), len(parts) - len(keep)


def map_crs(spec, extent):
    """Projection of the map and its panel text. "local" (default): Lambert azimuthal equal-area centred on the bounds of
    the frame extent (smallest distortion at the centre, even in every direction, true areas; works for
    catchments spanning several UTM zones); "utm": UTM zone of the extent; anything else: a CRS (e.g. ESRI:102033)."""
    if spec == "utm":
        crs = extent.estimate_utm_crs()
        return crs, crs.name
    if spec != "local":
        crs = CRS.from_user_input(spec)
        return crs, crs.name
    x0, y0, x1, y1 = extent.to_crs(4326).total_bounds
    lon, lat = (x0 + x1) / 2, (y0 + y1) / 2
    crs = CRS.from_proj4(f"+proj=laea +lat_0={lat:.4f} +lon_0={lon:.4f} +datum=WGS84 +units=m +no_defs")
    return crs, f"Lambert azimuthal equal-area, WGS 84, centred at {abs(lat):.2f}°{'S' if lat < 0 else 'N'} {abs(lon):.2f}°{'W' if lon < 0 else 'E'}"


def read_in_frame(spec, base, frame, crs, clip=False):
    """Features of an optional layer inside the frame. spec: {"path", "layer" (optional), "where" (optional)}; the path
    may carry the layer QGIS-style ("file.gpkg|layername=x"); relative paths resolve against the config folder.
    clip: cut the geometries to the frame's bbox in the source CRS before reprojecting (huge features such as the
    global Natural Earth ocean polygon, which the local projection cannot take whole)."""
    path, layer = spec["path"], spec.get("layer")
    if "|layername=" in path:
        path, layer = path.split("|layername=", 1)
    path = path if path.startswith("/vsi") else str(base / path)
    bbox = gpd.GeoSeries([dense(frame)], crs=crs).to_crs(pyogrio.read_info(path, layer=layer)["crs"]).total_bounds
    # all columns: GDAL returns nothing when `where` runs with columns=[]
    gdf = pyogrio.read_dataframe(path, layer=layer, bbox=tuple(bbox), where=spec.get("where"))
    if clip and len(gdf):
        gdf = gdf.clip_by_rect(*bbox).to_frame("geometry").set_geometry("geometry", crs=gdf.crs)
        gdf = gdf[~gdf.is_empty]
    return gdf.to_crs(crs)


def cut_threshold(cut, width_km, map_mm):
    """Drainage cut: (minimum value of cut["column"] kept, description) for a frame width_km wide drawn map_mm wide.
    Forms, first match wins:
      table: [[frame_km, value], ...] interpolated on log(frame_km), value in log ("interp": "loglog", default; a
             2-row table is a power law) or linear ("loglin", for order columns such as ORD_STRA); end segments
             extended beyond the rows.
      min_spacing_mm (area columns, e.g. UPLAND_SKM in km2): rivers about s mm apart on paper ->
             value = area_factor (1) x (s x ground metres per paper mm / 1000)^2.
      value_ref + ref_km (100) + exponent (2): value = value_ref x (frame_km / ref_km)^exponent (any magnitude column)."""
    if "table" in cut:
        rows = sorted((float(a), float(b)) for a, b in cut["table"])
        if len(rows) < 2:
            raise ValueError("drainage.cut.table: at least 2 rows")
        xs = np.log([r[0] for r in rows])
        loglog = cut.get("interp", "loglog") == "loglog"
        ys = np.log([r[1] for r in rows]) if loglog else np.array([r[1] for r in rows])
        x = np.log(width_km)
        i = int(np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2))  # segment (end ones extended)
        y = ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])
        return (float(np.exp(y)) if loglog else float(y)), f"table ({cut.get('interp', 'loglog')})"
    if "min_spacing_mm" in cut:
        s = float(cut["min_spacing_mm"])
        ground_km = s * width_km / map_mm
        return float(cut.get("area_factor", 1)) * ground_km ** 2, f"spacing {s:g} mm = {ground_km:.2f} km on the ground"
    if "value_ref" in cut:
        e, ref = float(cut.get("exponent", 2)), float(cut.get("ref_km", 100))
        return float(cut["value_ref"]) * (width_km / ref) ** e, f"{cut['value_ref']:g} at {ref:g} km, exponent {e:g}"
    raise ValueError("drainage.cut: needs table, min_spacing_mm or value_ref")


def nice_ticks(lo, hi):
    """3 to 4 round values (degrees) inside [lo, hi]; fewer only when the span is tiny."""
    steps = [0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10]
    best = None
    for st in steps:
        v = np.arange(np.ceil(lo / st) * st, hi + 1e-12, st)
        if len(v) <= 4:
            best = (st, v)
            if len(v) >= 3:
                break
            if best is not None and len(v) < 2:
                break
    return best


def fmt_deg(v, st, pos, neg):
    dec = 0 if st >= 1 else (1 if st >= 0.1 and round(st * 10, 9) % 1 == 0 else (2 if st >= 0.01 else 3))
    return f"{abs(v):.{dec}f}°{neg if v < 0 else pos}"


def graticule(ax, crs, x0, x1, y0, y1, color):
    """Longitude ticks on the bottom/top edges, latitude ticks on the left/right edges (the frame is projected, so each
    tick sits where the meridian/parallel crosses that edge); ticks point inward, labels on the bottom and left."""
    to_ll = Transformer.from_crs(crs, 4326, always_xy=True)
    n = 400
    xs, ys = np.linspace(x0, x1, n), np.linspace(y0, y1, n)
    edges = {}
    for side, (ex, ey) in {"bottom": (xs, np.full(n, y0)), "top": (xs, np.full(n, y1)),
                           "left": (np.full(n, x0), ys), "right": (np.full(n, x1), ys)}.items():
        lon, lat = to_ll.transform(ex, ey)
        edges[side] = (lon, ex) if side in ("bottom", "top") else (lat, ey)
    lon_b = edges["bottom"][0]
    st, vals = nice_ticks(lon_b.min(), lon_b.max())
    lat_l = edges["left"][0]
    st2, vals2 = nice_ticks(lat_l.min(), lat_l.max())
    kw = dict(direction="in", length=4, width=0.6, color=color, labelsize=6, labelcolor=color)
    ax.set_xticks(np.interp(vals, *edges["bottom"]), [fmt_deg(v, st, "E", "W") for v in vals])
    ax.set_yticks(np.interp(vals2, *edges["left"]), [fmt_deg(v, st2, "N", "S") for v in vals2], rotation=90, va="center")
    ax.tick_params(**kw)
    top = ax.secondary_xaxis("top")
    top.set_xticks(np.interp(vals, *edges["top"]), [""] * len(vals))
    top.tick_params(**kw)
    right = ax.secondary_yaxis("right")
    right.set_yticks(np.interp(vals2, *edges["right"]), [""] * len(vals2))
    right.tick_params(**kw)
    for a_ in (top, right):
        for sp in a_.spines.values():
            sp.set_visible(False)


def subheader(fig, t, color, fontsize, handlelength=1.6, handletextpad=0.8):
    """Legend text as a group subheader: bold, dark, moved left over its empty handle (aligned with the symbols)."""
    t.set_fontweight("bold")
    t.set_color(color)
    dx = (handlelength + handletextpad) * fontsize / 72  # inches: the handle column plus the gap to the text
    t.set_transform(t.get_transform() + ScaledTranslation(-dx, 0, fig.dpi_scale_trans))


def side_panel(fig, gpkg, code, name, uf, proj_text, handles, col, cfg, view):
    """Right panel: municipality, supply facts from T2, legend, sources."""
    con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    q = lambda sql: con.execute(sql, (code,)).fetchone()  # noqa: E731
    mrow = q("SELECT area_km2, metropolitan_region_name, operator_name FROM municipios WHERE municipio_code = ?")
    pop = q("SELECT population_urban FROM municipios_indicators WHERE municipio_code = ? AND year = 2020")
    pa = q("SELECT source_mix, area_km2, topology, n_parts, n_intakes_surface_upstream FROM provisioning_areas WHERE municipio_code = ?")
    con.close()
    pop = pop[0] if pop else None
    x, w, y = PAGE[0] - PANEL_W, 32, PAGE[1] - 0.9
    ink, ink2 = col["ink"], col["ink2"]
    cm_text(fig, x, y, code, fontsize=9, color=ink2, va="top")
    y -= 0.5
    # title: 11 pt, wrapped; shrunk (down to 8 pt) if a line is still wider than the panel
    fs = cfg.get("title_size", 11)
    lines = textwrap.wrap(f"{name} ({uf})", 24)
    renderer = fig.canvas.get_renderer()
    while fs > 8:
        t = [cm_text(fig, x, y, ln, fontsize=fs, fontweight="bold") for ln in lines]
        wide = max(a_.get_window_extent(renderer).width for a_ in t) / fig.dpi * 2.54 > PANEL_W - 0.5
        for a_ in t:
            a_.remove()
        if not wide:
            break
        fs -= 0.5
    for line in lines:
        cm_text(fig, x, y, line, fontsize=fs, fontweight="bold", color=ink, va="top")
        y -= fs * 0.047
    cm_text(fig, x, y + 0.05, view, fontsize=8, style="italic", color=ink2, va="top")  # "full view" / "zoom view"
    y -= 0.5
    for label, val in (("Operator", mrow[2]),):
        if val:
            cm_text(fig, x, y, label, fontsize=6, color=ink2, va="top")
            y -= 0.3
            for line in textwrap.wrap(val, w):
                cm_text(fig, x, y, line, fontsize=7, color=ink, va="top")
                y -= 0.32
            y -= 0.15
    num = lambda v, f: "-" if v is None else f.format(v)  # noqa: E731
    area = pa[1] if pa else None
    facts = [("Municipality area", num(mrow[0], "{:,.1f} km²")),
             ("Urban population 2020", num(pop, "{:,.0f}")),
             ("Provisioning area", num(area, "{:,.1f} km²")),
             ("m² per urban inhabitant", num(area * 1e6 / pop if area and pop else None, "{:,.0f}")),
             ("Source mix", pa[0] if pa else "-"),
             ("Topology / parts", f"{pa[2] or '-'} / {pa[3] if pa and pa[3] is not None else '-'}" if pa else "-"),
             ("Upstream surface intakes", num(pa[4] if pa else None, "{:,.0f}"))]
    y -= 0.15
    for label, val in facts:
        cm_text(fig, x, y, label, fontsize=7, color=ink2, va="top")
        cm_text(fig, PAGE[0] - 0.5, y, val, fontsize=7, color=ink, va="top", ha="right")
        y -= 0.4
    y -= 0.3
    lg = fig.legend(handles=handles, loc="upper left", bbox_to_anchor=((x - 0.15) / PAGE[0], y / PAGE[1]), fontsize=7,
                    frameon=False, borderaxespad=0, handlelength=1.6, labelspacing=0.7, labelcolor=ink)
    for h, t in zip(handles, lg.get_texts()):
        if getattr(h, "subheader", False):  # e.g. "Intakes": its entries below it
            subheader(fig, t, ink, 7)
    foot = [f"Version: {cfg.get('version', '1.0.0')}", f"Data: ANA Atlas Águas 2021 (T2)", f"Intakes: provisioning_links of {code}"]
    if cfg.get("drainage"):
        foot.append(cfg["drainage"].get("credit", "Drainage: HydroRIVERS v1.0"))
    if cfg.get("ocean"):
        foot.append(cfg["ocean"].get("credit", "Ocean: Natural Earth 1:10m"))
    if cfg.get("countries"):
        foot.append(cfg["countries"].get("credit", "Countries: Natural Earth 1:10m"))
    if cfg.get("urban_areas"):
        foot.append(cfg["urban_areas"].get("credit", "Urban areas: IBGE BC250"))
    if cfg.get("water_bodies"):
        foot.append(cfg["water_bodies"].get("credit", "Water bodies: IBGE BC250"))
    foot += textwrap.wrap(f"Projection: {proj_text}", 48)
    yy = MAP_BOX[1]
    for line in reversed(foot):
        cm_text(fig, x, yy, line, fontsize=5.5, color=ink2, va="bottom")
        yy += 0.3
    if cfg.get("author"):  # above the credits, a little larger and darker
        yy += 0.1
        for line in reversed(textwrap.wrap(str(cfg["author"]), 42)):
            cm_text(fig, x, yy, line, fontsize=6.5, color=ink, va="bottom")
            yy += 0.35


def plot_one(code, cfg, cpath, gpkg, out_dir, col):
    """One map: <out_dir>/<code>_<NAME>.jpeg."""
    mun = pyogrio.read_dataframe(gpkg, layer="municipios", where=f"municipio_code = {sql_list([code])}")
    if len(mun) != 1:
        raise ValueError(f"municipio {code} not found")
    name, uf = mun.municipio_name.iloc[0], mun.unidade_alias.iloc[0]
    con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    links = dict(con.execute("SELECT intake_code, link_source FROM provisioning_links WHERE municipio_code = ?", (code,)).fetchall())
    # minor direct intakes: linked only through the intake's own municipality list (link_source direct) while the
    # municipality has supply shares (systems_supply covered_percent > 0), none for this intake's systems (e.g. Imunana
    # -> Rio de Janeiro: the Paquetá supply). Plot only (T2 unchanged): gray point, no catchment, left out of the frame
    # and of the relevant-aqueduct search
    minor = set()
    if cfg.get("minor_direct", True) and con.execute(
            "SELECT 1 FROM systems_supply WHERE municipio_code = ? AND covered_percent > 0", (code,)).fetchone():
        minor = {c for c, s_ in links.items() if s_ == "direct"}
    con.close()
    itk = pyogrio.read_dataframe(gpkg, layer="intakes", where=f"intake_code IN ({sql_list(links) or 'NULL'})")
    cat = pyogrio.read_dataframe(gpkg, layer="catchments", where=f"intake_code IN ({sql_list(links) or 'NULL'})")
    itk_minor = itk[itk.intake_code.isin(minor)]
    itk, cat = itk[~itk.intake_code.isin(minor)], cat[~cat.intake_code.isin(minor)]
    n_s, n_g = int((itk.intake_type == "Superficial").sum()), int((itk.intake_type == "Subterrânea").sum())
    log(f"{code} {name} ({uf}): {len(links)} linked intakes ({n_s} surface, {n_g} groundwater, {len(itk_minor)} minor direct), "
        f"{len(cat)} catchments" + (f"; minor direct (no share, catchment ignored): {', '.join(itk_minor.intake_code)}" if len(itk_minor) else ""))
    # transfers (T2 layer catchments_transfers, when the database has it): rows whose target (intake_code) is a linked,
    # not minor, intake, chains followed upstream (a row also counts when its target is the source of a row already
    # reached; same rule as build_database.transfer_closure); sources already linked to the municipality are left out (their catchment is drawn already); a
    # polygon reached through two targets is drawn once (by source intake; drawn polygons by identical geometry).
    # Transfer intakes = the source intakes of case A (catchments_only and drawn polygons have none)
    trc, itk_tr = cat.iloc[:0], itk.iloc[:0]
    if cfg.get("transfers", True) and "catchments_transfers" in set(pyogrio.list_layers(gpkg)[:, 0]):
        tr = pyogrio.read_dataframe(gpkg, layer="catchments_transfers")  # small layer: read whole, chains followed here
        seen, front, keep = set(itk.intake_code), list(itk.intake_code), set()
        while front:
            hit = tr[tr.intake_code.isin(front) & ~tr.index.isin(keep)]
            keep |= set(hit.index)
            front = [c for c in hit.source_intake_code.dropna().unique() if c not in seen]
            seen |= set(front)
        tr = tr.loc[sorted(keep)]
        tr = tr[~tr.source_intake_code.isin(itk.intake_code)]
        key = pd.Series([v if isinstance(v, str) else shapely.normalize(g).wkb for v, g in zip(tr.source_intake_code, tr.geometry)], index=tr.index)
        trc = tr[~key.duplicated()]
        is_a = trc.transfer_type == "intake" if "transfer_type" in trc.columns else trc.source_intake_code.notna()
        src = sorted(set(trc.source_intake_code[is_a].dropna()) - set(links))  # case A only: case C has no relevant intake
        itk_tr = pyogrio.read_dataframe(gpkg, layer="intakes", where=f"intake_code IN ({sql_list(src) or 'NULL'})")
        log(f"  transfers: {len(trc)} transfer catchments ({int((~is_a).sum())} without a source intake: catchments_only or drawn), "
            f"{len(itk_tr)} transfer intakes")

    core, dropped = core_parts(mun.geometry.iloc[0], mun.crs, cfg.get("part_max_distance_km", 50))
    if dropped:
        log(f"  municipality: {dropped} remote polygon part(s) left out of the frame (> {cfg.get('part_max_distance_km', 50)} km from the main part)")
    zoom = cfg.get("zoom")
    if zoom not in (None, "intakes"):
        raise ValueError(f"zoom {zoom!r}: only \"intakes\" (or absent)")
    zoom_mode = zoom == "intakes"  # file name suffix and intake labels, even if the default frame is kept
    # frame points: linked, minor direct and transfer intakes
    pts = pd.concat([itk.geometry, itk_minor.geometry, itk_tr.geometry.to_crs(itk.crs)]).dropna()
    if zoom == "intakes" and not len(pts):
        log("  zoom intakes: no intake points, default frame")
        zoom = None
    # relevant aqueduct systems: every line whose name (system) has a line intersecting the municipality or passing
    # within intake_km (2) of a linked intake point (catchments are not used: regional trunk lines cross large catchments
    # far from the intakes); their whole extent goes into the frame (both modes); colors + map legend in zoom mode
    aq_cfg = cfg["aqueducts"] if isinstance(cfg.get("aqueducts"), dict) else {}
    rel_names, rel_geoms = set(), []
    if cfg.get("aqueducts") and aq_cfg.get("relevant", True):
        aq_all = pyogrio.read_dataframe(gpkg, layer="aqueducts", where=aq_cfg.get("where")).to_crs(mun.crs)
        hit = aq_all.intersects(mun.geometry.iloc[0])
        if len(itk.geometry.dropna()):
            near = itk.geometry.dropna().to_crs("ESRI:102033").buffer(aq_cfg.get("intake_km", 2) * 1000).union_all()
            hit |= aq_all.to_crs("ESRI:102033").intersects(near).values
        rel_names = set(aq_all.aqueduct_name[hit].dropna())
        rel = aq_all[aq_all.aqueduct_name.isin(rel_names)]
        if aq_cfg.get("extend_frame", True):
            rel_geoms = list(rel.geometry.dropna())
        if len(rel):
            log(f"  relevant aqueducts: {len(rel_names)} systems ({len(rel)} lines): {', '.join(sorted(rel_names))}")

    def make_frame(geoms, square, extra=()):
        """(crs, projection text, frame bounds grown to the map box aspect) for an extent; square = zoom mode, where
        geoms = [municipality core] + intake points; extra = geometries whose bounds are added before the buffer
        (relevant aqueducts)."""
        ext = gpd.GeoSeries(list(geoms) + list(extra), crs=mun.crs)
        crs_, text_ = map_crs(cfg.get("projection", "local"), ext)
        a0, b0, a1, b1 = ext.to_crs(crs_).total_bounds
        if square:
            # square on the intake points (side = their larger side, centred); union with the municipality bounds
            # unless the municipality's larger side is more than zoom_max_ratio (3) x the square side (large
            # municipality, clustered intakes: the square alone, at least zoom_min_km wide, e.g. a single intake);
            # then a buffer of zoom_buffer (0.2) x the larger side of the box on each side
            p0, q0, p1, q1 = gpd.GeoSeries(geoms[1:], crs=mun.crs).to_crs(crs_).total_bounds
            m0, n0, m1, n1 = gpd.GeoSeries(geoms[:1], crs=mun.crs).to_crs(crs_).total_bounds
            side, cx, cy = max(p1 - p0, q1 - q0), (p0 + p1) / 2, (q0 + q1) / 2
            ratio = max(m1 - m0, n1 - n0) / side if side else float("inf")
            if ratio > cfg.get("zoom_max_ratio", 3):
                side = max(side, cfg.get("zoom_min_km", 10) * 1000)
                a0, b0, a1, b1 = cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2
                log(f"  zoom intakes: municipality {ratio:.1f}x the intake square, intakes only")
            else:
                a0, b0 = min(m0, cx - side / 2), min(n0, cy - side / 2)
                a1, b1 = max(m1, cx + side / 2), max(n1, cy + side / 2)
            m = cfg.get("zoom_buffer", 0.2) * max(a1 - a0, b1 - b0)
            a0, b0, a1, b1 = a0 - m, b0 - m, a1 + m, b1 + m
            m = 0
            if len(extra):  # relevant aqueducts after the buffer, with the default margin only
                e0, f0, e1, f1 = gpd.GeoSeries(list(extra), crs=mun.crs).to_crs(crs_).total_bounds
                if e0 < a0 or f0 < b0 or e1 > a1 or f1 > b1:
                    a0, b0, a1, b1 = min(a0, e0), min(b0, f0), max(a1, e1), max(b1, f1)
                    m = cfg.get("margin", 0.04) * max(a1 - a0, b1 - b0)
        else:
            m = cfg.get("margin", 0.04) * max(a1 - a0, b1 - b0)
        a0, b0, a1, b1 = a0 - m, b0 - m, a1 + m, b1 + m
        # grow the short side (centered) to the aspect of the map box
        r = MAP_BOX[3] / MAP_BOX[2]
        if (b1 - b0) / (a1 - a0) < r:
            g = ((a1 - a0) * r - (b1 - b0)) / 2
            b0, b1 = b0 - g, b1 + g
        else:
            g = ((b1 - b0) / r - (a1 - a0)) / 2
            a0, a1 = a0 - g, a1 + g
        return crs_, text_, (a0, b0, a1, b1)

    normal = make_frame([core] + list(cat.geometry) + list(trc.geometry.to_crs(mun.crs)) + list(pts), False, rel_geoms)
    crs, proj_text, (x0, y0, x1, y1) = normal
    view = "zoom view" if zoom_mode else "full view"  # the mode, also when a zoom run keeps the default frame
    if zoom:
        zc, zt, zb = make_frame([core] + list(pts), True, rel_geoms)
        area = lambda b: (b[2] - b[0]) * (b[3] - b[1]) / 1e6  # noqa: E731 (both projections are equal-area)
        if area(zb) < area(normal[2]):
            crs, proj_text, (x0, y0, x1, y1) = zc, zt, zb
            log(f"  zoom intakes: frame {(zb[2] - zb[0]) / 1000:.1f} x {(zb[3] - zb[1]) / 1000:.1f} km")
        else:
            log(f"  zoom intakes: frame {area(zb):,.0f} km2 not smaller than the default ({area(normal[2]):,.0f} km2), default kept")
    label_intakes = zoom_mode  # intake labels only in zoom mode: the full view stays clean
    mun, itk, cat, itk_minor = mun.to_crs(crs), itk.to_crs(crs), cat.to_crs(crs), itk_minor.to_crs(crs)
    trc, itk_tr = trc.to_crs(crs), itk_tr.to_crs(crs)
    frame = shapely.box(x0, y0, x1, y1)
    bbox_ll = tuple(gpd.GeoSeries([dense(frame)], crs=crs).to_crs(pyogrio.read_info(gpkg, layer="municipios")["crs"]).total_bounds)
    bg = pyogrio.read_dataframe(gpkg, layer="municipios", bbox=bbox_ll, columns=["municipio_code", "municipio_name"]).to_crs(crs)
    seats = pyogrio.read_dataframe(gpkg, layer="municipios_sedes", bbox=bbox_ll, columns=["municipio_code"]).to_crs(crs)
    seats = seats.merge(bg[["municipio_code", "municipio_name"]], on="municipio_code", how="left")
    seats = seats[seats.intersects(frame)]
    # context from T2: the other intakes in the frame (not linked to this municipality) and the aqueducts
    others = None
    if cfg.get("other_intakes", True):
        others = read_in_frame({"path": str(gpkg), "layer": "intakes"}, cpath.parent, frame, crs)
        others = others[~others.intake_code.isin(links) & ~others.intake_code.isin(itk_tr.intake_code) & others.intersects(frame)]
        log(f"  other intakes: {len(others)} in the frame")
    aq = None
    if cfg.get("aqueducts"):
        aq = read_in_frame({"path": str(gpkg), "layer": "aqueducts", **aq_cfg}, cpath.parent, frame, crs)
        log(f"  aqueducts: {len(aq)} in the frame")
    # name labels: at most max_labels, the municipality itself first, then by urban population 2020 (largest first)
    con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    pop = dict(con.execute(f"SELECT municipio_code, population_urban FROM municipios_indicators WHERE year = 2020 "
                           f"AND municipio_code IN ({sql_list(seats.municipio_code) or 'NULL'})").fetchall())
    con.close()
    seats = seats.assign(_own=seats.municipio_code == code, _pop=seats.municipio_code.map(pop).fillna(0))
    seats = seats.sort_values(["_own", "_pop"], ascending=False)
    n_lab = int(cfg.get("max_labels", 20))
    seats["_label"] = [i < n_lab for i in range(len(seats))]
    if len(seats) > n_lab:
        log(f"  seats: {len(seats)} in the frame, {n_lab} labelled (by urban population 2020)")
    out = itk[~itk.intersects(frame)]
    if len(out):
        log(f"  {len(out)} intake points outside the frame (not drawn): {', '.join(out.intake_code)}")

    ocean = None
    if cfg.get("ocean"):
        ocean = read_in_frame(cfg["ocean"], cpath.parent, frame, crs, clip=True)
        grow = float(cfg["ocean"].get("grow_km", 2))
        if grow and len(ocean):
            # grown into land: hidden under the land layers drawn above, fills the gaps where the detailed IBGE coast
            # lies seaward of the coarse 1:10m one
            ocean = ocean.set_geometry(ocean.buffer(grow * 1000, quad_segs=2).intersection(frame))
        log(f"  ocean: {'in the frame' if len(ocean) else 'none in the frame'} (grown {grow:g} km)")
    countries = None
    if cfg.get("countries"):
        cs = cfg["countries"]
        countries = read_in_frame(cs, cpath.parent, frame, crs)
        lab = cs.get("label")
        if cs.get("filter"):  # values of the label column left out (e.g. Brazil: its municipalities are drawn)
            if lab not in countries.columns:
                raise ValueError(f"countries.filter needs countries.label (a column), got {lab!r}")
            countries = countries[~countries[lab].isin(cs["filter"])]
        log(f"  countries: {len(countries)} in the frame")
    drain = water = None
    if cfg.get("drainage"):
        drain = read_in_frame(cfg["drainage"], cpath.parent, frame, crs)
        log(f"  drainage: {len(drain)} lines in the frame")
    urban = None
    if cfg.get("urban_areas"):
        urban = read_in_frame(cfg["urban_areas"], cpath.parent, frame, crs)
        log(f"  urban areas: {len(urban)} polygons in the frame")
    if cfg.get("water_bodies"):
        water = read_in_frame(cfg["water_bodies"], cpath.parent, frame, crs)
        log(f"  water bodies: {len(water)} polygons in the frame")

    fig = plt.figure(figsize=(PAGE[0] * CM, PAGE[1] * CM))
    ax = fig.add_axes([MAP_BOX[0] / PAGE[0], MAP_BOX[1] / PAGE[1], MAP_BOX[2] / PAGE[0], MAP_BOX[3] / PAGE[1]])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    for sp in ax.spines.values():
        sp.set_color(col["ink"])
        sp.set_linewidth(0.8)
    graticule(ax, crs, x0, x1, y0, y1, col["ink2"])
    oc = cfg.get("ocean") or {}
    oc_color = oc.get("color", col["ocean"])
    if ocean is not None and len(ocean):  # bottom: the land layers (municipalities, countries) draw the coastline
        draw(ax, ocean, color=oc_color, linewidth=0, zorder=-2)
    if countries is not None and len(countries):  # deepest layer: neighbour countries, names in light italic caps
        cs = cfg["countries"]
        draw(ax, countries, color=cs.get("color", col["country"]), edgecolor=cs.get("edgecolor", col["country_edge"]),
             linewidth=cs.get("linewidth", 0.5), zorder=-1)
        lab = cs.get("label")
        if lab in countries.columns:
            fa = frame.area
            for c_name, g in zip(countries[lab], countries.geometry):
                part = g.intersection(frame)
                if part.is_empty or part.area < cs.get("label_min_fraction", 0.01) * fa:
                    continue  # too little of the country in the frame for a name
                p = part.representative_point()
                ax.text(p.x, p.y, str(c_name).upper(), fontsize=cs.get("label_size", 7), style="italic",
                        color=cs.get("label_color", col["country_label"]), ha="center", va="center", zorder=-0.5,
                        clip_on=True)
    draw(ax, bg[bg.municipio_code != code], color=col["background"], edgecolor=col["background_edge"], linewidth=0.3, zorder=0)
    draw(ax, mun, color=col["municipio"], linewidth=0, zorder=1)
    draw(ax, mun.boundary, color=col["municipio_edge"], linewidth=0.9, zorder=2.7)  # above the catchments
    ua = cfg.get("urban_areas") or {}
    ua_color = ua.get("color", col["urban"])
    if urban is not None and len(urban):  # just above the municipality fills, no border
        draw(ax, urban, color=ua_color, alpha=ua.get("alpha", 1), linewidth=0, zorder=1.2)
    wb = cfg.get("water_bodies") or {}
    wb_color, wb_edge = wb.get("color", col["water"]), wb.get("edgecolor", col["water_edge"])
    marine = None
    if water is not None and len(water) and wb.get("marine"):
        # marine features of the water layer (e.g. BC250 bays) in the ocean color, at the same level (they cover the
        # municipality fills that reach into the bays), no edge, like the ocean
        mc, mv = wb["marine"].get("column", "tipomassadagua"), wb["marine"].get("values", ["Baía", "Oceano", "Enseada"])
        if mc not in water.columns:
            raise ValueError(f"water_bodies.marine.column {mc} not in the water bodies layer")
        is_m = water[mc].isin(mv)
        marine, water = water[is_m], water[~is_m]
        draw(ax, marine, color=oc_color, linewidth=0, zorder=1.5)
    if water is not None and len(water):  # above the municipality fills, below the catchments (seen through them)
        draw(ax, water, color=wb_color, edgecolor=wb_edge, linewidth=wb.get("linewidth", 0.2), zorder=1.5)
    alpha = cfg.get("catchment_alpha", 0.3)
    if len(trc):  # transfer catchments: yellower green, under the municipality's own catchments
        draw(ax, trc, color=col["transfer"], alpha=alpha + 0.1, linewidth=0, zorder=1.9)
        draw(ax, trc.boundary, color=col["transfer_edge"], linewidth=cfg.get("catchment_linewidth", 0.7), zorder=1.95)
    if len(cat):
        draw(ax, cat, color=col["catchment"], alpha=alpha, linewidth=0, zorder=2)
        draw(ax, cat.boundary, color=col["catchment_edge"], linewidth=cfg.get("catchment_linewidth", 0.7), zorder=2.5)
    drain_color = cfg.get("drainage", {}).get("color", col["drainage"])
    if drain is not None and len(drain):
        d = cfg["drainage"]
        c_ = d.get("column")
        if c_ and c_ not in drain.columns:
            log(f"  drainage: column {c_} not found, single color and width")
        if c_ and c_ in drain.columns and drain[c_].notna().any():
            # declutter, 1) cut (scale-dependent tail): reaches with cut.column below a threshold that grows with the
            # frame width are dropped (cut_threshold); 2) guard: keep the max_reaches largest by column (0 = all;
            # default 2000 without a cut, 0 with one). Ties (stream orders are classes) are broken by tie_column
            # (e.g. UPLAND_SKM); without it whole classes are dropped (the largest class kept whole). Color and width
            # are scaled on the min-max of ALL reaches in the frame (before any cut: main rivers stay dark and thick on
            # large maps), linearly or on log ("scale": "log", positive values); missing values count as the minimum
            v = drain[c_].astype(float).fillna(drain[c_].min())
            if d.get("scale", "linear") == "log":
                v = np.log10(v.clip(lower=v[v > 0].min() if (v > 0).any() else 1))
            lo, hi = v.min(), v.max()
            n0, cut = len(drain), d.get("cut")
            cap, tie = int(d.get("max_reaches", 0 if cut else 2000)), d.get("tie_column")
            cut_msg = ""
            if cut:
                cc = cut.get("column", "UPLAND_SKM")
                if cc not in drain.columns:
                    raise ValueError(f"drainage.cut.column {cc} not in the drainage layer")
                thr, how = cut_threshold(cut, (x1 - x0) / 1000, MAP_BOX[2] * 10)
                keep = (drain[cc].astype(float) >= thr).values
                if not keep.any():  # never an empty map: keep the largest reach
                    keep = (drain[cc].astype(float) >= drain[cc].max()).values
                drain, v = drain[keep], v[keep]
                cut_msg = f", cut {cc} >= {thr:,.4g} ({how})"
            if cap and len(drain) > cap:
                if tie and tie in drain.columns:
                    order = np.lexsort((-drain[tie].astype(float).fillna(0).values, -v.values))  # by v, then tie, descending
                    keep = np.zeros(len(drain), bool)
                    keep[order[:cap]] = True
                else:
                    desc = np.sort(v.values)[::-1]
                    thr = desc[cap - 1]
                    keep = (v >= thr if (v >= thr).sum() <= cap else v > thr).values
                    if not keep.any():
                        keep = (v >= desc[0]).values
                drain, v = drain[keep], v[keep]
            t = (v - lo) / (hi - lo) if hi > lo else v * 0 + 1
            c0, c1 = d.get("cmap_range", [0.35, 1.0])
            w0, w1 = d.get("linewidth_range", [0.2, 0.6])
            cmap = matplotlib.colormaps[d.get("cmap", "Blues")]
            drain = drain.assign(_t=t.values, _c=[cmap(c0 + (c1 - c0) * x) for x in t]).sort_values("_t")  # larger rivers on top
            draw(ax, drain, color=list(drain._c), linewidth=list(w0 + (w1 - w0) * drain._t), zorder=3)
            drain_color = cmap(c0 + (c1 - c0) * 0.6)
            log(f"  drainage: {len(drain)} of {n0} reaches kept (frame {(x1 - x0) / 1000:,.1f} km{cut_msg}, max_reaches {cap}), "
                f"{c_}{' (log10)' if d.get('scale') == 'log' else ''} scaled on {lo:g}-{hi:g}")
        else:
            draw(ax, drain, color=drain_color, linewidth=d.get("linewidth", 0.25), zorder=3)
    aq_color = aq_cfg.get("color", col["aqueduct"])
    aq_alpha = aq_cfg.get("full_view_alpha", 0.7)  # light magenta: every line in the full view, the non-relevant in zoom
    aq_groups = zoom_mode and aq is not None and aq.aqueduct_name.isin(rel_names).any() and aq_cfg.get("split_zoom", True)
    # status -> color family (Existente is Operando, the stages before construction are Planejado)
    fam = {**AQ_STATUS_FAMILY, **{s: s for s in aq_cfg.get("status_palettes", {})}, **aq_cfg.get("status_family", {})}
    bg_family = aq_cfg.get("background_family", "Operando")
    if aq is not None and len(aq):  # above the drainage, below the seats
        plain = aq[~aq.aqueduct_name.isin(rel_names)] if aq_groups else aq
        if bg_family:  # light background lines (full view; non-relevant in zoom mode): one status family only
            n0 = len(plain)
            plain = plain[plain.aqueduct_status.map(fam).eq(bg_family)]
            log(f"  aqueducts in the background: {len(plain)} of {n0} lines ({bg_family} family)")
        draw(ax, plain, color=aq_color, alpha=aq_alpha, linewidth=aq_cfg.get("linewidth", 0.8), zorder=3.2)
    if aq_groups:
        aq = aq[aq.aqueduct_name.isin(rel_names)]  # relevant systems only: colored, listed on the map
        # zoom mode: the status is a hierarchy with its own color family (Operando magenta-purple, Em Obras reds,
        # Planejado yellow-orange, the others grays), one tone per aqueduct name within it (cycled). List in the
        # lower right corner of the map: status as a bold subheader, the names under it; 4 rows, columns as needed
        # (filled down; a subheader never ends a column)
        pals = {**AQ_STATUS_PALETTES, **aq_cfg.get("status_palettes", {})}
        other_pal = aq_cfg.get("other_palette", AQ_OTHER_PALETTE)
        lw, rows, wrap = aq_cfg.get("linewidth_zoom", 1.2), int(aq_cfg.get("legend_rows", 4)), aq_cfg.get("wrap", 40)
        st = aq.aqueduct_status.fillna("Unknown").astype(str)
        nm = aq.aqueduct_name.fillna("?").astype(str)
        statuses = [s for s in fam if (st == s).any()] + sorted(set(st) - set(fam))
        blank = lambda: Line2D([], [], color="none", label="")  # noqa: E731
        aq_handles, heads, used = [], [], {}
        for s in statuses:
            if len(aq_handles) % rows == rows - 1:  # the subheader would end a column: start the next one
                aq_handles.append(blank())
            heads.append(len(aq_handles))
            aq_handles.append(Line2D([], [], color="none", label=s))
            f = fam.get(s)
            pal = pals.get(f, other_pal)
            for n in sorted(set(nm[st == s])):
                i = used[f] = used.get(f, -1) + 1  # shade counted over the family (Operando + Existente differ)
                c = pal[i % len(pal)]
                draw(ax, aq[(st == s) & (nm == n)], color=c, linewidth=lw, zorder=3.25)
                aq_handles.append(Line2D([], [], color=c, lw=lw + 0.3, label="\n".join(textwrap.wrap(n, wrap))))
        lg = ax.legend(handles=aq_handles, loc="lower right", ncol=-(-len(aq_handles) // rows), fontsize=5.5,
                       title="Aqueducts", title_fontsize=6.5, alignment="left", frameon=True,
                       framealpha=0.9, facecolor="white", edgecolor=col["ink2"], fancybox=False, borderpad=0.5,
                       handlelength=1.6, columnspacing=1.2, labelspacing=0.5)
        lg.get_title().set_fontweight("bold")
        for i in heads:  # status subheaders: bold, dark, pulled left over the empty handle
            subheader(fig, lg.get_texts()[i], col["ink"], 5.5)
        lg.get_frame().set_linewidth(0.4)
        lg.set_zorder(6)
    halo = [patheffects.withStroke(linewidth=1.6, foreground="white")]
    ss = cfg.get("seat_size", 9)
    unl = seats[~seats._label]  # seats without a name label: smaller, lighter
    if len(unl):
        draw(ax, unl, marker="D", color=col["seat_unlabelled"], markersize=ss * cfg.get("seat_unlabelled_scale", 0.55),
                 edgecolor="white", linewidth=0.2, zorder=3.4)
    draw(ax, seats[seats._label], marker="D", color=col["seat"], markersize=ss, edgecolor="white", linewidth=0.3, zorder=3.5)
    for r in seats[seats._label].itertuples():
        own = r.municipio_code == code
        ax.annotate(r.municipio_name or r.municipio_code, (r.geometry.x, r.geometry.y), xytext=(3.5, 2.5), textcoords="offset points",
                    fontsize=6.5 if own else 5.5, fontweight="bold" if own else "normal", color=col["ink"] if own else col["seat"],
                    path_effects=halo, zorder=3.6, annotation_clip=True, clip_on=True)  # under the intakes
    ps, pe, ring = cfg.get("point_size", 32), cfg.get("point_edge", 0.9), cfg.get("point_ring", 0.5)
    if others is not None and len(others):  # other intakes: small, light, no border, above the aqueducts, under the seats
        for typ, c in (("Subterrânea", col["groundwater_other"]), ("Superficial", col["surface_other"])):
            g = others[others.intake_type == typ]
            if len(g):
                draw(ax, g, color=c, markersize=cfg.get("other_point_size", 10), linewidth=0, zorder=3.3)  # under the seats
    for typ, c, g in (("minor", col["minor"], itk_minor), ("transfer", col["transfer_intake"], itk_tr), ("Subterrânea", col["groundwater"], None), ("Superficial", col["surface"], None)):
        g = itk[itk.intake_type == typ] if g is None else g  # minor direct intakes: gray, under the linked ones
        if len(g):
            if ring:  # thin dark ring outside the white border: the edge is centred on the outline, so a thicker
                # dark edge drawn first shows `ring` pt outside the white one
                draw(ax, g, color=c, markersize=ps, edgecolor=col["intake_ring"], linewidth=pe + 2 * ring, zorder=3.95)
            draw(ax, g, color=c, markersize=ps, edgecolor="white", linewidth=pe, zorder=4)
    if label_intakes:
        # surface intakes labelled: intake_label columns (default intake_name, intake_tradename) joined by " - ",
        # empty and repeated values dropped (name only when the tradename is the same); the code when all are empty
        lc = cfg.get("intake_label", ["intake_name", "intake_tradename"])
        lc = [c for c in ([lc] if isinstance(lc, str) else lc) if c in itk.columns]
        lab = pd.concat([itk_minor, itk_tr, itk])  # one neutral label color for every kind (the point says the kind)
        for r in lab[(lab.intake_type == "Superficial") & lab.geometry.notna()].itertuples():
            parts = []
            for c in lc:
                v = getattr(r, c)
                v = v.strip() if isinstance(v, str) else ""
                if v and v.casefold() not in (x.casefold() for x in parts):
                    parts.append(v)
            p = r.geometry.centroid  # intakes are MultiPoint (one point each)
            ax.annotate(" - ".join(parts) or r.intake_code, (p.x, p.y),
                        xytext=(4.5, -3.5), textcoords="offset points", fontsize=5.5, color=col["ink"],
                        fontweight="bold", va="top", path_effects=halo, zorder=4.1, annotation_clip=True, clip_on=True)
    scale_bar(ax, x0, x1, y0, y1, col["ink2"])
    ax.set_xlabel("")
    ax.set_ylabel("")  # geopandas labels projected axes (Easting/Northing); the ticks are lat/long

    # intakes under an "Intakes" subheader; transfer and minor always listed (also with 0), others without counts
    big = dict(marker="o", ls="", mec=col["intake_ring"], mew=0.6, ms=7.5)
    head = Line2D([], [], color="none", label="Intakes")
    head.subheader = True  # bold, gray (side_panel)
    handles = [head,
               Line2D([], [], color=col["surface"], label=f"Surface ({n_s})", **big),
               Line2D([], [], color=col["transfer_intake"], label=f"Surface - transfer ({len(itk_tr)})", **big),
               Line2D([], [], color=col["minor"], label=f"Surface - minor ({len(itk_minor)})", **big),
               Line2D([], [], color=col["groundwater"], label=f"Groundwater ({n_g})", **big)]
    if others is not None:
        handles += [Line2D([], [], marker="o", ls="", color=col["surface_other"], mew=0, ms=3.6, label="Surface (others)"),
                    Line2D([], [], marker="o", ls="", color=col["groundwater_other"], mew=0, ms=3.6, label="Groundwater (others)")]
    handles.append(Line2D([], [], color="none", label=" "))  # spacer: ends the intakes group
    head = Line2D([], [], color="none", label="Catchments")
    head.subheader = True
    handles += [head,
                Patch(facecolor=col["catchment"], alpha=alpha + 0.2, edgecolor=col["catchment_edge"], lw=cfg.get("catchment_linewidth", 0.7), label=f"Local ({len(cat)})"),
                Patch(facecolor=col["transfer"], alpha=alpha + 0.3, edgecolor=col["transfer_edge"], lw=cfg.get("catchment_linewidth", 0.7),
                      label=f"Transfer ({len(trc)})"),
                Line2D([], [], color="none", label=" ")]  # spacer: ends the group
    handles += [Line2D([], [], marker="D", ls="", color=col["seat"], mec="white", mew=0.3, ms=3.5, label="Municipal seat"),
                Patch(facecolor=col["municipio"], edgecolor=col["municipio_edge"], lw=0.9, label="Municipality"),
                Patch(facecolor=col["background"], edgecolor=col["background_edge"], lw=0.3, label="Other municipalities")]
    if urban is not None:
        handles.append(Patch(facecolor=ua_color, alpha=ua.get("alpha", 1), lw=0, label="Urban area"))
    if water is not None:
        handles.append(Patch(facecolor=wb_color, edgecolor=wb_edge, lw=0.3, label="Water body"))
    if (ocean is not None and len(ocean)) or (marine is not None and len(marine)):
        handles.append(Patch(facecolor=oc_color, lw=0, label="Ocean"))
    if aq is not None:  # same entry in both modes (zoom mode: the relevant systems are also listed on the map)
        handles.append(Line2D([], [], color=aq_color, alpha=aq_alpha, lw=1.0, label="Aqueduct" + (" (operating)" if bg_family == "Operando" else f" ({bg_family})" if bg_family else "")))
    if drain is not None:
        handles.append(Line2D([], [], color=drain_color, lw=0.6, label="Drainage"))
    side_panel(fig, gpkg, code, name, uf, proj_text, handles, col, cfg, view)

    path = out_dir / file_name(code, name, zoom_mode)
    fig.savefig(path, dpi=cfg.get("dpi", 300), facecolor="white", pil_kwargs={"quality": cfg.get("jpeg_quality", 92)})
    plt.close(fig)
    log(f"written {path}")
    return path


def municipio_codes(spec, base):
    """IBGE codes from a code, a list of codes, or a text file (one code per line; blank lines and '#' comments skipped;
    only the first token of a line counts, so "4314902 Porto Alegre" works). Order kept, repeats dropped."""
    items = spec if isinstance(spec, list) else [spec]
    codes = []
    for it in items:
        it = str(it).strip()
        if re.fullmatch(r"\d{7}", it):
            codes.append(it)
            continue
        f = base / it
        if not f.is_file():
            sys.exit(f"municipios: {it!r} is neither a 7-digit code nor a file")
        for line in f.read_text(encoding="utf-8").splitlines():
            tok = line.split("#", 1)[0].split()
            if tok:
                if not re.fullmatch(r"\d{7}", tok[0]):
                    sys.exit(f"{f.name}: {tok[0]!r} is not a 7-digit IBGE code")
                codes.append(tok[0])
    return list(dict.fromkeys(codes))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--municipio", nargs="+", help="IBGE codes or text files (override `municipios` of the config)")
    ap.add_argument("--skip-existing", action="store_true", help="do not redraw maps whose JPEG already exists")
    a = ap.parse_args()
    cpath = Path(a.config).resolve()
    cfg = json.loads(cpath.read_text(encoding="utf-8"))
    spec = a.municipio or cfg.get("municipios", cfg.get("municipio_code"))
    miss = [k for k in REQUIRED if k not in cfg] + ([] if spec else ["municipios"])
    if miss:
        sys.exit(f"config: missing keys {miss}")
    # command-line files resolve against the working directory, config files against the config folder
    codes = municipio_codes(spec, Path.cwd() if a.municipio else cpath.parent)
    gpkg = cpath.parent / cfg["gpkg"]
    out_dir = cpath.parent / cfg["output_folder"]
    out_dir.mkdir(parents=True, exist_ok=True)
    col = {**COLORS, **cfg.get("colors", {})}
    set_font(cfg.get("font", "default"))
    skip = a.skip_existing or cfg.get("skip_existing", False)
    log(f"{len(codes)} municipalities -> {out_dir}")
    done, skipped, failed = 0, 0, []
    for i, code in enumerate(codes, 1):
        # zoom and default maps may share a folder: look only for this mode's files
        if skip and any(p for p in out_dir.glob(f"{code}_*.jpeg") if p.stem.endswith("_ZOOM") == (cfg.get("zoom") == "intakes")):
            skipped += 1
            continue
        log(f"[{i}/{len(codes)}] {code}")
        try:
            plot_one(code, cfg, cpath, gpkg, out_dir, col)
            done += 1
        except Exception as e:  # one bad municipality must not stop a batch
            plt.close("all")
            log(f"  ERROR {code}: {type(e).__name__}: {e}")
            failed.append(code)
    log(f"done: {done} written, {skipped} skipped (existing), {len(failed)} failed{': ' + ' '.join(failed) if failed else ''}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
