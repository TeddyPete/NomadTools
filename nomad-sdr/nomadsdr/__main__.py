"""Command line for Nomad SDR (also handy over SSH).

  nomad-sdr                    run the app (LCD + keyboard)
  nomad-sdr --seconds 60       run the app and quit after 60 s (testing)
  nomad-sdr --probe            show the dongle, tuner and gain steps
  nomad-sdr --level MHZ [S]    print the signal level at MHZ for S seconds
  nomad-sdr --screens DIR      render sample LCD screens to PNG (no dongle needed)
"""
from __future__ import annotations

import argparse
import sys
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--level", nargs="+", metavar="X")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    if a.screens:
        from .demo import render_screens
        render_screens(a.screens)
        return 0
    if a.probe:
        from . import rtl
        for d in rtl.devices():
            print(d)
        try:
            r = rtl.Rtl(0)
        except rtl.RtlError as e:
            print("ERROR:", e)
            return 1
        print("tuner", r.tuner, "bias-tee", r.has_bias_tee)
        print("gains", r.gains)
        r.close()
        return 0
    if a.level:
        from . import settings
        from .radio import Radio
        cfg = settings.load()
        cfg.update(freq=float(a.level[0]))
        r = Radio(cfg)
        r.out.write = lambda pcm: None
        r.start()
        end = time.time() + (float(a.level[1]) if len(a.level) > 1 else 5)
        while time.time() < end:
            time.sleep(0.5)
            rx = r.rx
            print(f"{r.freq:.4f} MHz  level {rx.level:6.1f} dBFS  noise {rx.noise:6.1f}  "
                  f"snr {rx.level - rx.noise:+5.1f} dB  {r.status} {r.error}", flush=True)
        r.stop()
        return 0
    from .app import main_ui
    return main_ui(a.seconds)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
