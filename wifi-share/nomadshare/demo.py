"""Sample screens with made-up data, for store screenshots and UI checks."""
from __future__ import annotations

import os

from . import lcd as L
from . import portal
from .app import App, Home, PortalPage, WifiList


def fake_app() -> App:
    app = App(L.Panel(headless=True), None)
    app.cfg.update(hs_ssid="Nomad-Share-D428", hs_password="k7m2pq9xw4")
    app.status = dict(mode="wifi2eth", wifi="wlan0", eth="eth0", wifi_state="connected", wifi_con="Hotel Guest",
                      wifi_ip=["10.20.4.117/22"], wifi_link=dict(ssid="Hotel Guest", signal=72),
                      eth_state="connected", eth_con="nomad-share-eth", eth_ip=["192.168.50.1/24"], eth_carrier=True,
                      route=("10.20.4.1", "wlan0"),
                      clients=[dict(mac="00:05:a6:1c:22:10", ip="192.168.50.12", name="DSP-Tesira"),
                               dict(mac="00:10:7f:3a:9b:01", ip="192.168.50.14", name="CP4-Rack1"),
                               dict(mac="00:60:74:aa:01:02", ip="192.168.50.15", name="")])
    app.inet = ("online", "")
    app.status["vpn"] = ""
    app.cfg["devices"] = {"00:05:a6:1c:22:10": dict(name="DSP rack 1", reserve=True, ip="192.168.50.12",
                                                    down="Off", up="Off"),
                          "00:10:7f:3a:9b:01": dict(name="CP4 processor", reserve=True, ip="192.168.50.14",
                                                    down="Off", up="Off"),
                          "a4:83:e7:11:22:33": dict(name="Guest laptop", block=True)}
    app.cfg["forwards"] = [dict(name="DSP web", proto="tcp", port="8080", ip="192.168.50.12", to_port="80")]
    app.cfg["dns_names"] = [dict(name="dsp1.av", ip="192.168.50.12")]
    app.cfg["setup_done"] = True
    return app


def extra_screens(app):
    """The power-feature screens with sample data (for screenshots)."""
    import math
    from . import extras as X
    dash = X.Dashboard(app, live=False)
    for i in range(60):
        dash.down.append(18 + 10 * math.sin(i / 6) + (i % 7))
        dash.up.append(2 + 1.5 * math.cos(i / 5))
    dash.ping_ms, dash.links = 3.4, "Wi-Fi 72% 65 Mb/s  Eth 1 Gb/s"
    sw = X.SwitchPort(app)
    sw.nbrs = [dict(switch="M4250-AV-Rack1", port="1/0/12 Stage left", port_id="12", vlan="20",
                    vlan_name="AV-Control", mgmt="10.20.0.2", desc="", caps="", dev="eth0")]
    wiz = X.Wizard(app)
    return [("dashboard", dash), ("devices", X.Devices(app)), ("switch", sw), ("forwards", X.Forwards(app)),
            ("settings", X.SettingsMenu(app)), ("wizard", wiz), ("vpn", X.Vpn(app))]


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

    extra = dict(extra_screens(app))
    shot(Home(app), "lcd_0.png")
    shot(extra["dashboard"], "lcd_1.png")
    shot(extra["devices"], "lcd_2.png")
    shot(extra["switch"], "lcd_3.png")
    nets = [dict(ssid="Hotel Guest", signal=72, security="", chan="6", active=True, saved=True),
            dict(ssid="Venue-Staff", signal=64, security="WPA2", chan="11", active=False, saved=False),
            dict(ssid="Ballroom AV", signal=51, security="WPA2", chan="1", active=False, saved=True),
            dict(ssid="xfinitywifi", signal=33, security="", chan="6", active=False, saved=False)]
    shot(WifiList(app, nets), "lcd_4.png")
    page = portal.parse(SAMPLE_PORTAL, "http://portal.example/login")
    app.status["mode"] = None
    shot(PortalPage(app, page), "lcd_5.png")
    for f in files:
        print(f)
    return files
