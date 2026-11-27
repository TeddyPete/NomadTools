import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
from hamtools import calc as C, geo, nomadgps, online, prop, sats  # noqa: E402


def test_sun_and_prefixes():
    # Newington CT on 2026-11-27: sunrise about 06:54 EST (11:54 UTC), sunset 16:22 EST (21:22 UTC)
    t = 1795737600 + 12 * 3600          # 2026-11-27 12:00 UTC
    ev = geo.sun_events(41.71, -72.73, geo.day_start(t))
    assert abs((ev["rise"] % 86400) / 3600 - 11.9) < 0.15
    assert abs((ev["set"] % 86400) / 3600 - 21.37) < 0.15
    assert geo.lookup_call("N0TNT")["cq"] == 4
    assert geo.lookup_call("VE7ABC")["country"].startswith("Canada")
    assert geo.lookup_call("JA1XYZ")["country"] == "Japan"
    assert geo.lookup_call("KH6/N0TNT")["country"] == "Hawaii"
    assert geo.lookup_call("2E0ABC")["country"] == "England"


def test_rf_math():
    assert C.s_units(-73) == "S9"
    assert C.s_units(-79) == "S8"
    assert C.dbm_to_uv(-73) == pytest.approx(50, rel=0.01)
    f, _l, _c = C.lc_solve(None, 1e-6, 100e-12)
    assert f == pytest.approx(15.915e6, rel=1e-3)
    assert C.toroid("T-50-2", 4.9)["turns"] == 100
    assert C.toroid_from_turns("FT-50-43", 10) == pytest.approx(52.3)
    r = C.attenuator(6)
    assert r["pi_shunt"] == pytest.approx(150.5, abs=0.2) and r["t_series"] == pytest.approx(16.6, abs=0.1)
    assert C.e24(16.6) == 16.0
    assert C.activity_near(14.074)[0][1] == "FT8"
    assert C.edges(14.2, "General")["inside"] is False
    assert C.power_limit(7.03, "Technician") == "200 W PEP"


def test_muf_estimate_shape():
    t = 1795737600
    night = prop.muf(41.7, -72.7, t + 6 * 3600, 90)
    day = prop.muf(41.7, -72.7, t + 17 * 3600, 90)
    assert 6 < night < day < 25
    assert prop.ssn_from_sfi(63.7) == pytest.approx(0, abs=0.5)


def test_solar_parse():
    from hamtools.demo import SOLAR_XML
    d = online.parse_solar(SOLAR_XML)
    assert d["solarflux"] == "87" and d["bands"]["80m-40m"]["day"] == "Good"


@pytest.mark.skipif(not sats.have_sgp4(), reason="python3-sgp4 not installed")
def test_satellite_passes():
    here = os.path.join(os.path.dirname(__file__), "..", "hamtools", "data", "tle.txt")
    tles = online.parse_tles(open(here).read())
    assert 25544 in tles
    ps = sats.next_passes(41.71, -72.73, tles, start=1795737600 + 16 * 3600, hours=12, min_el=0)
    assert ps
    for _b, p in ps:
        assert p["aos"] < p["tca"] < p["los"] and 0 <= p["max_el"] <= 90
        assert 1 * 60 < p["los"] - p["aos"] < 30 * 60
    b, p = next((b, p) for b, p in ps if b.name == "ISS")
    tr = sats.Tracker(b, tles[b.norad], 41.71, -72.73)
    up, down = tr.doppler(p["aos"] + 20)
    assert down > b.down and up < b.up          # coming towards us: hear it high, send low
    assert abs(down - b.down) < 0.012


def _nmea(body):
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"${body}*{x:02X}"


def test_nmea():
    fix = {}
    assert nomadgps.parse_nmea(_nmea("GPRMC,161229.487,A,4142.6000,N,07243.8000,W,0.13,309.62,271126,,,A"), fix)
    assert not nomadgps.parse_nmea("$GPRMC,161229.487,A,4142.6000,N,07243.8000,W,0.13,309.62,271126,,,A*00", {})
    nomadgps.parse_nmea(_nmea("GPGGA,161229.487,4142.6000,N,07243.8000,W,1,08,1.0,30.0,M,-34.0,M,,"), fix)
    assert fix["sats"] == 8 and fix["alt"] == 30.0
    assert fix["valid"] and fix["lat"] == pytest.approx(41.71) and fix["lon"] == pytest.approx(-72.73)
    assert time.gmtime(fix["utc"])[:6] == (2026, 11, 27, 16, 12, 29)
    assert nomadgps.to_grid(41.71, -72.73) == "FN31pr"


def test_screens_render(tmp_path):
    from hamtools.demo import render_screens
    files = render_screens(str(tmp_path))
    assert len(files) >= 15


def test_cap_gnss_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    port, power = tmp_path / "ttyS0", tmp_path / "brightness"
    port.write_text("")
    power.write_text("0\n")
    monkeypatch.setattr(nomadgps, "CAP_PORT", str(port))
    monkeypatch.setattr(nomadgps, "CAP_POWER", str(power))
    assert str(port) not in nomadgps.gps_ports()            # off and unpowered: never opened
    assert nomadgps.set_cap(True) == "Cap GNSS on"
    assert power.read_text().strip() == "1"
    assert str(port) in nomadgps.gps_ports()
    nomadgps.set_cap(False)
    assert str(port) not in nomadgps.gps_ports()            # switched off in Settings wins over the 5 V
