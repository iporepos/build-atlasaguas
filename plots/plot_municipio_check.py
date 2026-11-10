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
Zoom mode ("zoom": "intakes", optional): the frame is a square centred on the bounds of the linked intake points, side =
zoom_scale (5) x their larger side, at least zoom_min_km (10, e.g. a single intake); everything else is drawn as usual
(what falls outside is cut). No intake points, or a zoom frame not smaller than the default one -> default frame. The
square grows on its short side to the map box.
Layers, bottom to top: other municipalities (light gray, subtle borders), municipality (gray, stronger border),
urban areas (optional, dark red, no border),
water bodies (optional, light blue), catchments (light green, transparent: nested ones show darker),
drainage (optional), municipal seats (diamonds, named), intake points (surface blue, groundwater orange, white border).
Page: A4 landscape. Map on the left (frame with 3-4 inward lat/long ticks, scale bar; the frame grows on its short side
to the map box), a 5 cm side panel on the right: code, name, metropolitan region, operator, supply facts from T2
(urban population 2020, provisioning area, m2 per urban inhabitant, source mix, topology, upstream intakes), legend,
sources. Output: <output_folder>/<code>_<NAME>.jpeg (name upper case, no accents, spaces -> '-') at dpi.
Projection (key projection): "local" (default) Lambert azimuthal equal-area centred on the frame, "utm" (zone of the
municipality) or any CRS string.
Config keys: gpkg, municipios (old name municipio_code still read), output_folder. Relative paths resolve against the config file.
  Optional: urban_areas ({"path" (QGIS-style "file|layername=x" accepted) or "layer", "where", "color" (#814446),
  "alpha" (1), "credit"}: no border, just above the municipality fills), water_bodies ({"path": polygon layer, QGIS-style "file.gpkg|layername=x" accepted, or "layer"; "where",
  "color" (light blue), "edgecolor", "linewidth" (0.2), "credit"}: drawn above the municipality fills, below the
  catchments), drainage ({"path": shp/gpkg (GDAL path, e.g. /vsizip/...zip/x.shp), "where": SQL filter such as
  "ORD_STRA >= 2", "linewidth": 0.25, "color": hex; "column": e.g. "ORD_STRA" -> color (cmap, default Blues, cut to
  cmap_range [0.35, 1]) and width (linewidth_range [0.2, 0.6]) scaled on the local min-max of the column in the frame;
  declutter: the max_reaches (2000; 0 = all) largest kept, ties broken by tie_column (e.g. UPLAND_SKM; without it
  whole classes of the smallest values are dropped, the largest class kept whole);
  column absent or not found -> single color and linewidth; "credit": panel text}), dpi (300), jpeg_quality (92), margin (0.04 of the
  frame), part_max_distance_km (50), title_size (11, shrinks to fit the panel), point_size (32), point_edge (0.9), seat_size (9), max_labels (20: seat names shown, own first, then by urban population 2020; every seat keeps its diamond; unlabelled ones smaller, seat_unlabelled_scale 0.55 of the area, and lighter), colors ({background, background_edge, seat, seat_unlabelled, municipio, municipio_edge, catchment, catchment_edge, surface, groundwater,
  drainage}), catchment_alpha (0.3).
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
import pyogrio
import shapely
from pyproj import CRS, Transformer

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

REQUIRED = ["gpkg", "output_folder"]
COLORS = {"background": "#f1f0ec", "background_edge": "#c4c3be", "seat": "#3d3c39", "seat_unlabelled": "#9a9994",
          "municipio": "#d9d8d4", "municipio_edge": "#3d3c39", "catchment": "#7cc47c", "catchment_edge": "#3f8f3f",
          "surface": "#2a78d6", "groundwater": "#ef7d1a", "drainage": "#3b78b0", "urban": "#814446", "water": "#b9dcf2", "water_edge": "#7fb3d5", "ink": "#0b0b0b", "ink2": "#52514e"}
CM = 1 / 2.54


def log(m):
    print(m, flush=True)


def file_name(code, name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    return f"{code}_{re.sub(r'[^A-Z0-9]+', '-', s).strip('-')}.jpeg"


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


def read_in_frame(spec, base, frame, crs):
    """Features of an optional layer inside the frame. spec: {"path", "layer" (optional), "where" (optional)}; the path
    may carry the layer QGIS-style ("file.gpkg|layername=x"); relative paths resolve against the config folder."""
    path, layer = spec["path"], spec.get("layer")
    if "|layername=" in path:
        path, layer = path.split("|layername=", 1)
    path = path if path.startswith("/vsi") else str(base / path)
    bbox = gpd.GeoSeries([dense(frame)], crs=crs).to_crs(pyogrio.read_info(path, layer=layer)["crs"]).total_bounds
    # all columns: GDAL returns nothing when `where` runs with columns=[]
    return pyogrio.read_dataframe(path, layer=layer, bbox=tuple(bbox), where=spec.get("where")).to_crs(crs)


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


def side_panel(fig, gpkg, code, name, uf, proj_text, handles, col, cfg):
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
    y -= 0.2
    for label, val in (("Metropolitan region", mrow[1]), ("Operator", mrow[2])):
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
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=((x - 0.15) / PAGE[0], y / PAGE[1]), fontsize=7,
               frameon=False, borderaxespad=0, handlelength=1.6, labelspacing=0.7, labelcolor=ink)
    foot = [f"Data: ANA Atlas Águas 2021 (T2)", f"Intakes: provisioning_links of {code}"]
    if cfg.get("drainage"):
        foot.append(cfg["drainage"].get("credit", "Drainage: HydroRIVERS v1.0"))
    if cfg.get("urban_areas"):
        foot.append(cfg["urban_areas"].get("credit", "Urban areas: IBGE BC250"))
    if cfg.get("water_bodies"):
        foot.append(cfg["water_bodies"].get("credit", "Water bodies: IBGE BC250"))
    foot += textwrap.wrap(f"Projection: {proj_text}", 48)
    yy = MAP_BOX[1]
    for line in reversed(foot):
        cm_text(fig, x, yy, line, fontsize=5.5, color=ink2, va="bottom")
        yy += 0.3


def plot_one(code, cfg, cpath, gpkg, out_dir, col):
    """One map: <out_dir>/<code>_<NAME>.jpeg."""
    mun = pyogrio.read_dataframe(gpkg, layer="municipios", where=f"municipio_code = {sql_list([code])}")
    if len(mun) != 1:
        raise ValueError(f"municipio {code} not found")
    name, uf = mun.municipio_name.iloc[0], mun.unidade_alias.iloc[0]
    con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    links = dict(con.execute("SELECT intake_code, link_source FROM provisioning_links WHERE municipio_code = ?", (code,)).fetchall())
    con.close()
    itk = pyogrio.read_dataframe(gpkg, layer="intakes", where=f"intake_code IN ({sql_list(links) or 'NULL'})")
    cat = pyogrio.read_dataframe(gpkg, layer="catchments", where=f"intake_code IN ({sql_list(links) or 'NULL'})")
    n_s, n_g = int((itk.intake_type == "Superficial").sum()), int((itk.intake_type == "Subterrânea").sum())
    log(f"{code} {name} ({uf}): {len(links)} linked intakes ({n_s} surface, {n_g} groundwater), {len(cat)} catchments")

    core, dropped = core_parts(mun.geometry.iloc[0], mun.crs, cfg.get("part_max_distance_km", 50))
    if dropped:
        log(f"  municipality: {dropped} remote polygon part(s) left out of the frame (> {cfg.get('part_max_distance_km', 50)} km from the main part)")
    zoom = cfg.get("zoom")
    if zoom not in (None, "intakes"):
        raise ValueError(f"zoom {zoom!r}: only \"intakes\" (or absent)")
    pts = itk.geometry.dropna()
    if zoom == "intakes" and not len(pts):
        log("  zoom intakes: no intake points, default frame")
        zoom = None
    def make_frame(geoms, square):
        """(crs, projection text, frame bounds grown to the map box aspect) for an extent; square = zoom mode."""
        ext = gpd.GeoSeries(geoms, crs=mun.crs)
        crs_, text_ = map_crs(cfg.get("projection", "local"), ext)
        a0, b0, a1, b1 = ext.to_crs(crs_).total_bounds
        if square:
            # square on the intake points: side = zoom_scale x the larger side of their bounds (at least zoom_min_km)
            side = max(cfg.get("zoom_scale", 5) * max(a1 - a0, b1 - b0), cfg.get("zoom_min_km", 10) * 1000)
            cx, cy = (a0 + a1) / 2, (b0 + b1) / 2
            a0, b0, a1, b1 = cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2
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

    normal = make_frame([core] + list(cat.geometry) + list(pts), False)
    crs, proj_text, (x0, y0, x1, y1) = normal
    if zoom:
        zc, zt, zb = make_frame(list(pts), True)
        area = lambda b: (b[2] - b[0]) * (b[3] - b[1]) / 1e6  # noqa: E731 (both projections are equal-area)
        if area(zb) < area(normal[2]):
            crs, proj_text, (x0, y0, x1, y1) = zc, zt, zb
            log(f"  zoom intakes: frame {(zb[2] - zb[0]) / 1000:.1f} x {(zb[3] - zb[1]) / 1000:.1f} km")
        else:
            log(f"  zoom intakes: frame {area(zb):,.0f} km2 not smaller than the default ({area(normal[2]):,.0f} km2), default kept")
    mun, itk, cat = mun.to_crs(crs), itk.to_crs(crs), cat.to_crs(crs)
    frame = shapely.box(x0, y0, x1, y1)
    bbox_ll = tuple(gpd.GeoSeries([dense(frame)], crs=crs).to_crs(pyogrio.read_info(gpkg, layer="municipios")["crs"]).total_bounds)
    bg = pyogrio.read_dataframe(gpkg, layer="municipios", bbox=bbox_ll, columns=["municipio_code", "municipio_name"]).to_crs(crs)
    seats = pyogrio.read_dataframe(gpkg, layer="municipios_sedes", bbox=bbox_ll).to_crs(crs)
    seats = seats.merge(bg[["municipio_code", "municipio_name"]], on="municipio_code", how="left")
    seats = seats[seats.intersects(frame)]
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
    draw(ax, bg[bg.municipio_code != code], color=col["background"], edgecolor=col["background_edge"], linewidth=0.3, zorder=0)
    draw(ax, mun, color=col["municipio"], linewidth=0, zorder=1)
    draw(ax, mun.boundary, color=col["municipio_edge"], linewidth=0.9, zorder=2.7)  # above the catchments
    ua = cfg.get("urban_areas") or {}
    ua_color = ua.get("color", col["urban"])
    if urban is not None and len(urban):  # just above the municipality fills, no border
        draw(ax, urban, color=ua_color, alpha=ua.get("alpha", 1), linewidth=0, zorder=1.2)
    wb = cfg.get("water_bodies") or {}
    wb_color, wb_edge = wb.get("color", col["water"]), wb.get("edgecolor", col["water_edge"])
    if water is not None and len(water):  # above the municipality fills, below the catchments (seen through them)
        draw(ax, water, color=wb_color, edgecolor=wb_edge, linewidth=wb.get("linewidth", 0.2), zorder=1.5)
    alpha = cfg.get("catchment_alpha", 0.3)
    if len(cat):
        draw(ax, cat, color=col["catchment"], alpha=alpha, linewidth=0, zorder=2)
        draw(ax, cat.boundary, color=col["catchment_edge"], linewidth=0.4, zorder=2.5)
    drain_color = cfg.get("drainage", {}).get("color", col["drainage"])
    if drain is not None and len(drain):
        d = cfg["drainage"]
        c_ = d.get("column")
        if c_ and c_ not in drain.columns:
            log(f"  drainage: column {c_} not found, single color and width")
        if c_ and c_ in drain.columns and drain[c_].notna().any():
            # declutter: keep the max_reaches largest (a larger frame drops more). Ties (stream orders are classes) are
            # broken by tie_column (e.g. UPLAND_SKM: within an order the downstream, larger reaches stay); without
            # it whole classes are dropped (the largest class kept whole). Color and width are scaled on the local
            # min-max of ALL reaches in the frame (before the cut: main rivers stay dark and thick on large maps);
            # missing values count as the minimum
            v = drain[c_].astype(float).fillna(drain[c_].min())
            lo, hi = v.min(), v.max()
            n0, cap, tie = len(drain), int(d.get("max_reaches", 2000)), d.get("tie_column")
            if cap and n0 > cap:
                if tie and tie in drain.columns:
                    order = np.lexsort((-drain[tie].astype(float).fillna(0).values, -v.values))  # by v, then tie, descending
                    keep = np.zeros(n0, bool)
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
            log(f"  drainage: {len(drain)} of {n0} reaches kept (max_reaches {cap}, {c_} {v.min():g}-{v.max():g}), scaled on {lo:g}-{hi:g}")
        else:
            draw(ax, drain, color=drain_color, linewidth=d.get("linewidth", 0.25), zorder=3)
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
    ps, pe = cfg.get("point_size", 32), cfg.get("point_edge", 0.9)
    for typ, c in (("Subterrânea", col["groundwater"]), ("Superficial", col["surface"])):
        g = itk[itk.intake_type == typ]
        if len(g):
            draw(ax, g, color=c, markersize=ps, edgecolor="white", linewidth=pe, zorder=4)
    scale_bar(ax, x0, x1, y0, y1, col["ink2"])
    ax.set_xlabel("")
    ax.set_ylabel("")  # geopandas labels projected axes (Easting/Northing); the ticks are lat/long

    handles = [Line2D([], [], marker="o", ls="", color=col["surface"], mec="white", mew=0.9, ms=7.5, label=f"Surface intake ({n_s})"),
               Line2D([], [], marker="o", ls="", color=col["groundwater"], mec="white", mew=0.9, ms=7.5, label=f"Groundwater intake ({n_g})"),
               Patch(facecolor=col["catchment"], alpha=alpha + 0.2, edgecolor=col["catchment_edge"], lw=0.4, label=f"Catchment ({len(cat)})"),
               Patch(facecolor=col["municipio"], edgecolor=col["municipio_edge"], lw=0.9, label="Municipality"),
               Patch(facecolor=col["background"], edgecolor=col["background_edge"], lw=0.3, label="Other municipalities"),
               Line2D([], [], marker="D", ls="", color=col["seat"], mec="white", mew=0.3, ms=3.5, label="Municipal seat")]
    if urban is not None:
        handles.append(Patch(facecolor=ua_color, alpha=ua.get("alpha", 1), lw=0, label="Urban area"))
    if water is not None:
        handles.append(Patch(facecolor=wb_color, edgecolor=wb_edge, lw=0.3, label="Water body"))
    if drain is not None:
        handles.append(Line2D([], [], color=drain_color, lw=0.6, label="Drainage"))
    side_panel(fig, gpkg, code, name, uf, proj_text, handles, col, cfg)

    path = out_dir / file_name(code, name)
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
    skip = a.skip_existing or cfg.get("skip_existing", False)
    log(f"{len(codes)} municipalities -> {out_dir}")
    done, skipped, failed = 0, 0, []
    for i, code in enumerate(codes, 1):
        if skip and any(out_dir.glob(f"{code}_*.jpeg")):
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
