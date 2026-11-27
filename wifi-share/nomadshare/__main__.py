"""Command line for Nomad WiFi Share.

  python3 -m nomadshare                 run the app (LCD + keyboard)
  python3 -m nomadshare --status        print network status
  python3 -m nomadshare --check         internet / captive portal check
  python3 -m nomadshare --restore       undo everything the app changed
  python3 -m nomadshare --start wifi2eth|hotspot --revert-after 90
                                      start a mode with no UI, then restore
                                      after N seconds (safe remote testing)
  python3 -m nomadshare --screens DIR   render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--start", choices=["wifi2eth", "hotspot"])
    ap.add_argument("--revert-after", type=int, default=90, help="seconds before restoring (with --start)")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    from . import net
    if a.status:
        print(json.dumps(net.status(), indent=1))
        return 0
    if a.check:
        from . import portal
        print(portal.check())
        return 0
    if a.restore:
        if not net.needs_restore():
            print("nothing to restore")
            return 0
        msgs = net.restore()
        print("restored" if not msgs else "done")
        return 0
    if a.start:
        return headless(a.start, a.revert_after)
    if a.screens:
        from .demo import render_screens
        render_screens(a.screens)
        return 0
    from .app import main_ui
    return main_ui()


def headless(mode: str, seconds: int) -> int:
    from . import net
    from . import settings as S
    stop = {"now": False}

    def on_sig(*_):
        stop["now"] = True
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, on_sig)
    cfg = S.load()
    ts = lambda: time.strftime("%H:%M:%S")
    print(f"{ts()} before: {json.dumps(net.status())}", flush=True)
    try:
        fn = net.start_wifi_to_eth if mode == "wifi2eth" else net.start_hotspot
        print(f"{ts()} start {mode}: {fn(cfg)}", flush=True)
        end = time.monotonic() + seconds
        while time.monotonic() < end and not stop["now"]:
            time.sleep(5)
            st = net.status()
            print(f"{ts()} {st.get('mode')} wifi={st.get('wifi_state')}/{st.get('wifi_con')} {st.get('wifi_ip')} "
                  f"eth={st.get('eth_state')}/{st.get('eth_con')} {st.get('eth_ip')} clients={len(st.get('clients', []))}",
                  flush=True)
    except Exception as e:
        print(f"{ts()} ERROR: {e}", flush=True)
    finally:
        msgs = net.restore()
        print(f"{ts()} restored: {msgs}", flush=True)
        print(f"{ts()} after: {json.dumps(net.status())}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
