"""Render sample screens to PNG (store screenshots, and checking layouts without a device)."""
from __future__ import annotations

import os


def render_screens(out_dir: str) -> list:
    os.environ["XDG_CONFIG_HOME"] = os.path.join(out_dir, ".cfg")
    from . import lcd as L
    from .app import App, BandPlan, Clock, Coax, Frequency, Grid, Home, Ohms, Swr
    os.makedirs(out_dir, exist_ok=True)
    panel = L.Panel(headless=True)
    app = App(panel, None)
    app.st.d = {"license": "General"}
    files = []

    def shot(name, s=None):
        if s is not None:
            app.stack = app.stack[:1] + [s]
        app.draw()
        p = os.path.join(out_dir, f"{name}.png")
        panel.save(p)
        files.append(p)

    app.push(Home(app))
    shot("lcd_0_home")
    fr = Frequency(app)
    fr.values.update({"MHz": "7.074", "lic": "General"})
    fr.build()
    fr.form.sel = 4
    shot("lcd_1_frequency", fr)
    bp = BandPlan(app)
    bp.sel = 3
    shot("lcd_2_bandplan", bp)
    co = Coax(app)
    co.form.sel = 6
    shot("lcd_3_coax", co)
    g = Grid(app)
    g.form.sel = 5
    shot("lcd_4_grid", g)
    shot("lcd_5_clock", Clock(app))
    shot("lcd_x_ohms", Ohms(app))
    shot("lcd_x_swr", Swr(app))
    return files
