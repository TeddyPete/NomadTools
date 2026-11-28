"""The receiver worker: owns the dongle, runs the DSP, plays and records sound.

The UI thread only changes the wanted settings (freq, mode, gain ...) and
reads the status; the worker applies changes between blocks, so tuning is
instant (the dongle is retuned live, nothing restarts).
"""
from __future__ import annotations

import threading
import time

import numpy as np

from . import audio as A
from . import dsp
from .rtl import Rtl, RtlError

HF_TOP = 28.8e6          # V3 direct sampling works below this
STEPS = [10, 100, 500, 1000, 2500, 5000, 6250, 12500, 25000, 100000, 1000000]


class Radio:
    def __init__(self, cfg: dict, source=None):
        self.cfg = cfg
        self.rx = dsp.Receiver()
        self.source = source          # fake source for tests: callable(nbytes) -> bytes
        self.dev: Rtl | None = None
        self.error = ""
        self.status = "Starting"
        self.tuner = ""
        self.gains: list = []
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.dirty = True
        self.out = A.AudioOut(dsp.AF)
        self.rec: A.WavWriter | None = None
        self.last_rec = ""
        self.listeners = []           # callables(flat_fm_audio) for decoders
        self.mute = False
        self.fox_tone = False         # replace audio with a pitch that follows the level
        self._phase = 0.0
        self.hw_freq = 0.0
        self.direct = 0
        self.blocks = 0
        self.overruns = 0
        self.bias_ok = None

    # ---- settings the UI changes ------------------------------------------------
    def set(self, **kw) -> None:
        with self.lock:
            self.cfg.update(kw)
            self.dirty = True

    @property
    def freq(self) -> float:
        return float(self.cfg["freq"])

    def filter_for(self, mode: str) -> int:
        return int(self.cfg.get("filter", {}).get(mode) or dsp.FILTERS[mode][0])

    # ---- life cycle ----------------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name="radio", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)
        self.stop_rec()
        self.out.close()

    def start_rec(self) -> str:
        with self.lock:
            if not self.rec:
                self.rec = A.WavWriter(A.rec_name(self.freq, self.cfg["mode"]), dsp.AF)
            return self.rec.path

    def stop_rec(self) -> str:
        with self.lock:
            r, self.rec = self.rec, None
        if r:
            self.last_rec = r.close()
            return self.last_rec
        return ""

    # ---- worker ------------------------------------------------------------------------
    def _open(self) -> bool:
        if self.source:
            self.tuner, self.gains = "test", [0.0, 20.0, 40.0]
            return True
        try:
            self.dev = Rtl(0)
        except RtlError as e:
            self.error = str(e)
            self.status = "No dongle"
            return False
        self.dev.set_rate(dsp.RATE)
        self.tuner, self.gains = self.dev.tuner, self.dev.gains
        self.error = ""
        self.direct = 0
        self.dirty = True
        return True

    def _apply(self) -> None:
        with self.lock:
            c = dict(self.cfg)
            self.dirty = False
        mode = c["mode"]
        self.rx.set_mode(mode, self.filter_for(mode))
        self.rx.squelch = c.get("squelch")
        self.rx.agc = c.get("agc", True)
        f = float(c["freq"]) * 1e6 + self.rx.shift
        direct = 0
        hw = f - self.rx.offset
        if f < HF_TOP:
            if c.get("hf") == "direct":
                direct = 2
            elif c.get("hf") == "upconverter":
                hw += float(c.get("upconverter_mhz", 125.0)) * 1e6
        self.hw_freq = hw
        if not self.dev:
            return
        self.dev.set_direct(direct)
        self.direct = direct
        self.dev.set_freq(hw)
        self.dev.set_gain(c.get("gain"))
        if c.get("ppm"):
            self.dev.set_ppm(int(c["ppm"]))
        want_bias = bool(c.get("bias_tee"))
        if want_bias != bool(self.bias_ok):
            ok = self.dev.set_bias_tee(want_bias)
            self.bias_ok = want_bias if ok else None

    def _run(self) -> None:
        nbytes = dsp.HOP * 2
        while self.running:
            if not self.dev and not self.source:
                if not self._open():
                    time.sleep(1.5)
                    continue
                self.dev.start()
            elif self.source and not self.tuner:
                self._open()
            if self.dirty:
                try:
                    self._apply()
                except Exception as e:   # noqa: BLE001  keep the radio alive
                    self.error = f"Tuning failed: {e}"
            try:
                if self.source:
                    raw = self.source(nbytes)
                    time.sleep(dsp.HOP / dsp.RATE * 0.9)
                else:
                    raw = self.dev.read(nbytes)
            except RtlError as e:
                self.error = str(e)
                self._close_dev()
                continue
            if len(raw) < nbytes:
                continue
            self.status = "Receiving"
            audio, flat = self.rx.process(raw)
            self.blocks += 1
            if flat is not None:
                for fn in list(self.listeners):
                    try:
                        fn(flat)
                    except Exception:   # noqa: BLE001
                        pass
            if self.fox_tone:
                hz = 300 + max(0.0, min(1.0, (self.rx.level - self.rx.noise + 3) / 45.0)) * 1500
                audio, self._phase = A.tone(dsp.AF, len(audio), hz, self._phase)
            if len(audio):
                pcm = A.to_pcm(audio, 0.0 if self.mute else float(self.cfg.get("volume", 0.6)))
                self.out.write(pcm)
                with self.lock:
                    rec = self.rec
                if rec and (not self.cfg.get("rec_squelch") or self.rx.sq_open):
                    rec.write(A.to_pcm(audio, 0.9))
        self._close_dev()

    def _close_dev(self) -> None:
        if self.dev:
            try:
                self.dev.close()
            except Exception:   # noqa: BLE001
                pass
            self.dev = None
            self.bias_ok = None


def fake_source(freq_offsets=(60000,), fm_tone=1000.0, snr_db=30.0):
    """Synthetic IQ for tests and screenshots: FM carriers with a tone."""
    t0 = [0]
    rng = np.random.default_rng(1)

    def read(nbytes):
        n = nbytes // 2
        t = (t0[0] + np.arange(n)) / dsp.RATE
        t0[0] += n
        sig = np.zeros(n, np.complex64)
        amp = 10 ** (snr_db / 20) * 0.003
        for off in freq_offsets:
            phase = 2 * np.pi * off * t + (3000 / fm_tone) * np.sin(2 * np.pi * fm_tone * t)
            sig += amp * np.exp(1j * phase)
        sig += 0.003 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        iq = np.empty(2 * n, np.float32)
        iq[0::2], iq[1::2] = sig.real, sig.imag
        return np.clip(iq * 128 + 127.4, 0, 255).astype(np.uint8).tobytes()
    return read
