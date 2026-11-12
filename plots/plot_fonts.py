"""Fonts shipped with the plot scripts (plots/fonts), the same look on every platform.

Fira Sans (SIL OFL, fonts/OFL.txt) and TeX Gyre Heros (Helvetica clone, GUST Font License, fonts/GUST-FONT-LICENSE.txt).
Presets: "default" / "fira" = Fira Sans, "helvetica" = TeX Gyre Heros; any other value is an installed family name.
Imports matplotlib only (no backend choice), so interactive scripts can use it too.
"""
from pathlib import Path

import matplotlib
from matplotlib import font_manager

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_PRESETS = {"default": "Fira Sans", "fira": "Fira Sans", "helvetica": "TeX Gyre Heros"}


def set_font(family, log=print, fallback="DejaVu Sans"):
    """Register the shipped fonts and use `family` (a preset or an installed family) for all text. Returns the family
    in use (`fallback` when it is not found)."""
    family = FONT_PRESETS.get(str(family).lower(), family)
    for f in sorted(FONT_DIR.glob("*.[ot]tf")):
        font_manager.fontManager.addfont(str(f))
    if family not in {f.name for f in font_manager.fontManager.ttflist}:
        log(f"font {family!r} not found (plots/fonts or system), {fallback} used")
        family = fallback
    matplotlib.rcParams["font.family"] = family
    return family
