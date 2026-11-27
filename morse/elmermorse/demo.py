"""Render sample screens to PNG (store screenshots, and checking layouts without a device)."""
from __future__ import annotations

import os


def render_screens(out_dir: str) -> list:
    os.environ["XDG_CONFIG_HOME"] = os.path.join(out_dir, ".cfg")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from . import lcd as L
    from . import nomadui as T
    from .app import App, CopyGame, Decoder, Home, Hunt, KeyScreen, Progress, SendGame, Trainer
    os.makedirs(out_dir, exist_ok=True)
    panel = L.Panel(headless=True)
    app = App(panel, None)
    st = app.store
    st.learned, st.introduced = 14, 14
    for c in st.chars:
        st.stats[c] = [1] * 9 + [0]
    st.window = [1] * 40 + [0] * 3
    files = []

    def shot(name, s=None):
        if s is not None:
            for old in app.stack[1:]:
                old.leave()
            app.stack = app.stack[:1] + [s]
        app.draw()
        p = os.path.join(out_dir, f"{name}.png")
        panel.save(p)
        files.append(p)

    app.push(Home(app))
    shot("lcd_0_home")
    tr = Trainer(app)
    tr.cur, tr.typed, tr.next_at = "R", "R", 1e12
    tr.msg, tr.msg_color = "Right!", T.OK
    shot("lcd_1_learn", tr)
    cg = CopyGame(app)
    cg.msg, cg.round, cg.eff = "TU 73 ES", 3, 10
    import random
    from . import morse as M
    cg.msg = "PSE QRS"
    cg.expect = M.chars_of(cg.msg)
    for c in "PSEQ":
        cg.typed.append((c, True))
    cg.typed.append(("S", False))
    cg.pos, cg.score, cg.misses = 5, 17, 1
    cg.note, cg.note_color = "Missed R  ·−·", T.BAD
    shot("lcd_2_copy", cg)
    sg = SendGame(app)
    sg.word = "PARK"
    sg.score = 5
    sg.note, sg.note_color = "Sent TEST! 14 WPM  fist 86", T.OK
    shot("lcd_3_send", sg)
    h = Hunt(app)
    h.hour, h.miles, h.band_i = 14, 1200, 3
    shot("lcd_4_hunt", h)
    ks = KeyScreen(app)
    ks.text = "CQ CQ DE N0TNT N0TNT K"
    shot("lcd_5_key", ks)
    dec = Decoder(app)
    dec.dec.stop()
    dec.dec.tone, dec.dec.level, dec.dec.running = 640, 0.7, True
    dec.dec.dec.dit = 1200 / 18
    dec.last = "CQ POTA DE K0ABC K0ABC K  N0TNT TU UR 5NN MN MN BK"
    shot("lcd_6_decoder", dec)
    shot("lcd_x_progress", Progress(app))
    for s in app.stack[1:]:
        s.leave()
    random.seed(0)
    return files
