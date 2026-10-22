#!/usr/bin/env python3
"""Pack the T1 and T2 ASSETS folders into zip files for a Zenodo release.

Usage (project venv):  .venv/bin/python publish.py --config publish.local.json [--dry-run] [--overwrite]

Config keys: output_folder, archives[] {zip, folder}. Optional: skip (glob patterns on file names, e.g. "*_backup_*",
  "*.zip"), compresslevel (deflate 0-9, default 6).
Each archive gets every file of its folder (subfolders included) except the skipped ones, inside a top folder named
after the zip (T1_ANA_ATLASAGUAS_DB_BRAZIL_2021.zip -> T1_ANA_ATLASAGUAS_DB_BRAZIL_2021/...).
Stops when a GeoPackage is open or was not closed cleanly (-wal / -journal next to it), when an archive would be
empty, or when the zip exists (use --overwrite). Writes <zip>.part, then renames. Prints size and md5 (Zenodo shows md5).
Reads the folders only; writes only to output_folder.
"""
import argparse
import fnmatch
import hashlib
import json
import sys
import zipfile
from pathlib import Path

REQUIRED = ["output_folder", "archives"]


def log(m):
    print(m, flush=True)


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def collect(folder, skip):
    files, skipped = [], []
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        (skipped if any(fnmatch.fnmatch(p.name, s) for s in skip) else files).append(p)
    return files, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true", help="list what would be packed; write nothing")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    miss = [k for k in REQUIRED if k not in cfg]
    if miss:
        sys.exit(f"config: missing keys {miss}")
    out = Path(cfg["output_folder"])
    skip = cfg.get("skip", [])
    plan = []
    for ar in cfg["archives"]:
        folder, target = Path(ar["folder"]), out / ar["zip"]
        if not folder.is_dir():
            sys.exit(f"{folder} not found")
        if target.exists() and not a.overwrite and not a.dry_run:
            sys.exit(f"{target} exists (use --overwrite)")
        files, skipped = collect(folder, skip)
        busy = [p.name for p in folder.rglob("*") if p.name.endswith(("-wal", "-journal"))]
        if busy:
            sys.exit(f"{folder}: {busy} found: a GeoPackage is open (QGIS?) or was not closed cleanly")
        if not files:
            sys.exit(f"{folder}: nothing to pack")
        plan.append((folder, target, files))
        log(f"[{ar['zip']}] {folder}: {len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:,.1f} MB")
        for p in files:
            log(f"    + {p.relative_to(folder)}")
        for p in skipped:
            log(f"    - {p.relative_to(folder)} (skipped)")
    if a.dry_run:
        log("dry run: nothing written")
        return
    out.mkdir(parents=True, exist_ok=True)
    for folder, target, files in plan:
        top = target.stem
        part = target.with_name(target.name + ".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=cfg.get("compresslevel", 6)) as z:
            for p in files:
                z.write(p, f"{top}/{p.relative_to(folder).as_posix()}")
        with zipfile.ZipFile(part) as z:
            bad = z.testzip()
            if bad:
                sys.exit(f"{part}: CRC error in {bad}")
        part.replace(target)
        log(f"written {target}: {target.stat().st_size / 1e6:,.1f} MB, md5 {md5(target)}")


if __name__ == "__main__":
    main()
