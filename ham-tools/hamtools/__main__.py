"""Command line for Ask Elmer Ham Tools (also handy over SSH).

  askelmer-ham-tools                         run the app (LCD + keyboard)
  askelmer-ham-tools --mhz 7.1 [--license General]   band and privileges
  askelmer-ham-tools --antennas              Antenna Lab templates
  askelmer-ham-tools --run ID [--mhz F] [--ground G] [--tune]
                                             model one antenna and print the results
  askelmer-ham-tools --deck ID [--mhz F]     print the NEC2 deck
  askelmer-ham-tools --screens DIR           render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import sys


def antenna_cli(a) -> int:
    from .lab import lab, nec
    from .lab import templates as TP
    if a.antennas:
        for t in TP.TEMPLATES:
            print(f"{t.id:16} {t.family:14} {t.name}")
        return 0
    tid = a.run or a.deck
    t = TP.by_id(tid)
    if not t:
        print(f"no antenna '{tid}' (see --antennas)", file=sys.stderr)
        return 2
    mhz = a.mhz or t.default_mhz
    p = t.defaults(mhz)
    g = nec.ground_of(a.ground)
    if a.deck:
        m = t.model(p, mhz, g)
        segs, _ = nec.segment_model(m, mhz)
        print(nec.build_deck(m, [mhz], segs), end="")
        return 0
    if a.tune:
        p, tr = lab.tune(t, p, mhz, g, "copper", t.device)
        if tr:
            print(f"tuned {t.tune['param']} = {tr[0]:.4f}")
    r = lab.run_design(t, p, mhz, g, "copper", t.device)
    print(f"{t.name} at {mhz} MHz, ground {a.ground}")
    print(f"  Z = {r.zr:.1f} {r.zi:+.1f}j ohm   SWR {r.swr:.2f} via {lab.DEVICES[t.device][0]}")
    print(f"  resonances {[round(x, 4) for x in r.resonances]}  min SWR {r.min_swr[1]:.2f} @ {r.min_swr[0]:.4f}")
    if r.gain is not None:
        print(f"  gain {r.gain:.2f} dBi  takeoff {r.takeoff:.0f} deg  F/B {r.fb:.1f}  eff {r.efficiency:.0f}%")
    for c in t.build(p, mhz).cut:
        print(f"  cut: {c.part}: {'' if c.length is None else f'{c.length:.3f} m'} {'x' + str(c.qty) if c.qty else ''}")
    for w in r.warnings + r.errors:
        print("  !", w)
    print(f"  {r.secs:.1f} s")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mhz", type=float)
    ap.add_argument("--license", default="Technician")
    ap.add_argument("--antennas", "--list", action="store_true")
    ap.add_argument("--run", metavar="ID")
    ap.add_argument("--deck", metavar="ID")
    ap.add_argument("--ground", default="average")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    if a.antennas or a.run or a.deck:
        return antenna_cli(a)
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
