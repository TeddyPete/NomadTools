import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from elmerlab import lab, nec  # noqa: E402
from elmerlab import templates as TP  # noqa: E402

needs_engine = pytest.mark.skipif(not shutil.which("nec2c"), reason="nec2c not installed")


def test_every_template_builds_a_deck():
    for t in TP.TEMPLATES:
        p = t.defaults(t.default_mhz)
        m = t.model(p, t.default_mhz, nec.ground_of("average"))
        segs, _ = nec.segment_model(m, t.default_mhz)
        deck = nec.build_deck(m, [t.default_mhz], segs)
        assert deck.startswith("CM ") and deck.rstrip().endswith("EN"), t.id
        assert len(m.wires) == len(segs)


def test_swr():
    assert lab.swr_of(50, 0) == pytest.approx(1.0)
    assert lab.swr_of(100, 0) == pytest.approx(2.0)
    assert lab.swr_of(25, 0) == pytest.approx(2.0)


@needs_engine
def test_dipole_free_space_is_near_73_ohms_and_2_15_dbi():
    t = TP.by_id("dipole")
    mhz = 14.0
    lam = nec.C0 / mhz
    p = {"length": lam * 0.48, "height": 10, "conductor": "awg14"}
    r = lab.run_design(t, p, mhz, nec.ground_of("free"), "perfect", "choke-1-1")
    assert 60 < r.zr < 80
    assert r.gain == pytest.approx(2.15, abs=0.2)


@needs_engine
def test_tune_makes_dipole_resonant():
    t = TP.by_id("dipole")
    p = t.defaults(7.15)
    q, r = lab.tune(t, p, 7.15, nec.ground_of("average"), "copper", t.device)
    assert r is not None and abs(r[1][1]) < 2
