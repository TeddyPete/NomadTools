"""Quick checks that need no dongle: python3 -m pytest tests (or run directly)."""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())

from nomadsdr import aprs, bandplan as B, dsp, radio  # noqa: E402


def test_bandplan_privileges():
    assert B.can_tx(146.52, "Technician") is True
    assert B.can_tx(14.2, "Technician") is False
    assert B.can_tx(14.2, "General") is False      # Extra-only phone
    assert B.can_tx(14.3, "General") is True
    assert B.can_tx(7.03, "Technician") is True     # Tech CW on 40 m
    assert B.can_tx(162.55, "Extra") is False
    assert B.can_tx(146.52, "None") is None


def test_repeater_offsets():
    assert B.repeater_offset(146.94) == -0.6
    assert B.repeater_offset(147.12) == +0.6
    assert B.repeater_offset(444.5) == +5.0
    assert B.repeater_offset(146.52) is None


def test_fm_tone_recovered():
    src = radio.fake_source(fm_tone=1000.0)
    rx = dsp.Receiver()
    out = [rx.process(src(dsp.HOP * 2))[0] for _ in range(50)]
    a = np.concatenate(out)[8000:]
    f = np.fft.rfftfreq(len(a), 1 / dsp.AF)[np.abs(np.fft.rfft(a)).argmax()]
    assert abs(f - 1000) < 20
    assert rx.level - rx.noise > 20


def test_noise_only_is_quiet():
    src = radio.fake_source(freq_offsets=())
    rx = dsp.Receiver()
    for _ in range(60):
        rx.process(src(dsp.HOP * 2))
    assert abs(rx.level - rx.noise) < 3


def test_aprs_parse():
    t = aprs.parse_tnc2("N0TNT-9>APDR16,WIDE1-1:=4459.10N/09310.20W>hi")
    assert t[0] == "N0TNT-9" and t[2] == "WIDE1-1"
    la, lo = aprs.position(t[3])
    assert abs(la - 44.985) < 1e-3 and abs(lo + 93.17) < 1e-3


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
