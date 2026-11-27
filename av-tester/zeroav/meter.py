"""Audio input meter and 1/3-octave RTA from the CardputerZero's mic
(or whatever the default capture device is, such as the 3.5 mm input).

Levels are dBFS (relative to the input's full scale). The SPL readout is
dBFS plus a calibration offset; set it once with a sound level calibrator
or a reference meter (+/- keys), and it is saved for next time.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

from .lipsync import RATE, Mic

CAL_PATH = os.path.expanduser("~/.config/nomad-av-tester/spl.json")
NFFT = 8192                      # 170 ms at 48 kHz
# ISO 1/3-octave centres, 25 Hz .. 20 kHz
BANDS = [25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000,
         1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000]
FLOOR_DB = -100.0


def a_weight_db(f: np.ndarray) -> np.ndarray:
    f2 = np.maximum(f, 1.0) ** 2
    ra = (12194 ** 2 * f2 ** 2) / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2))
                                    * (f2 + 12194 ** 2))
    return 20 * np.log10(ra) + 2.0


def band_label(fc: float) -> str:
    return f"{fc / 1000:g}k" if fc >= 1000 else f"{fc:g}"


class Meter:
    def __init__(self, device: str = "default"):
        self.mic = Mic(device)
        self.weighting = "Z"         # Z (flat) or A
        self.cal = self._load_cal()  # dB to add to dBFS for SPL
        self.peak_db = FLOOR_DB
        self.rms_db = FLOOR_DB
        self.max_db = FLOOR_DB
        self.bands = np.full(len(BANDS), FLOOR_DB)
        self.hold = np.full(len(BANDS), FLOOR_DB)
        self._leq_sum, self._leq_n = 0.0, 0
        self.started = 0.0
        self._win = np.hanning(NFFT)
        f = np.fft.rfftfreq(NFFT, 1 / RATE)
        self._aw = 10 ** (a_weight_db(f) / 10)
        edges = [(fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)) for fc in BANDS]
        self._bins = [np.nonzero((f >= lo) & (f < hi))[0] for lo, hi in edges]
        # Parseval with the Hann window: summed one-sided bins = mean square
        self._norm = 1.0 / (np.sum(self._win ** 2) * NFFT / 2)

    @staticmethod
    def _load_cal() -> float | None:
        try:
            with open(CAL_PATH) as f:
                return float(json.load(f)["offset_db"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save_cal(self) -> None:
        os.makedirs(os.path.dirname(CAL_PATH), exist_ok=True)
        with open(CAL_PATH, "w") as f:
            json.dump({"offset_db": round(self.cal or 0.0, 1), "when": time.strftime("%Y-%m-%d %H:%M:%S")}, f)

    def adjust_cal(self, step: float) -> None:
        if self.cal is None:
            self.cal = 100.0          # rough starting point for a MEMS mic
        self.cal += step
        self.save_cal()

    def start(self) -> None:
        self.mic.start()
        self.started = time.perf_counter()

    def stop(self) -> None:
        self.mic.stop()

    def reset(self) -> None:
        self.max_db = FLOOR_DB
        self.hold[:] = FLOOR_DB
        self._leq_sum, self._leq_n = 0.0, 0

    def update(self) -> bool:
        """Analyse the newest audio. Returns False until audio arrives."""
        now = time.perf_counter()
        t0, x = self.mic.window(now - 0.25, now)
        if len(x) < NFFT:
            return False
        x = x[-NFFT:].astype(np.float64) / 32768
        peak = float(np.abs(x).max())
        if self.weighting == "A":
            spec = np.abs(np.fft.rfft(x * self._win)) ** 2 * self._norm * self._aw
            ms = float(spec.sum())
        else:
            spec = np.abs(np.fft.rfft(x * self._win)) ** 2 * self._norm
            ms = float(np.mean(x ** 2))
        self.peak_db = 20 * np.log10(max(peak, 1e-5))
        self.rms_db = 10 * np.log10(max(ms, 1e-10))
        self.max_db = max(self.max_db, self.rms_db)
        self._leq_sum += ms
        self._leq_n += 1
        b = np.array([10 * np.log10(max(spec[i].sum(), 1e-10)) if len(i) else FLOOR_DB
                      for i in self._bins])
        self.bands = np.maximum(b, self.bands - 3.0)   # fast attack, ~20 dB/s fall at 7 Hz
        self.hold = np.maximum(self.hold, self.bands)
        return True

    @property
    def leq_db(self) -> float:
        return 10 * np.log10(max(self._leq_sum / self._leq_n, 1e-10)) if self._leq_n else FLOOR_DB

    def spl(self, dbfs: float) -> str:
        if self.cal is None:
            return "uncal"
        return f"{dbfs + self.cal:.1f} dB{self.weighting}"

    def lines(self) -> list[str]:
        w = self.weighting
        return [f"RMS {self.rms_db:6.1f} dBFS  peak {self.peak_db:6.1f}",
                f"SPL {self.spl(self.rms_db)}  ({w}-weighted)",
                f"Leq {self.spl(self.leq_db) if self.cal is not None else f'{self.leq_db:.1f} dBFS'}"
                f"  max {self.spl(self.max_db) if self.cal is not None else f'{self.max_db:.1f}'}"]

    def report(self) -> str:
        out = [f"Nomad AV Tester audio report  {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        out += self.lines()
        out += ["", f"SPL calibration offset: {'none' if self.cal is None else f'{self.cal:+.1f} dB'}", "",
                "1/3-octave band levels (dBFS, current / max hold):"]
        for fc, b, h in zip(BANDS, self.bands, self.hold):
            out.append(f"  {band_label(fc):>5} Hz  {b:6.1f}  {h:6.1f}")
        return "\n".join(out) + "\n"


def draw_rta(surf, rect, bands, hold, lo_db: float = -90.0, hi_db: float = -10.0, font=None) -> None:
    """Bar graph of band levels into rect (x, y, w, h) on a pygame Surface."""
    import pygame
    x0, y0, w, h = rect
    n = len(bands)
    bw = w / n
    lab_h = font.get_linesize() if font else 0
    gh = h - lab_h
    span = hi_db - lo_db
    for db in range(int(hi_db), int(lo_db) - 1, -10):     # grid every 10 dB
        y = y0 + gh * (hi_db - db) / span
        pygame.draw.line(surf, (40, 40, 60), (x0, y), (x0 + w, y))
    for i, (b, hd) in enumerate(zip(bands, hold)):
        frac = min(1.0, max(0.0, (b - lo_db) / span))
        bh = int(gh * frac)
        x = int(x0 + i * bw)
        col = (60, 200, 90) if b < hi_db - 12 else (240, 200, 60) if b < hi_db - 3 else (240, 70, 60)
        surf.fill(col, (x + 1, y0 + gh - bh, max(1, int(bw) - 2), bh))
        hy = y0 + gh - int(gh * min(1.0, max(0.0, (hd - lo_db) / span)))
        surf.fill((220, 220, 255), (x + 1, hy, max(1, int(bw) - 2), 2))
    if font:
        for i, fc in enumerate(BANDS):
            if fc in (31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000):
                img = font.render(band_label(fc), True, (170, 170, 190))
                surf.blit(img, (int(x0 + i * bw + bw / 2 - img.get_width() / 2), y0 + gh))
