"""Command line for Nomad Label Scanner (also handy over SSH).

  nomad-label-scanner                    run the app (LCD + keyboard)
  nomad-label-scanner --read IMAGE       read barcodes + label text from a photo
  nomad-label-scanner --shot             take one camera shot and read it
  nomad-label-scanner --jobs             list jobs
  nomad-label-scanner --list [JOB]       items in a job (default: current job)
  nomad-label-scanner --export [JOB]     write JOB.csv + JOB.xlsx (and All-Jobs.xlsx)
  nomad-label-scanner --find MAC|IP      find a device on the local network
  nomad-label-scanner --screens DIR      render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import sys


def _read_gray(path: str):
    import numpy as np
    from PIL import Image
    return np.asarray(Image.open(path).convert("L"))


def _show(codes, text, found) -> None:
    for sym, d in codes:
        print(f"code   {sym}: {d}")
    if text.strip():
        print("text   " + " | ".join(l.strip() for l in text.splitlines() if l.strip()))
    from . import oui
    for k in ("model", "serial", "mac", "ip"):
        v = getattr(found, k)
        if v:
            extra = f"  ({oui.vendor(v)})" if k == "mac" and oui.vendor(v) else ""
            print(f"{k:6} {v}{extra}")
    for k, v in found.others:
        print(f"other  {k}: {v}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--read", metavar="IMAGE")
    ap.add_argument("--shot", action="store_true")
    ap.add_argument("--save", metavar="PNG", help="with --shot: also save the frame")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--jobs", action="store_true")
    ap.add_argument("--list", nargs="?", const="", metavar="JOB")
    ap.add_argument("--export", nargs="?", const="", metavar="JOB")
    ap.add_argument("--find", metavar="MAC_OR_IP")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    from . import decode, parse, store
    if a.screens:
        from .demo import render_screens
        render_screens(a.screens)
        return 0
    if a.read or a.shot:
        if a.read:
            gray = _read_gray(a.read)
        else:
            import time
            from . import camera
            cam = camera.Camera(int(store.load_settings().get("rotation", 0)))
            cam.start()
            f = cam.wait_frame(0, 8)
            time.sleep(1.5)            # let exposure settle
            f = cam.wait_frame(f.seq if f else 0, 4)
            cam.stop()
            if not f:
                print("ERROR: " + (cam.error or "no frame from the camera"), file=sys.stderr)
                return 1
            gray = f.y
            if a.save:
                f.rgb_image().save(a.save)
            print(f"sharpness {decode.sharpness(gray):.0f}  brightness {gray.mean():.0f}")
        codes = decode.barcodes(gray)
        text = "" if a.no_ocr else decode.ocr(gray)
        _show(codes, text, parse.extract(codes, text))
        return 0
    cfg = store.load_settings()
    if a.jobs:
        for j in store.jobs():
            print(f"{len(store.load(j)):4}  {j}{'  (current)' if j == cfg.get('job') else ''}")
        return 0
    if a.list is not None:
        for i, it in enumerate(store.load(a.list or cfg.get("job", "")), 1):
            print(f"{i:3} {it.name or '-':16} {it.model or '-':16} {it.serial or '-':16} {it.mac or '-':17} {it.ip or '-':15} {it.online}")
        return 0
    if a.export is not None:
        from . import export
        for p in export.export_job(a.export or cfg.get("job", "")) + [export.export_all()]:
            print(p)
        return 0
    if a.find:
        from . import netfind
        mac = parse.norm_mac(a.find)
        r = netfind.check(mac, "" if mac else a.find, progress=lambda t: print("..", t, file=sys.stderr))
        for k in ("text", "ip", "mac", "iface", "host"):
            if r.get(k):
                print(f"{k:6} {r[k]}")
        return 0 if r.get("online") else 1
    from .app import main_ui
    return main_ui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
