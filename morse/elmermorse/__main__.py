"""Command line for Ask Elmer Morse.

  askelmer-morse                       run the app (LCD + keyboard + GPIO paddle)
  askelmer-morse --encode "CQ DE N0TNT"   print dots and dashes
  askelmer-morse --decode-audio [DEV]  decode CW from an audio input to the terminal
  askelmer-morse --screens DIR         render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import sys
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--encode")
    ap.add_argument("--decode-audio", nargs="?", const="plughw:CARD=ES8389Audio,DEV=0", metavar="DEV")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    if a.encode:
        from . import morse as M
        print(M.encode(a.encode))
        return 0
    if a.decode_audio:
        from .cwdecode import CwDecoder
        d = CwDecoder(a.decode_audio)
        d.start()
        end = time.monotonic() + a.seconds
        last = ""
        while time.monotonic() < end and (d.running or not d.error):
            time.sleep(0.5)
            line = d.line()
            if line != last:
                print(f"[{d.tone:.0f} Hz {d.wpm:.0f} WPM] {line}", flush=True)
                last = line
        d.stop()
        if d.error:
            print(d.error, file=sys.stderr)
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
