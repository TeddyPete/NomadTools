"""Sample screens with made-up data (store screenshots, UI checks), and a
synthetic gear label for testing the read pipeline without a camera."""
from __future__ import annotations

import os
import time

import numpy as np

from . import camera as C
from . import lcd as L
from . import parse, qr, store
from .app import App, Home, Inventory, ItemScreen, ScanScreen, ShareScreen

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def label_image(w: int = C.W, h: int = C.H, qr_text: str = "SN:1904ABC1234;MAC:00107F3A9C21"):
    """A white equipment sticker on a dark rack, like the camera would see it."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (w, h), (38, 40, 46))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = int(w * 0.06), int(h * 0.08), int(w * 0.94), int(h * 0.92)
    d.rounded_rectangle((x0, y0, x1, y1), 18, fill=(242, 242, 236))
    big = ImageFont.truetype(FONT, 50) if os.path.exists(FONT) else ImageFont.load_default()
    mono = ImageFont.truetype(MONO, 44) if os.path.exists(MONO) else big
    d.text((x0 + 40, y0 + 30), "CRESTRON", font=big, fill=(20, 20, 20))
    lines = ["MODEL: DM-NVX-360", "S/N: 1904ABC1234", "MAC: 00.10.7F.3A.9C.21", "Made in China"]
    for i, t in enumerate(lines):
        d.text((x0 + 40, y0 + 120 + i * 62), t, font=mono, fill=(25, 25, 25))
    m = qr.matrix(qr_text)
    n = len(m) + 4
    s = (y1 - y0 - 80) // n
    qx, qy = x1 - n * s - 50, y0 + 40
    d.rectangle((qx, qy, qx + n * s, qy + n * s), fill=(255, 255, 255))
    for r, row in enumerate(m):
        for c, v in enumerate(row):
            if v:
                d.rectangle((qx + (c + 2) * s, qy + (r + 2) * s, qx + (c + 3) * s - 1, qy + (r + 3) * s - 1), fill=(0, 0, 0))
    return img


def frame_from_image(img) -> C.Frame:
    ycc = img.convert("YCbCr")
    y, u, v = (np.asarray(p) for p in ycc.split())
    buf = y.tobytes() + u[::2, ::2].tobytes() + v[::2, ::2].tobytes()
    return C.Frame(1, buf, time.monotonic())


def fake_app() -> App:
    app = App(L.Panel(headless=True), None)
    app.cfg.update(job="Hotel Ballroom", ocr=True, room="Ballroom")
    items = [
        store.Item("Stage DSP", "TesiraFORTE AI", "2219A0123", "00:90:5E:4B:11:02", "Biamp Systems", "10.10.20.15",
                   "Ballroom", online="online 0.8 ms"),
        store.Item("Rack NVX 1", "DM-NVX-360", "1904ABC1234", "00:10:7F:3A:9C:21", "Crestron Electronics", "10.10.20.41",
                   "Ballroom", online="online 1.2 ms"),
        store.Item("Rack NVX 2", "DM-NVX-360", "1904ABC1302", "00:10:7F:3A:9C:5E", "Crestron Electronics", "",
                   "Ballroom", online="not found"),
        store.Item("Wireless rx", "ULXD4Q", "3HG2210045", "00:0E:DD:2C:71:90", "Shure", "10.10.20.60", "Ballroom"),
        store.Item("PoE switch", "M4250-26G4F", "6LR1234567", "94:18:65:01:AB:CD", "NETGEAR", "10.10.20.2", "Rack"),
    ]
    app.items = items
    return app


def render_screens(out_dir: str) -> list[str]:
    import pygame
    os.makedirs(out_dir, exist_ok=True)
    app = fake_app()
    out = []

    def snap(screen, name):
        app.stack = [screen]
        app.draw()
        p = os.path.join(out_dir, name)
        pygame.image.save(app.panel.surf, p)
        out.append(p)

    snap(Home(app), "lcd_0.png")
    sc = ScanScreen.__new__(ScanScreen)
    sc.app, sc.live, sc.decoding, sc.last_seq, sc.sharp, sc.paused, sc.bright = app, {}, False, 0, 80.0, False, 128.0
    sc.started = time.monotonic()
    sc.live["SN:1904ABC1234;MAC:00107F3A9C21"] = ("QRCODE", time.monotonic())
    app.cam.frame = frame_from_image(label_image())
    app.cam.proc = None
    snap(sc, "lcd_1.png")
    found = parse.extract([("QRCODE", "SN:1904ABC1234;MAC:00107F3A9C21")],
                          "CRESTRON\nMODEL: DM-NVX-360\nS/N: 1904ABC1234\nMAC: 00.10.7F.3A.9C.21")
    it = store.Item(model=found.model, serial=found.serial, mac=found.mac, vendor="Crestron Electronics",
                    ip="10.10.20.41", room="Ballroom", online="online 1.2 ms", codes=["SN:1904ABC1234;MAC:00107F3A9C21"])
    snap(ItemScreen(app, it, found=found), "lcd_2.png")
    snap(Inventory(app), "lcd_3.png")
    app.share.srv = object()      # draw the "on" state without opening a port
    app.share.port = 8082
    import nomadscan.netfind as nf
    real = nf.local_nets
    nf.local_nets = lambda: [("eth0", "10.10.20.24", None)]
    try:
        sh = ShareScreen.__new__(ShareScreen)
        sh.app, sh.pick = app, 0
        snap(sh, "lcd_4.png")
    finally:
        nf.local_nets = real
        app.share.srv = None
    return out
