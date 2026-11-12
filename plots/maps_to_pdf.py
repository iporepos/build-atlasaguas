#!/usr/bin/env python3
"""Bundle JPEG figures into one PDF (one image per page), e.g. for a Zenodo release: the maps of
plot_municipio_check.py (folder mode) or any list of JPEGs, e.g. the dispersion plots (files mode).

Usage (project venv):  .venv/bin/python plots/maps_to_pdf.py --config plots/maps_to_pdf_capitals.local.json [--overwrite]

Config keys: output (the PDF), and either
  files: list of JPEG paths or glob patterns (relative to the config; a pattern adds its matches sorted), or objects
  {"path": ..., "title": ...}: pages in this order, one bookmark per file (title, default the file name), or
  folder (where the maps are: <code>_<NAME>.jpeg and <code>_<NAME>_ZOOM.jpeg) for the maps.
  Optional: municipios (a code, a list, or a text file as in plot_municipio_check.py: the page order; default every
  map in the folder, by code), views (["full", "zoom"]: which maps and their order within a municipality),
  title, author, subject (PDF metadata), gpkg (the T2 database: bookmark names "<Name> (<UF>)" from municipios;
  without it the name comes from the file name).
The JPEG data is embedded as is (no recompression, no extra dependency); the page size follows the image size and its
dpi (300 if the file has none), so an A4 map at 300 dpi gives an A4 page. One bookmark per municipality
("<code> <Name> (<UF>)", pointing at its first page). Stops on a missing map (a code of the list without the requested
views) or when the PDF exists (use --overwrite). Writes <output>.part, then renames.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_municipio_check import municipio_codes  # noqa: E402  same list syntax as the maps

VIEWS = {"full": "", "zoom": "_ZOOM"}


def log(m):
    print(m, flush=True)


def pdf_text(s):
    """PDF text string: plain ASCII as a literal, anything else as UTF-16BE hex with a BOM."""
    if s.isascii():
        return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"
    return "<FEFF" + s.encode("utf-16-be").hex().upper() + ">"


def find_maps(folder, codes, views):
    """[(code, name, [jpeg paths in view order])]; stops on a missing view."""
    found = {}
    for p in sorted(folder.glob("*.jpeg")):
        code, _, rest = p.stem.partition("_")
        view = "zoom" if rest.endswith("_ZOOM") else "full"
        name = rest[: -len("_ZOOM")] if view == "zoom" else rest
        found.setdefault(code, {"name": name})[view] = p
    codes = codes or sorted(found)
    out, missing = [], []
    for c in codes:
        m = found.get(c, {})
        miss = [v for v in views if v not in m]
        if miss:
            missing.append(f"{c} ({', '.join(miss)})")
            continue
        out.append((c, m["name"], [m[v] for v in views]))
    if missing:
        sys.exit(f"maps missing in {folder}: {'; '.join(missing)}")
    return out


def write_pdf(path, pages, info):
    """pages: [(jpeg path, bookmark title or None)]. Minimal PDF 1.4: one DCTDecode image per page."""
    objs = []  # bytes of objects 1..n, filled in order

    def add(b):
        objs.append(b)
        return len(objs)

    def ref(i):
        return f"{i} 0 R"
    catalog, pages_id, outlines_id = add(b""), add(b""), add(b"")  # placeholders, written last
    page_ids, marks = [], []
    for jpeg, title in pages:
        with Image.open(jpeg) as im:
            if im.format != "JPEG":
                sys.exit(f"{jpeg}: not a JPEG")
            w, h = im.size
            dpi = float((im.info.get("dpi") or (300, 300))[0]) or 300.0
            cs = {"RGB": "/DeviceRGB", "L": "/DeviceGray", "CMYK": "/DeviceCMYK"}.get(im.mode)
            if cs is None:
                sys.exit(f"{jpeg}: color mode {im.mode} not supported")
        data = jpeg.read_bytes()
        pw, ph = w / dpi * 72, h / dpi * 72  # points
        img = add(f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace {cs} /BitsPerComponent 8 "
                  f"/Filter /DCTDecode /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")
        content = f"q {pw:.3f} 0 0 {ph:.3f} 0 0 cm /Im0 Do Q".encode()
        cid = add(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        pid = add(f"<< /Type /Page /Parent {ref(pages_id)} /MediaBox [0 0 {pw:.3f} {ph:.3f}] "
                  f"/Resources << /XObject << /Im0 {ref(img)} >> >> /Contents {ref(cid)} >>".encode())
        page_ids.append(pid)
        if title:
            marks.append((title, pid))
    # bookmarks: a flat list, one item per municipality
    mark_ids = list(range(len(objs) + 1, len(objs) + 1 + len(marks)))
    for k, ((title, pid), mid) in enumerate(zip(marks, mark_ids)):
        links = (f" /Prev {ref(mark_ids[k - 1])}" if k else "") + (f" /Next {ref(mark_ids[k + 1])}" if k + 1 < len(marks) else "")
        add(f"<< /Title {pdf_text(title)} /Parent {ref(outlines_id)}{links} /Dest [{ref(pid)} /Fit] >>".encode())
    info_id = add(("<< " + " ".join(f"/{k} {pdf_text(v)}" for k, v in info.items() if v) + " /Producer (maps_to_pdf.py) >>").encode())
    objs[catalog - 1] = f"<< /Type /Catalog /Pages {ref(pages_id)} /Outlines {ref(outlines_id)} /PageMode /UseOutlines >>".encode()
    objs[pages_id - 1] = f"<< /Type /Pages /Kids [{' '.join(ref(p) for p in page_ids)}] /Count {len(page_ids)} >>".encode()
    objs[outlines_id - 1] = (f"<< /Type /Outlines /First {ref(mark_ids[0])} /Last {ref(mark_ids[-1])} /Count {len(marks)} >>"
                             if marks else "<< /Type /Outlines /Count 0 >>").encode()
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, b in enumerate(objs, 1):
            offsets.append(f.tell())
            f.write(f"{i} 0 obj\n".encode() + b + b"\nendobj\n")
        xref = f.tell()
        f.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
        f.write("".join(f"{o:010d} 00000 n \n" for o in offsets).encode())
        f.write(f"trailer\n<< /Size {len(objs) + 1} /Root {ref(catalog)} /Info {ref(info_id)} >>\nstartxref\n{xref}\n%%EOF\n".encode())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    cpath = Path(a.config).resolve()
    cfg = json.loads(cpath.read_text(encoding="utf-8"))
    if "output" not in cfg or ("folder" in cfg) == ("files" in cfg):
        sys.exit("config: needs output and one of folder (maps) or files (any JPEGs)")
    out = cpath.parent / cfg["output"]
    if out.exists() and not a.overwrite:
        sys.exit(f"{out} exists (use --overwrite)")
    if "files" in cfg:
        pages = []
        for it in cfg["files"]:
            spec, title = (it["path"], it.get("title")) if isinstance(it, dict) else (it, None)
            hits = sorted(cpath.parent.glob(spec)) if any(ch in spec for ch in "*?[") else [cpath.parent / spec]
            if not hits or not all(h.is_file() for h in hits):
                sys.exit(f"files: nothing found for {spec}")
            pages += [(h, title or h.stem) for h in hits]
        write_out(out, pages, cfg)
        return
    folder = cpath.parent / cfg["folder"]
    views = cfg.get("views", ["full", "zoom"])
    bad = [v for v in views if v not in VIEWS]
    if bad or not views:
        sys.exit(f"views: use a non-empty list of {list(VIEWS)} (got {views})")
    codes = municipio_codes(cfg["municipios"], cpath.parent) if cfg.get("municipios") else None
    maps = find_maps(folder, codes, views)
    names = {}
    if cfg.get("gpkg"):
        con = sqlite3.connect(f"file:{cpath.parent / cfg['gpkg']}?mode=ro", uri=True)
        names = {c: f"{n} ({u})" for c, n, u in con.execute("SELECT municipio_code, municipio_name, unidade_alias FROM municipios")}
        con.close()
    pages = [(p, f"{c} {names.get(c) or n.replace('-', ' ').title()}" if i == 0 else None) for c, n, ps in maps for i, p in enumerate(ps)]
    log(f"{len(maps)} municipalities")
    write_out(out, pages, cfg)


def write_out(out, pages, cfg):
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    write_pdf(part, pages, {k.capitalize(): cfg.get(k) for k in ("title", "author", "subject")})
    part.replace(out)
    log(f"{len(pages)} pages -> {out} ({out.stat().st_size / 1e6:,.1f} MB)")


if __name__ == "__main__":
    main()
