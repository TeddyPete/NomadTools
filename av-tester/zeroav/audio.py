"""Test-tone output through ALSA's `aplay`, so no extra Python audio
libraries are needed. Tones loop until stop() is called.

Modes:
  tone  - 1 kHz sine on both channels at a set dBFS level
  left  - L/R channel ID: tone on the left only
  right - tone on the right only
  lr    - alternates left and right every second (ID test)
  pink  - pink noise (equal energy per octave), both channels, for RTA/EQ
  sweep - log sine sweep 20 Hz to 20 kHz over 10 s, then 1 s silence
  polarity - positive-going pulse twice a second, for polarity checkers
"""
from __future__ import annotations

import subprocess
import threading

import numpy as np

RATE = 48000


def sine(freq: float, seconds: float, dbfs: float = -20.0) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return (10 ** (dbfs / 20)) * np.sin(2 * np.pi * freq * t)


def stereo(left: np.ndarray, right: np.ndarray) -> bytes:
    pcm = np.stack([left, right], axis=1)
    return (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()


def block_for(mode: str, freq: float = 1000.0, dbfs: float = -20.0) -> bytes:
    """One second (or two for 'lr') of audio that loops seamlessly."""
    s = sine(freq, 1.0, dbfs)          # 1000 Hz x 1 s = whole cycles, loops cleanly
    z = np.zeros_like(s)
    if mode == "tone":
        return stereo(s, s)
    if mode == "left":
        return stereo(s, z)
    if mode == "right":
        return stereo(z, s)
    if mode == "lr":
        return stereo(s, z) + stereo(z, s)
    if mode == "pink":
        p = pink_noise(10.0, dbfs)
        return stereo(p, p)
    if mode == "sweep":
        w = np.concatenate([log_sweep(20, 20000, 10.0, dbfs), np.zeros(RATE)])
        return stereo(w, w)
    if mode == "polarity":
        x = polarity_pulse(dbfs)
        return stereo(x, x)
    raise ValueError(mode)


def pink_noise(seconds: float, dbfs: float = -20.0, seed: int = 7) -> np.ndarray:
    """Pink noise with RMS at dbfs. Shaped in the frequency domain so the
    loop is seamless (the FFT is periodic)."""
    n = int(RATE * seconds)
    rng = np.random.default_rng(seed)
    spec = rng.normal(size=n // 2 + 1) + 1j * rng.normal(size=n // 2 + 1)
    f = np.fft.rfftfreq(n, 1 / RATE)
    spec[1:] /= np.sqrt(f[1:])
    spec[f < 15] = 0          # no subsonic rumble
    spec[f > 22000] = 0
    x = np.fft.irfft(spec, n)
    x *= (10 ** (dbfs / 20)) / np.sqrt(np.mean(x ** 2))
    return np.clip(x, -1, 1)


def log_sweep(f0: float, f1: float, seconds: float, dbfs: float = -20.0) -> np.ndarray:
    """Exponential sine sweep with short fades at each end."""
    t = np.arange(int(RATE * seconds)) / RATE
    k = np.log(f1 / f0)
    x = np.sin(2 * np.pi * f0 * seconds / k * (np.exp(t * k / seconds) - 1))
    fade = int(0.01 * RATE)
    env = np.ones_like(x)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return (10 ** (dbfs / 20)) * np.sqrt(2) * x * env


def polarity_pulse(dbfs: float = -20.0) -> np.ndarray:
    """0.5 s loop: a 1 ms positive half-sine pulse with a slow negative
    return, so the first (sharp) movement is clearly positive."""
    x = np.zeros(RATE // 2)
    n = int(0.001 * RATE)
    x[:n] = np.sin(np.pi * np.arange(n) / n)
    tail = int(0.02 * RATE)
    x[n:n + tail] = -np.sum(x[:n]) / tail   # net zero DC, slow return
    return np.clip(x * 10 ** ((dbfs + 14) / 20), -1, 1)


def pick_device() -> str:
    """Test tones belong on the HDMI output under test. On the CardputerZero
    the HDMI audio card (vc4hdmi) is free, while the ES8389 codec is held by
    the launcher, so prefer HDMI, then PipeWire, then the ALSA default."""
    try:
        names = [l.strip() for l in subprocess.run(
            ["aplay", "-L"], capture_output=True, text=True, timeout=5).stdout.splitlines()]
    except (OSError, subprocess.SubprocessError):
        return "default"
    for n in names:
        if n.startswith("hdmi:CARD=vc4hdmi"):
            return n
    return "pipewire" if "pipewire" in names else "default"


class TonePlayer:
    def __init__(self, device: str | None = None):
        self.device = device or pick_device()
        self.mode: str | None = None
        self.dbfs = -20.0
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def play(self, mode: str) -> None:
        self.stop()
        self.mode = mode
        data = block_for(mode, dbfs=self.dbfs)
        self._stop.clear()
        try:
            self._proc = subprocess.Popen(
                ["aplay", "-q", "-D", self.device, "-f", "S16_LE", "-r", str(RATE), "-c", "2", "-t", "raw"],
                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            self._proc = None
            return

        def feed(proc=self._proc):
            try:
                while not self._stop.is_set():
                    proc.stdin.write(data)
            except (BrokenPipeError, ValueError, OSError):
                pass

        self._thread = threading.Thread(target=feed, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            self._proc.terminate()
            self._proc = None
        self.mode = None

    def cycle(self) -> str | None:
        """Off -> tone -> lr -> left -> right -> pink -> sweep -> polarity -> off."""
        order = [None, "tone", "lr", "left", "right", "pink", "sweep", "polarity"]
        nxt = order[(order.index(self.mode) + 1) % len(order)]
        if nxt is None:
            self.stop()
        else:
            self.play(nxt)
        return nxt
