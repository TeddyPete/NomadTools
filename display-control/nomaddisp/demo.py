"""Sample screens with made-up data, for store screenshots and UI checks."""
from __future__ import annotations

import os

from . import lcd as L
from .app import App, DisplayScreen, Found, Home, Pick, RoomScreen, Rooms
from .base import Display


def fake_app() -> App:
    app = App(L.Panel(headless=True), None)
    app.displays = [
        Display("Ballroom A proj", "pjlink", "10.10.20.31", mac="00:21:a0:11:22:33", room="Ballroom", id="p1"),
        Display("Ballroom B proj", "pjlink", "10.10.20.32", mac="00:21:a0:11:22:34", room="Ballroom", id="p2"),
        Display("Lobby LG 65", "lg", "10.10.20.50", mac="30:34:db:6e:bc:84", room="Lobby", secret="k", id="l1"),
        Display("Boardroom Sony", "sony", "10.10.20.61", room="Boardroom", secret="1234", id="s1"),
        Display("Green room Roku", "roku", "10.10.20.70", room="Green room", id="r1"),
        Display("Bar Samsung", "samsung", "10.10.20.80", room="Lobby", id="m1"),
    ]
    app.state = {"p1": {"power": "on", "input": "Digital 1", "mute": False, "avmute": False},
                 "p2": {"power": "warming", "input": "Digital 1"},
                 "l1": {"power": "on", "input": "HDMI 2", "volume": 14, "mute": False},
                 "s1": {"power": "standby"}, "r1": {"power": "on", "input": "HDMI 1"},
                 "m1": {"power": "off"}}
    return app


def render_screens(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    app = fake_app()
    files = []

    def shot(screen, name, sel=0):
        screen.sel = sel
        app.stack = [screen]
        app.draw()
        fn = os.path.join(out_dir, name)
        app.panel.save(fn)
        files.append(fn)

    shot(Home(app), "lcd_0.png")
    shot(DisplayScreen(app, app.displays[2]), "lcd_1.png")
    shot(RoomScreen(app, "Ballroom"), "lcd_2.png")
    found = [Display("Epson EB-L1505U", "pjlink", "10.10.20.31", model="EPSON EB-L1505U"),
             Display("LG TV", "lg", "10.10.20.50", model="webOS"),
             Display("Sony FW-65BZ40H", "sony", "10.10.20.61"),
             Display("Green room Roku", "roku", "10.10.20.70")]
    app.displays = app.displays[:3]
    shot(Found(app, found), "lcd_3.png", 1)
    app.displays = fake_app().displays
    shot(Pick(app, "Input", [("HDMI_1", "HDMI 1"), ("HDMI_2", "HDMI 2 (Laptop)"), ("HDMI_3", "HDMI 3"),
                              ("HDMI_4", "HDMI 4")], lambda v: None, "HDMI_2"), "lcd_4.png", 1)
    shot(Rooms(app), "lcd_5.png")
    for f in files:
        print(f)
    return files
