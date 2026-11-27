import math
import os
import random
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from elmermorse import morse as M  # noqa: E402
from elmermorse.cwdecode import RATE, CwDecoder  # noqa: E402
from elmermorse.trainer import Store  # noqa: E402


def test_paris_timing():
    # PARIS plus a word gap is 50 units: 3.0 s at 20 WPM
    assert abs(M.schedule("PARIS ", M.timing(20)).total - 3000) < 1e-6
    # Farnsworth: characters at 18, the word still lasts 60/5 s at 5 WPM overall
    assert abs(M.schedule("PARIS ", M.timing(18, 5)).total - 12000) < 1e-6


def test_tables_round_trip():
    for ch, code in M.MORSE.items():
        assert M.char_for(code) == ch
    assert M.encode("CQ DE <AR>") == "-.-. --.- / -.. . / .-.-."
    assert M.sound_out("K") == "dah-di-dah"


def test_key_decoder_reads_a_slow_fist():
    d = M.KeyDecoder(initial_dit_ms=60)   # starts expecting 20 WPM ...
    t, out = 0.0, []
    dit = 160                              # ... but the learner keys at 7.5 WPM
    for ch in "PARK":
        for el in M.MORSE[ch]:
            out += d.key_down(t)
            t += dit if el == "." else 3 * dit
            d.key_up(t)
            t += dit
        t += 2 * dit
        out += d.poll(t)
    out += d.flush()
    assert "".join(c.char for c in out)[-3:] == "ARK"


def test_unlock_rule():
    with tempfile.TemporaryDirectory() as tmp:
        st = Store(os.path.join(tmp, "s.json"))
        assert st.chars == ["K", "M"]
        rng = random.Random(1)
        new = None
        for _ in range(200):
            c = st.pick([], rng)
            new = st.answer(c, c) or new
            if new:
                break
        assert new == "U" and st.learned == 3
        # wrong answers never take a character away
        for _ in range(30):
            st.answer("U", "K")
        assert st.learned == 3 and "U" in st.trouble


def _synth(text, wpm, hz, noise, seed=0):
    s = M.schedule(text, M.timing(wpm))
    n = int((s.total + 1500) * RATE / 1000) + RATE // 2
    env = np.zeros(n, np.float32)
    lead = RATE // 2
    for st, dur, _, _ in s.elements:
        env[lead + int(st * RATE / 1000):lead + int((st + dur) * RATE / 1000)] = 1
    t = np.arange(n) / RATE
    rng = np.random.default_rng(seed)
    return (0.3 * env * np.sin(2 * math.pi * hz * t) + noise * rng.standard_normal(n)).astype(np.float32)


def test_audio_decoder_finds_tone_and_speed():
    for text, wpm, hz in (("CQ CQ DE N0TNT N0TNT K", 20, 700), ("UR RST 579 TU 73", 14, 560)):
        d = CwDecoder()
        x = _synth(text, wpm, hz, 0.05)
        for i in range(0, len(x), 768):
            d.feed(x[i:i + 768])
        assert abs(d.tone - hz) < 30
        assert abs(d.wpm - wpm) < 3
        assert text.split()[-3:] == d.line().split()[-3:]
