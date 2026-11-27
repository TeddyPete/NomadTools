"""Sound: CW playback (rendered with numpy) and a live sidetone for keying.

Uses pygame.mixer through PipeWire/Pulse. If there is no sound device the
app still runs; the calls just do nothing.
"""
from __future__ import annotations

import math

import numpy as np

from . import morse as M

RATE = 48000
RAMP_MS = 5.0          # raised-cosine edges, no key clicks

_mixer = None


def init() -> bool:
    global _mixer
    if _mixer is not None:
        return bool(_mixer)
    try:
        import pygame
        pygame.mixer.pre_init(RATE, -16, 1, 512)
        pygame.mixer.init()
        _mixer = pygame.mixer
    except Exception:
        _mixer = False
    return bool(_mixer)


def envelope(sched: M.Schedule, n: int) -> np.ndarray:
    env = np.zeros(n, dtype=np.float32)
    ramp = max(2, int(RATE * RAMP_MS / 1000))
    up = (0.5 - 0.5 * np.cos(np.linspace(0, math.pi, ramp))).astype(np.float32)
    for start, dur, _el, _ti in sched.elements:
        a, b = int(start * RATE / 1000), int((start + dur) * RATE / 1000)
        b = min(b, n)
        if b - a < 2 * ramp:
            continue
        env[a:b] = 1.0
        env[a:a + ramp] = up
        env[b - ramp:b] = up[::-1]
    return env


def render(text_or_sched, t: M.Timing | None = None, hz: float = 600, volume: float = 0.6,
           noise: float = 0.0, qrm: list | None = None, qsb: float = 0.0, lead_ms: float = 150,
           seed: int = 1) -> np.ndarray:
    """Mono int16 samples. qrm: [(text, hz, level, wpm)] other stations in the
    passband; noise: band hiss level 0..1; qsb: fading depth 0..1."""
    sched = text_or_sched if isinstance(text_or_sched, M.Schedule) else M.schedule(text_or_sched, t)
    lead = int(RATE * lead_ms / 1000)
    n = lead + int(RATE * (sched.total + 200) / 1000)
    extra = []
    for (qt, qhz, lvl, qwpm) in qrm or []:
        qs = M.schedule(qt, M.timing(qwpm))
        n = max(n, lead + int(RATE * (qs.total + 200) / 1000))
        extra.append((qs, qhz, lvl))
    tt = np.arange(n, dtype=np.float32) / RATE
    out = np.zeros(n, dtype=np.float32)
    env = np.zeros(n, dtype=np.float32)
    e = envelope(sched, n - lead)
    env[lead:lead + len(e)] = e
    sig = env * np.sin(2 * math.pi * hz * tt)
    if qsb:
        sig *= (1 - qsb) + qsb * (0.5 + 0.5 * np.sin(2 * math.pi * 0.35 * tt + 1.0))
    out += sig
    rng = np.random.default_rng(seed)
    for qs, qhz, lvl in extra:
        off = int(rng.integers(0, RATE // 2))
        e = envelope(qs, n - off)
        out[off:] += lvl * e[:n - off] * np.sin(2 * math.pi * qhz * tt[off:])
    if noise:
        hiss = rng.standard_normal(n).astype(np.float32)
        # soften the hiss to a receiver-ish band with a short moving average
        k = 6
        hiss = np.convolve(hiss, np.ones(k, dtype=np.float32) / k, mode="same")
        out += noise * 1.2 * hiss
    peak = max(1.0, float(np.max(np.abs(out))))
    out = out / peak * volume * 0.9
    return (out * 32767).astype(np.int16)


class Player:
    """Plays rendered CW and a looped sidetone."""

    def __init__(self):
        self.ok = init()
        self.channel = None
        self.side = None
        self.side_hz = None
        self.side_ch = None
        self.side_vol = 0.6
        self.started = 0.0

    def play(self, samples: np.ndarray) -> float:
        """Start playing; returns the length in seconds."""
        if not self.ok:
            return len(samples) / RATE
        import pygame
        self.stop()
        snd = pygame.sndarray.make_sound(np.ascontiguousarray(samples))
        self.channel = snd.play()
        return len(samples) / RATE

    def busy(self) -> bool:
        return bool(self.ok and self.channel and self.channel.get_busy())

    def stop(self) -> None:
        if self.ok and self.channel:
            self.channel.stop()
        self.channel = None

    # ---- sidetone ----
    def sidetone(self, hz: float, volume: float) -> None:
        """Prepare the sidetone (a whole number of cycles, looped)."""
        if not self.ok:
            return
        if self.side is not None and self.side_hz == hz and abs(self.side_vol - volume) < 1e-3:
            return
        import pygame
        cycles = max(1, round(hz * 0.05))
        n = int(round(cycles * RATE / hz))
        tt = np.arange(n) / RATE
        wave = (np.sin(2 * math.pi * hz * tt) * 32767 * 0.85 * volume).astype(np.int16)
        self.side = pygame.sndarray.make_sound(np.ascontiguousarray(wave))
        self.side_hz, self.side_vol = hz, volume
        if self.side_ch is None:
            self.side_ch = pygame.mixer.Channel(min(7, pygame.mixer.get_num_channels() - 1))

    def tone_on(self) -> None:
        if self.ok and self.side is not None:
            self.side_ch.play(self.side, loops=-1, fade_ms=3)

    def tone_off(self) -> None:
        if self.ok and self.side_ch is not None:
            self.side_ch.fadeout(4)
