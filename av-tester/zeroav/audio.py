"""Test-tone output through ALSA's `aplay`, so no extra Python audio
libraries are needed. Tones loop until stop() is called.

Modes:
  tone  - 1 kHz sine on both channels at a set dBFS level
  left  - L/R channel ID: tone on the left only
  right - tone on the right only
  lr    - alternates left and right every second (ID test)
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
    raise ValueError(mode)


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
        self._proc = subprocess.Popen(
            ["aplay", "-q", "-D", self.device, "-f", "S16_LE", "-r", str(RATE), "-c", "2", "-t", "raw"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

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
        """Off -> tone -> lr -> left -> right -> off."""
        order = [None, "tone", "lr", "left", "right"]
        nxt = order[(order.index(self.mode) + 1) % len(order)]
        if nxt is None:
            self.stop()
        else:
            self.play(nxt)
        return nxt
