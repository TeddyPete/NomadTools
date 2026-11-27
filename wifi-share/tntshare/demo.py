"""Sample screens with made-up data, for store screenshots and UI checks."""
from __future__ import annotations

import os

from . import lcd as L
from . import portal
from .app import App, Home, PortalPage, Status, WifiList


def fake_app() -> App:
    app = App(L.Panel(headless=True), None)
    app.cfg.update(hs_ssid="TNT-Share-D428", hs_password="k7m2pq9xw4")
    app.status = dict(mode="wifi2eth", wifi="wlan0", eth="eth0", wifi_state="connected", wifi_con="Hotel Guest",
                      wifi_ip=["10.20.4.117/22"], wifi_link=dict(ssid="Hotel Guest", signal=72),
                      eth_state="connected", eth_con="tnt-share-eth", eth_ip=["192.168.50.1/24"], eth_carrier=True,
                      route=("10.20.4.1", "wlan0"),
                      clients=[dict(mac="00:05:a6:1c:22:10", ip="192.168.50.12", name="DSP-Tesira"),
                               dict(mac="00:10:7f:3a:9b:01", ip="192.168.50.14", name="CP4-Rack1"),
                               dict(mac="00:60:74:aa:01:02", ip="192.168.50.15", name="")])
    app.inet = ("online", "")
    return app


SAMPLE_PORTAL = """<html><head><title>Hotel Guest WiFi</title></head><body>
<h1>Welcome</h1><form method="post" action="/login">
<input type="hidden" name="token" value="abc">
<label for="room">Room number</label><input id="room" name="room" required>
<input type="checkbox" name="tos" id="tos" required><label for="tos">I accept the terms</label>
<button type="submit">Connect</button></form></body></html>"""


def render_screens(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    app = fake_app()
    files = []

    def shot(screen, name):
        app.stack = [screen]
        app.draw()
        fn = os.path.join(out_dir, name)
        app.panel.save(fn)
        files.append(fn)

    shot(Home(app), "lcd_0.png")
    shot(Status(app), "lcd_1.png")
    nets = [dict(ssid="Hotel Guest", signal=72, security="", chan="6", active=True, saved=True),
            dict(ssid="Venue-Staff", signal=64, security="WPA2", chan="11", active=False, saved=False),
            dict(ssid="Ballroom AV", signal=51, security="WPA2", chan="1", active=False, saved=True),
            dict(ssid="xfinitywifi", signal=33, security="", chan="6", active=False, saved=False)]
    shot(WifiList(app, nets), "lcd_2.png")
    page = portal.parse(SAMPLE_PORTAL, "http://portal.example/login")
    app.status["mode"] = None
    shot(PortalPage(app, page), "lcd_3.png")
    for f in files:
        print(f)
    return files
