"""Render sample screens to PNG (store screenshots, and checking layouts without a device)."""
from __future__ import annotations

import json
import os
import shutil
import time

SOLAR_XML = """<solar><solardata><updated> 27 Nov 2026 1612 GMT</updated><solarflux>87</solarflux>
<aindex> 4</aindex><kindex> 0</kindex><xray>B2.5</xray><sunspots>26</sunspots><geomagfield>INACTIVE</geomagfield>
<signalnoise>S0-S1</signalnoise><calculatedconditions>
<band name="80m-40m" time="day">Good</band><band name="30m-20m" time="day">Fair</band>
<band name="17m-15m" time="day">Poor</band><band name="12m-10m" time="day">Poor</band>
<band name="80m-40m" time="night">Good</band><band name="30m-20m" time="night">Fair</band>
<band name="17m-15m" time="night">Poor</band><band name="12m-10m" time="night">Poor</band>
</calculatedconditions></solardata></solar>"""

SPOTS = [
    {"activator": "KN6UDK", "frequency": "14035.5", "mode": "CW", "reference": "US-12114",
     "name": "Chuckwalla National Monument", "locationDesc": "US-CA", "grid6": "DM23ao", "latitude": 33.619,
     "longitude": -115.999, "spotTime": "2026-11-27T16:05:54", "comments": "RBN 13 dB 25 WPM"},
    {"activator": "W1ABC", "frequency": "7255", "mode": "SSB", "reference": "US-2120",
     "name": "Gillette Castle State Park", "locationDesc": "US-CT", "grid6": "FN31ui", "latitude": 41.42,
     "longitude": -72.43, "spotTime": "2026-11-27T16:12:10", "comments": "QRT soon"},
    {"activator": "K4XYZ", "frequency": "14074", "mode": "FT8", "reference": "US-4567",
     "name": "Shenandoah National Park", "locationDesc": "US-VA", "grid6": "FM08rn", "latitude": 38.53,
     "longitude": -78.44, "spotTime": "2026-11-27T16:09:00", "comments": ""},
]

PARKS = [["US-2120", "Gillette Castle State Park", "US-CT", 41.42, -72.43],
         ["US-1689", "Hammonasset Beach State Park", "US-CT", 41.26, -72.55],
         ["US-1703", "Sleeping Giant State Park", "US-CT", 41.42, -72.90],
         ["US-1680", "Devil's Hopyard State Park", "US-CT", 41.48, -72.34],
         ["US-0711", "Weir Farm National Historical Park", "US-CT", 41.26, -73.45],
         ["US-1700", "Talcott Mountain State Park", "US-CT", 41.83, -72.79]]


class FakeGps:
    def fix(self):
        return None

    def last(self):
        return None

    def utc(self):
        return time.time()

    def status(self):
        return "No GPS"

    def clock_offset(self):
        return None

    def close(self):
        pass


def render_screens(out_dir: str) -> list:
    cfg = os.path.join(out_dir, ".cfg")
    os.environ["XDG_CONFIG_HOME"] = cfg
    from . import lcd as L
    from . import online
    from .app import (App, Attenuator, BandCheck, Clock, Counter, Home, MufChart, Nearby, PassView, Power,
                      Propagation, Reference, RfMath, Satellites, Search, Spots, Toroid, Where)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(online.cache_dir(), exist_ok=True)
    d = online.parse_solar(SOLAR_XML)
    d["fetched"] = time.time()
    json.dump(d, open(os.path.join(online.cache_dir(), "solar.json"), "w"))
    json.dump({"fetched": time.time(), "spots": SPOTS}, open(os.path.join(online.cache_dir(), "pota_spots.json"), "w"))
    json.dump({"fetched": time.time(), "lat": 41.71, "lon": -72.73, "items": PARKS},
              open(os.path.join(online.cache_dir(), "parks.json"), "w"))
    panel = L.Panel(headless=True)
    app = App(panel, None, FakeGps())
    app.st.d = {"license": "General", "settings": {"grid": "FN31pr", "call": "N0TNT", "units": "mi",
                                                    "id_on": True, "id_last": time.time() - 412}}
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
    bc = BandCheck(app)
    bc.values.update({"MHz": "7.074"})
    bc.build()
    shot("lcd_1_band", bc)
    shot("lcd_x_rfmath", RfMath(app))
    shot("lcd_x_power", Power(app))
    to = Toroid(app)
    shot("lcd_x_toroid", to)
    shot("lcd_x_atten", Attenuator(app))
    w = Where(app)
    w.form.top = 1
    shot("lcd_2_where", w)
    shot("lcd_3_prop", Propagation(app))
    shot("lcd_x_muf", MufChart(app, 87))
    sa = Satellites(app)
    shot("lcd_4_sats", sa)
    if sa.passes:
        b, p = sa.passes[0]
        shot("lcd_x_pass", PassView(app, b, p))
    shot("lcd_x_spots", Spots(app))
    shot("lcd_5_parks", Nearby(app, "parks"))
    app.st.d["activation"] = {"ref": "US-2120", "name": "Gillette Castle State Park",
                              "started": time.time() - 3000, "times": [time.time() - 2900 + i * 300 for i in range(7)]}
    shot("lcd_6_counter", Counter(app))
    shot("lcd_7_clock", Clock(app))
    se = Search(app)
    se.values["q"] = "qr"
    se.build()
    shot("lcd_x_search", se)
    shot("lcd_x_reference", Reference(app))
    if shutil.which("nec2c"):
        files += render_lab(app, shot)
    return files


def render_lab(main, shot) -> list:
    """Antenna Lab screens (needs nec2c)."""
    from .lab import lab, nec
    from .lab import templates as TP
    from .lab.screens import (CutList, Design, Family, Home, Optimized, Pattern, Pattern3D, Results, SwrChart,
                              context)
    from .lab import extras as X
    app = context(main)
    app.st.units = "ft"
    shot("lcd_a0_lab", Home(app))
    shot("lcd_ax_family", Family(app, "Beams"))
    t = TP.by_id("moxon")
    d = Design(app, t, 14.175)
    shot("lcd_a1_design", d)
    d.result = lab.run_design(t, d.p, d.mhz, nec.ground_of("average"), "copper", d.device)
    shot("lcd_a2_results", Results(app, d))
    shot("lcd_a3_swr", SwrChart(app, d))
    shot("lcd_a4_pattern", Pattern(app, d))
    shot("lcd_a5_3d", Pattern3D(app, d))
    shot("lcd_ax_cut", CutList(app, d))
    app.st.cable, app.st.cable_ft = "RG-8X", 75
    app.measured[t.id] = [(f, s * 1.08 + 0.05, 0, 0) for f, s, _zr, _zi in d.result.sweep]
    shot("lcd_ax_measured", SwrChart(app, d))
    y = TP.by_id("yagi")
    dy = Design(app, y, 14.15)
    dy.p = TP.yagi_defaults(14.15, 3)
    res = X.optimize_beam(y, dy.p, 14.15, "copper", "Balanced", rounds=6)
    shot("lcd_ax_optimize", Optimized(app, dy, res))
    dv = Design(app, TP.by_id("dipole"), 7.15)
    dv.result = lab.run_design(dv.t, dv.p, 7.15, nec.ground_of("average"), "copper", dv.device)
    shot("lcd_ax_3d_dipole", Pattern3D(app, dv))
    return []
