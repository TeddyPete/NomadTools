"""Render sample screens to PNG (store screenshots, checks on a PC)."""
from __future__ import annotations

import os
import time
from collections import Counter

from . import app as A
from . import lcd as L
from .keys import Key


def _app():
    panel = L.Panel(headless=True)
    app = A.App(panel, None)
    app.cfg.update(iface="eth0", preset="dante", duration="15 min", size="500 MB")
    return app


def fake_running(app):
    job = {"iface": "eth0", "filter": "x", "preset": "dante", "preset_name": "Dante (all)", "ring": False,
           "max_mb": 500, "seconds": 900, "file": "/tmp/x.pcap"}
    app.state = {"running": True, "job": job, "elapsed": 83, "packets": 48213, "drops": 0, "bytes": 21_400_000,
                 "pps": 612, "bps": 2_050_000, "files": ["/tmp/x.pcap"]}
    fl = app.follower
    fl.protos = Counter({"Dante audio": 30120, "PTP": 9400, "Dante ctl": 4100, "mDNS": 2300, "ARP": 900,
                         "IGMP": 400})
    fl.talkers = Counter({"192.168.51.60": 18000, "192.168.51.61": 12500, "192.168.51.249": 3100})
    fl.seen = sum(fl.protos.values())


def render_screens(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    app = _app()
    app.poll = lambda: None   # keep the fake state
    n = 0

    def shot():
        nonlocal n
        app.draw()
        app.panel.save(os.path.join(out_dir, f"lcd_{n}.png"))
        n += 1

    app.push(A.Home(app))
    fake_running(app)
    shot()                                   # 0 home while recording
    app.push(A.LiveView(app))
    shot()                                   # 1 live counters
    app.stack[-1].key(Key("pagedown"))
    shot()                                   # 2 protocols
    app.pop()
    app.push(A.FilterMenu(app))
    shot()                                   # 3 filter presets
    app.pop()
    A.open_settings(app)
    shot()                                   # 4 settings
    app.pop()
    app.state = {}
    app.push(A.ShareScreen(app))
    app.stack[-1].addrs = {"wlan0": "192.168.51.24"}
    shot()                                   # 5 share (QR)
    app.share.stop()
    app.pop()
    app.push(A.ModeMenu(app))
    shot()                                   # 6 mode
    app.pop()
    from . import files as F
    app.push(A.UsbFound(app, "/media/pi/STICK", [F.Saved("/x.pcap", 21_400_000, time.time(), {})] * 3))
    shot()                                   # 7 usb stick found
