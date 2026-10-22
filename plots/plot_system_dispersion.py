#!/usr/bin/env python3
"""Scatter of two columns of the SQL result, e.g. covered population vs area: one dot per row (supply system, or municipality with the
provisioning-area config plot_municipio_provisioning.local.json).

Usage (project venv):  .venv/bin/python plots/plot_system_dispersion.py --config plots/plot_system_dispersion.local.json [--show] [--output file.jpg]

Runs the SQL file against the T2 GeoPackage (read-only) and plots the result.
  --show    interactive window: hover a dot to see system, municipalities, population, area and density
  (default) saves a JPEG to config `output` (or --output) and does not open a window
Config keys: gpkg, sql (relative to the config file), output, x, y, category, category_order, x_label, y_label,
  title, panel_color (plot area gray), log_x, log_y, label_top (how many extreme systems are named per measure), label_column (default municipios_name), dpi, size_inches, jpeg_quality.
  Optional: subtitle (may use {n} plotted and {dropped}), ratio_column (third measure for labels, default
  covered_population_per_km2), hover (list of [column, text, format], e.g. ["n_parts", "parts", "{:.0f}"]),
  marker_size (default 44), marker_edge (default 1.2), alpha (default 0.95), colors (categorical hex list in category_order,
  default 3 slots), legend_loc (default lower right), label_gap (points of extra space left/right of each name label,
  default 0; e.g. 4 when short names would touch),
  equal_axes (true: same limits on x and y, whole decades covering both, aspect 1:1 -> square plotting area; log axes),
  identity_line ({"label": "...", "factor": f}: solid light-gray y = f * x line (f default 1), labelled along the line; e.g. 1 km2
  per inhabitant; a list of such objects draws several lines, e.g. factor 0.01 for 1 ha per inhabitant),
  highlight ({"column": c, "value": v, "label": "...", "other_label": "...", "alpha": a, "scale": k}: replaces category
  with two groups, other rows first in colors[0], rows where c == v on top in colors[1] (alpha a, default the config
  alpha; dot diameter x k, default 1);
  direct labels name highlighted rows only).
Rows with a missing or non-positive x/y are dropped on log axes (counted in the log).
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

import matplotlib
import matplotlib.text
import numpy as np
import pandas as pd

REQUIRED = ["gpkg", "sql", "x", "y"]
# reference palette, light surface; categorical slots in fixed order (blue, orange)
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#d8d7d2"
REF = "#aaa9a4"  # reference lines (y = f * x), a step lighter than MUTED
PANEL = "#e4e3df"  # dim gray plotting area (config panel_color overrides); gridlines are drawn in the surface color
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]


def log(m):
    print(m, flush=True)


def load(cfg, cfg_dir):
    sql_path = Path(cfg["sql"])
    if not sql_path.is_absolute():
        sql_path = cfg_dir / sql_path
    con = sqlite3.connect(f"file:{cfg['gpkg']}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query(sql_path.read_text(encoding="utf-8"), con)
    finally:
        con.close()
    log(f"query returned {len(df)} rows, columns: {', '.join(df.columns)}")
    return df


def short_label(text, max_names=3, max_len=34):
    """'A (RS) | B (RS)' -> 'A, B (RS)'; different states keep their own '(UF)'; more than max_names -> '+N'."""
    items = [i.strip() for i in str(text).split(" | ") if i.strip()]
    parsed = [re.match(r"^(.*?)\s*\(([A-Z]{2})\)$", i) for i in items]
    if not items or not all(parsed):
        out = ", ".join(items)
    else:
        names, ufs = [m.group(1) for m in parsed], [m.group(2) for m in parsed]
        extra = len(names) - max_names
        names, ufs = names[:max_names], ufs[:max_names]
        out = ", ".join(names) + (f" +{extra}" if extra > 0 else "")
        out += f" ({ufs[0]})" if len(set(ufs)) == 1 else " (" + "/".join(dict.fromkeys(ufs)) + ")"
    return out if len(out) <= max_len else out[: max_len - 1] + "…"


def fmt_num(v, _=None):
    if v >= 1e6:
        return f"{v / 1e6:g} M"
    if v >= 1e3:
        return f"{v / 1e3:g} k"
    return f"{v:g}"


def draw(df, cfg, interactive):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    x, y, cat = cfg["x"], cfg["y"], cfg.get("category")
    hl = cfg.get("highlight")
    if hl:
        cat = hl["column"]
    for c in (x, y) + ((cat,) if cat else ()):
        if c not in df.columns:
            sys.exit(f"column {c} not in the query result")
    d = df.copy()
    ok = d[x].notna() & d[y].notna()
    if cfg.get("log_x", True):
        ok &= d[x] > 0
    if cfg.get("log_y", True):
        ok &= d[y] > 0
    log(f"plotting {int(ok.sum())} points ({int((~ok).sum())} dropped: missing or non-positive values)")
    d = d[ok].reset_index(drop=True)
    ratio = cfg.get("ratio_column", "covered_population_per_km2")
    if hl:
        on, other = hl.get("label", str(hl["value"])), hl.get("other_label", "Others")
        cat = "_highlight"
        d[cat] = np.where(d[hl["column"]] == hl["value"], on, other)
        cfg = {**cfg, "category_order": [other, on]}

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2})
    fig, ax = plt.subplots(figsize=cfg.get("size_inches", [10, 6.5]), facecolor=SURFACE)
    panel = cfg.get("panel_color", PANEL)
    ax.set_facecolor(panel)
    colors = cfg.get("colors", SERIES)
    groups = list(cfg.get("category_order") or (sorted(d[cat].dropna().unique()) if cat else []))
    if cat:
        groups += [g for g in d[cat].dropna().unique() if g not in groups]
        if len(groups) > len(colors):
            sys.exit(f"{len(groups)} categories but only {len(colors)} colors in the config")
    cols, collections, index_of = {}, [], []
    for i, g in enumerate(groups or [None]):
        sub = d if g is None else d[d[cat] == g]
        size = float(cfg.get("marker_size", 44)) * (float(hl.get("scale", 1)) ** 2 if hl and i == 1 else 1)  # s is an area
        sc = ax.scatter(sub[x], sub[y], s=size, color=colors[i], edgecolors=panel,
                        linewidths=float(cfg.get("marker_edge", 1.2)),
                        alpha=float(hl.get("alpha", cfg.get("alpha", 0.95)) if hl and i == 1 else cfg.get("alpha", 0.95)),
                        label=(f"{g} (n={len(sub)})" if g is not None else None), zorder=3)
        collections.append(sc)
        index_of.append(sub.index.to_numpy())
    if cfg.get("log_x", True):
        ax.set_xscale("log")
    if cfg.get("log_y", True):
        ax.set_yscale("log")
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(FuncFormatter(fmt_num))
    if cfg.get("equal_axes"):
        if not (cfg.get("log_x", True) and cfg.get("log_y", True)):
            sys.exit("equal_axes needs log_x and log_y")
        v = np.concatenate([d[x].to_numpy(float), d[y].to_numpy(float)])
        lo, hi = 10.0 ** np.floor(np.log10(v.min())), 10.0 ** np.ceil(np.log10(v.max()))
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.set_aspect("equal", adjustable="box")
    lines = cfg.get("identity_line") or []
    lines = [lines] if isinstance(lines, dict) else lines
    spans = []  # (a, b, f): x range of each y = f * x line inside the axes
    for line in lines:
        f = float(line.get("factor", 1))
        (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
        a, b = max(x0, y0 / f), min(x1, y1 / f)
        ax.plot([a, b], [f * a, f * b], color=REF, linewidth=1.0, zorder=2)
        spans.append((a, b, f))
    ax.grid(True, which="major", color=SURFACE, linewidth=1.0, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.set_xlabel(cfg.get("x_label", x), fontsize=10)
    ax.set_ylabel(cfg.get("y_label", y), fontsize=10)
    import textwrap
    fw = float(cfg.get("size_inches", [10, 6.5])[0])
    sub_text = cfg.get("subtitle", "One dot per supply system. Catchment areas of a system's intakes are summed (no overlap correction).")
    sub = textwrap.fill(sub_text.format(n=len(d), dropped=int((~ok).sum())), width=max(30, int(fw * 13)))
    title = textwrap.fill(cfg.get("title", ""), width=max(24, int(fw * 8.5)))
    nsub = sub.count("\n") + 1
    ax.text(0, 1.015, sub, transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom", linespacing=1.25)
    ax.set_title(title, loc="left", fontsize=12 if fw < 9 else 13, fontweight="bold", color=INK, pad=14 + 12 * nsub)
    if groups:
        leg = ax.legend(loc=cfg.get("legend_loc", "lower right"), frameon=False, fontsize=9, labelcolor=INK2, handletextpad=0.4)
        for h in leg.legend_handles:
            h.set_sizes([44])

    # selective direct labels: extremes of each measure, named with INK2 text (never the series color)
    n = int(cfg.get("label_top", 3))
    pick = []
    cand = d[d[cat] == on] if hl else d
    for col in (y, x) + ((ratio,) if ratio in d.columns else ()):
        pick += list(cand[col].nlargest(n).index)
    seen = set()
    lab_col = cfg.get("label_column", "municipios_name")

    def label_of(i):
        r = d.loc[i]
        return short_label(r[lab_col]) if lab_col == "municipios_name" and lab_col in d.columns else str(r.get(lab_col, r.get("system_name", i)))[:34]

    base = {i: label_of(i) for i in dict.fromkeys(pick)}
    dup = pd.Series(list(base.values())).duplicated(keep=False).to_numpy()
    dups = {l for l, f in zip(base.values(), dup) if f}  # same municipality for several labelled systems: add the system name
    fig.tight_layout()
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    placed = []
    for line, (a, b, f) in zip(lines, spans):
        if not line.get("label"):
            continue
        p0, p1 = ax.transData.transform([(a, f * a), (b, f * b)])
        angle = np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0]))
        at = a * (b / a) ** 0.93  # near the upper end of the line
        lt = ax.annotate(line["label"], (at, f * at), xytext=(0, 4), textcoords="offset points", fontsize=8, color=INK2,
                         rotation=angle, rotation_mode="anchor", ha="right", va="bottom", zorder=4)
        placed.append(lt.get_window_extent(rend).expanded(1.04, 1.25))
    # label offsets (points) tried in order; the first whose box stays inside the axes and clear of earlier labels wins
    cands = [(8, 8, "left"), (8, -14, "left"), (-8, 8, "right"), (-8, -14, "right"), (8, 24, "left"), (-8, 24, "right"),
             (8, -30, "left"), (-8, -30, "right"), (8, 40, "left"), (-8, 40, "right"),
             (-30, 56, "right"), (-30, -56, "right"), (-60, 20, "right"), (-60, -40, "right"), (-90, 8, "right"), (-90, -30, "right"),
             (-120, 30, "right"), (-120, -60, "right"), (8, 60, "left"), (-8, 60, "right"), (8, -60, "left"), (-8, -60, "right"),
             (-150, 10, "right"), (-150, -20, "right"), (-200, 10, "right"), (-200, -30, "right"),
             (-20, -100, "right"), (-20, -150, "right"), (-20, -200, "right"), (-20, -250, "right"), (-100, -120, "right"), (-100, -200, "right")]
    axbox = ax.get_window_extent(rend)
    gap = fig.dpi * float(cfg.get("label_gap", 0)) / 72  # extra horizontal clearance between labels (points -> pixels)
    pts = ax.transData.transform(np.column_stack([cand[x].to_numpy(), cand[y].to_numpy()]))  # dots are obstacles too (highlight: its own only)
    for i in pick:
        if i in seen:
            continue
        seen.add(i)
        name = base[i]
        if name in dups and "system_name" in d.columns:
            name = f"{name} - {str(d.loc[i, 'system_name']).replace('Sistema ', '')}"[:44]
        best = None
        for dx, dy, ha in cands:
            t = ax.annotate(name, (d.loc[i, x], d.loc[i, y]), xytext=(dx, dy), textcoords="offset points", fontsize=8, color=INK2,
                            ha=ha, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6), zorder=4)
            t.update_positions(rend)
            bb = matplotlib.text.Text.get_window_extent(t, rend).expanded(1.04, 1.25).padded(gap, 0)  # the text only, not the leader line
            inside = axbox.x0 <= bb.x0 and bb.x1 <= axbox.x1 and axbox.y0 <= bb.y0 and bb.y1 <= axbox.y1
            on_dot = ((pts[:, 0] > bb.x0 - 4) & (pts[:, 0] < bb.x1 + 4) & (pts[:, 1] > bb.y0 - 4) & (pts[:, 1] < bb.y1 + 4)).any()
            if inside and not on_dot and not any(bb.overlaps(o) for o in placed):
                placed.append(bb)
                best = t
                break
            t.remove()
        if best is None:
            log(f"note: no free space for the label of {name}; skipped")

    if interactive:
        tip = ax.annotate("", xy=(0, 0), xytext=(14, 14), textcoords="offset points", fontsize=9, color=INK, zorder=10,
                          bbox=dict(boxstyle="round,pad=0.5", fc=SURFACE, ec=MUTED, lw=0.8), arrowprops=dict(arrowstyle="-", color=MUTED))
        tip.set_visible(False)

        def text_for(r):
            if cfg.get("hover"):
                return "\n".join(str(r.get(lab_col, "")) if k == 0 else f"{txt}: {fmt.format(r[c])}" if pd.notna(r[c]) else f"{txt}: -"
                                 for k, (c, txt, fmt) in enumerate([[lab_col, "", ""]] + cfg["hover"]))
            lines = [str(r.get("system_name", ""))]
            if "municipios_name" in r:
                m = str(r["municipios_name"])
                lines.append(m if len(m) < 70 else m[:67] + "…")
            lines.append(f"covered population 2020: {r[y]:,.0f}")
            lines.append(f"catchment area: {r[x]:,.1f} km²")
            if "covered_population_per_km2" in r:
                lines.append(f"density: {r['covered_population_per_km2']:,.2f} /km²")
            if "intakes_with_catchment" in r:
                lines.append(f"intakes with catchment: {int(r['intakes_with_catchment'])}")
            return "\n".join(lines)

        def on_move(ev):
            if ev.inaxes != ax:
                if tip.get_visible():
                    tip.set_visible(False)
                    fig.canvas.draw_idle()
                return
            for sc, idx in zip(collections, index_of):
                hit, info = sc.contains(ev)
                if hit and len(info["ind"]):
                    i = idx[info["ind"][0]]
                    tip.xy = (d.loc[i, x], d.loc[i, y])
                    tip.set_text(text_for(d.loc[i]))
                    tip.set_visible(True)
                    fig.canvas.draw_idle()
                    return
            if tip.get_visible():
                tip.set_visible(False)
                fig.canvas.draw_idle()

        fig.canvas.mpl_connect("motion_notify_event", on_move)
    return fig


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--show", action="store_true", help="interactive window instead of saving a JPEG")
    ap.add_argument("--output", help="JPEG path (overrides config output)")
    a = ap.parse_args()
    cfg_path = Path(a.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    miss = [k for k in REQUIRED if k not in cfg]
    if miss:
        sys.exit(f"config: missing keys {miss}")
    if not a.show:
        matplotlib.use("Agg")
    df = load(cfg, cfg_path.parent)
    fig = draw(df, cfg, a.show)
    import matplotlib.pyplot as plt
    if a.show:
        plt.show()
        return
    out = Path(a.output or cfg.get("output", "system_dispersion.jpg"))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=cfg.get("dpi", 200), facecolor=SURFACE, pil_kwargs={"quality": cfg.get("jpeg_quality", 92)})
    log(f"saved {out}")


if __name__ == "__main__":
    main()
