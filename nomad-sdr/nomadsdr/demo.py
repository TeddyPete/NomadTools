"""Renders sample screens to PNG files (store screenshots, tests) with a
simulated signal, so no dongle is needed."""
from __future__ import annotations

import os
import time

from . import app as AP
from . import lcd as L
from . import settings as S
from .radio import Radio, fake_source


class _Kb:
    def poll(self, t):
        return []

    def close(self):
        pass


def _warm(radio, n=60):
    for _ in range(n):
        audio, flat = radio.rx.process(radio.source(12288))


def render_screens(out: str) -> list[str]:
    os.makedirs(out, exist_ok=True)
    os.environ.setdefault("XDG_CONFIG_HOME", os.path.join(out, ".cfg"))
    os.environ.setdefault("XDG_DATA_HOME", os.path.join(out, ".data"))
    panel = L.Panel(headless=True)
    cfg = dict(S.DEFAULTS, freq=146.94, mode="NFM", license="Technician", squelch=None, step=12500)
    radio = Radio(cfg, source=fake_source((60000, -40000, 95000), snr_db=28))
    radio.tuner, radio.gains = "R820T", [0.0, 9.7, 19.7, 29.7, 38.6, 49.6]
    app = AP.App(panel, _Kb(), radio)
    app.cfg.clear()
    app.cfg.update(cfg)
    app.save = lambda: None
    app.radio._apply()
    _warm(radio)
    paths = []

    def shot(name):
        app.draw()
        p = os.path.join(out, name)
        panel.save(p)
        paths.append(p)

    app.push(AP.Radio_(app))
    shot("lcd_0.png")
    app.open_bandplan()
    app.stack[-1].sel = 11
    app.stack[-1].key(type("K", (), {"name": "enter", "char": "", "ctrl": False})())
    app.stack[-1].sel = 13
    shot("lcd_1.png")
    while len(app.stack) > 1:
        app.pop()
    a = AP.Aprs_.__new__(AP.Aprs_)
    AP.Screen.__init__(a, app)
    from . import aprs as P
    a.dec = P.Aprs(to_rig=False)
    a.dec.log = os.path.join(out, ".aprs.log")
    a.sel = a.top = 0
    a.detail = None
    a.fi = 0
    a.loc = (44.98, -93.27)
    for line in ("N0TNT-9>APDR16,WIDE1-1:=4459.10N/09310.20W>Rig Companion test",
                 "KD0ABC-7>T2TP5X,WIDE1-1,WIDE2-1:!4501.55N/09328.90W[",
                 "W0DIGI>APNU19,WIDE2-1:!4510.00N/09305.00W#PHG5460 Digi",
                 "N0WX>APRS:_11281035c220s004g008t034r000h68b10165",
                 "KC0XYZ>APK102,WIDE1-1::N0TNT-9  :See you at the hamfest{01"):
        a.dec.add_line(line)
    app.cfg["freq"] = 144.39
    app.push(a)
    shot("lcd_2.png")
    app.stack.pop()
    app.cfg.update(freq=146.565, gain=29.7, mode="NFM")
    fx = AP.Fox.__new__(AP.Fox)
    AP.Screen.__init__(fx, app)
    fx.hist = [5 + 25 * (i / 150) ** 1.5 + (i % 7) for i in range(150)]
    fx.best = 33.0
    fx.f_huge, fx.f_mid = AP.font(44), AP.font(17)
    fx.saved = {}
    app.push(fx)
    shot("lcd_3.png")
    app.stack.pop()
    app.cfg.update(freq=146.94, gain=None)
    app.open_menu()
    shot("lcd_4.png")
    app.stack.pop()
    from . import nomadui as T
    app.push(AP.Info(app, T.AboutView()))
    shot("lcd_5.png")
    return paths
