"""Command line for Ask Elmer Shack Tools.

  askelmer-shack-tools                    run the app (LCD + keyboard)
  askelmer-shack-tools --mhz 7.1 [--license General]   band and privileges
  askelmer-shack-tools --screens DIR      render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mhz", type=float)
    ap.add_argument("--license", default="Technician")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    if a.mhz:
        from . import calc as C
        band, seg, text = C.privilege(a.mhz, a.license)
        print(f"{a.mhz} MHz: {band.name if band else 'no band'}; {a.license}: {text}; "
              f"wavelength {C.fmt(C.wavelength_m(a.mhz))} m")
        return 0
    if a.screens:
        from .demo import render_screens
        for f in render_screens(a.screens):
            print(f)
        return 0
    from .app import main_ui
    return main_ui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
