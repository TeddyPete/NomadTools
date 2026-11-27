import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hamtools import calc as C  # noqa: E402


def test_privileges():
    assert C.privilege(7.074, "General")[1] is not None
    assert C.privilege(7.074, "Technician")[1] is not None          # 7.025-7.125 CW only
    assert C.privilege(7.2, "Technician")[1] is None
    assert C.privilege(14.2, "General")[1] is None                  # General phone starts 14.225
    assert C.privilege(14.2, "Extra")[1] is not None
    assert C.privilege(146.52, "Technician")[2].startswith("Yes")
    assert C.privilege(100.0, "Extra")[0] is None


def test_ohm_and_db_and_swr():
    v, f = C.solve_ohm(E=12, I=2)
    assert v["R"] == 6 and v["P"] == 24
    v, _ = C.solve_ohm(R=50, P=100)
    assert v["E"] == pytest.approx(70.71, abs=0.01)
    assert C.solve_ohm(E=1) is None
    assert C.watts_to_dbm(1) == pytest.approx(30)
    assert C.db_to_ratio(3) == pytest.approx(1.995, abs=0.001)
    r = C.swr_figures(swr=1.5)
    assert r["refl_pct"] == pytest.approx(4.0) and r["rl"] == pytest.approx(13.98, abs=0.01)
    r = C.swr_figures(forward=100, reflected=4)
    assert r["swr"] == pytest.approx(1.5)
    assert C.swr_figures(forward=10, reflected=10) is None


def test_numbers():
    assert C.parse_number("4.7k", prefixes=True) == pytest.approx(4700)
    assert C.parse_number("1,500") == 1500
    assert C.parse_number("") is None
    with pytest.raises(ValueError):
        C.parse_number("abc")
    assert C.si(0.0047, "A") == "4.7 mA"


def test_coax_and_grid():
    r = C.coax_loss("RG-8X", 100, 100, 100)
    assert r["loss"] == pytest.approx(3.1)
    assert C.to_grid(41.714775, -72.727260) == "FN31pr"
    lat, lon = C.grid_center("FN31pr")
    assert C.to_grid(lat, lon) == "FN31pr"
    assert C.norm_grid("fn31PR") == "FN31pr" and C.norm_grid("ZZ99") is None
    d = C.distance_km(*C.grid_center("FN31"), *C.grid_center("JO01"))
    assert 5000 < d < 6000
    b = C.bearing_deg(0, 0, 0, 10)
    assert b == pytest.approx(90) and C.compass(b) == "E"
    assert C.parse_coord("72.73W", "lon") == pytest.approx(-72.73)
    assert C.spell("n0tnt")[0] == ("N", "November")
