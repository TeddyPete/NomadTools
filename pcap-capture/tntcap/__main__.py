"""Command line for TNT Packet Capture.

  python3 -m tntcap                   run the app (LCD + keyboard)
  python3 -m tntcap --status          print the capture state
  python3 -m tntcap --start [--preset dante] [--iface eth0] [--seconds 60] [--mb 100]
                                      start a capture with no UI
  python3 -m tntcap --start --tap [eth1]   inline tap: bridge built-in + USB adapter
  python3 -m tntcap --viewer          desktop live viewer (HDMI)
  python3 -m tntcap --stop            stop the running capture
  python3 -m tntcap --list            list saved captures
  python3 -m tntcap --presets         show the filter presets
  python3 -m tntcap --screens DIR     render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--supervise", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--autotap", metavar="IFACE", help=argparse.SUPPRESS)
    ap.add_argument("--viewer", action="store_true", help="desktop live viewer window (HDMI)")
    ap.add_argument("--tap", metavar="ADAPTER", nargs="?", const="", help="with --start: inline tap mode")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--presets", action="store_true")
    ap.add_argument("--preset")
    ap.add_argument("--iface")
    ap.add_argument("--host")
    ap.add_argument("--port")
    ap.add_argument("--filter", help="custom tcpdump filter (sets preset custom)")
    ap.add_argument("--seconds", type=int)
    ap.add_argument("--mb", type=int)
    ap.add_argument("--headers", action="store_true", help="save headers only")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    from . import capture as C
    if a.supervise:
        return C.supervise()
    if a.autotap:
        return C.autotap(a.autotap)
    if a.viewer:
        from .viewer import main as viewer_main
        return viewer_main()
    if a.status:
        print(json.dumps(C.read_state(), indent=1))
        return 0
    if a.stop:
        st = C.stop()
        print(json.dumps({k: st.get(k) for k in ("running", "reason", "packets", "drops", "bytes", "files")}))
        return 0
    if a.list:
        from . import files as F
        for s in F.listing():
            print(f"{F.nice_size(s.size):>9}  {s.path}")
        return 0
    if a.presets:
        for key, label, short, expr, help_ in C.PRESETS:
            print(f"{key:10} {label}\n           {expr if expr is not None else '(your filter)'}")
        return 0
    if a.start:
        from . import settings as S
        cfg = S.load()
        if a.preset:
            cfg["preset"] = a.preset
        if a.filter:
            cfg["preset"], cfg["custom"] = "custom", a.filter
        for k in ("iface", "host", "port"):
            if getattr(a, k) is not None:
                cfg[k] = getattr(a, k)
        if a.seconds is not None:
            cfg["duration"] = f"{a.seconds} s" if a.seconds else "No limit"
        if a.mb:
            cfg["size"] = f"{a.mb} MB"
        if a.tap is not None:
            cfg["capmode"], cfg["tap_adapter"] = "Inline tap", a.tap
        if a.headers:
            cfg["snap"] = "Headers only"
        try:
            job = C.start(cfg)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(json.dumps(job))
        return 0
    if a.screens:
        from .demo import render_screens
        render_screens(a.screens)
        return 0
    from .app import main_ui
    return main_ui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
