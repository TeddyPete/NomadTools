"""Render sample screens to PNG (store screenshots, and checking layouts without a device)."""
from __future__ import annotations

import os


def render_screens(out_dir: str) -> list:
    os.environ.setdefault("XDG_CONFIG_HOME", os.path.join(out_dir, ".cfg"))
    from . import lcd as L
    from . import templates as TP
    from .app import App, Design, Family, Home, Pattern, Results, SwrChart, CutList
    os.makedirs(out_dir, exist_ok=True)
    panel = L.Panel(headless=True)
    app = App(panel, None)
    app.st.units = "ft"
    files = []

    def shot(name):
        app.draw()
        p = os.path.join(out_dir, f"{name}.png")
        panel.save(p)
        files.append(p)

    app.push(Home(app))
    shot("lcd_0_home")
    app.push(Family(app, "Beams"))
    shot("lcd_x_family")
    t = TP.by_id("moxon")
    d = Design(app, t)
    d.mhz = 14.175
    d.p = t.defaults(14.175)
    d.build_form()
    app.push(d)
    shot("lcd_1_design")
    from . import lab, nec
    d.result = lab.run_design(t, d.p, d.mhz, nec.ground_of("average"), "copper", d.device)
    app.push(Results(app, d))
    shot("lcd_2_results")
    app.pop()
    app.push(SwrChart(app, d))
    shot("lcd_3_swr")
    app.pop()
    app.push(Pattern(app, d))
    shot("lcd_4_pattern")
    app.pop()
    app.push(CutList(app, d))
    shot("lcd_5_cut")
    app.pop()
    # 0.2: feed line loss in the results, a measured sweep over the model, the beam optimizer
    from . import extras as X
    from .app import Optimized
    app.st.cable, app.st.cable_ft = "RG-8X", 75
    r = d.result
    app.measured[t.id] = [(f, s * 1.08 + 0.05, 0, 0) for f, s, _zr, _zi in r.sweep]
    rs = Results(app, d)
    rs.top = 8
    app.push(rs)
    shot("lcd_x_feedline")
    app.pop()
    app.push(SwrChart(app, d))
    shot("lcd_6_measured")
    app.pop()
    y = TP.by_id("yagi")
    dy = Design(app, y)
    dy.mhz = 14.15
    dy.p = TP.yagi_defaults(14.15, 3)
    res = X.optimize_beam(y, dy.p, 14.15, "copper", "Balanced", rounds=6)
    app.push(Optimized(app, dy, res))
    shot("lcd_7_optimize")
    return files
