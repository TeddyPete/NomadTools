"""Sound out (through PipeWire with aplay) and WAV recordings.

Recordings are plain 16-bit mono WAV files. The header is rewritten every
couple of seconds, so a recording that is cut off by a power loss still
opens and plays up to the last few seconds.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time

import numpy as np

from .settings import data_dir

REC_DIR = os.path.join(data_dir(), "recordings")


def _alsa_device() -> str:
    try:
        out = subprocess.run(["aplay", "-L"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return "default"
    names = [l.strip() for l in out.splitlines() if l and not l.startswith(" ")]
    return "pipewire" if "pipewire" in names else "default"


class AudioOut:
    """Writes 16-bit mono audio to aplay. If sound can't start, it is quietly
    dropped (the app still works as a meter / decoder)."""

    def __init__(self, rate: int):
        self.rate = rate
        self.proc = None
        self.device = None
        self.error = ""
        self._retry = 0.0

    def _start(self) -> None:
        if time.monotonic() < self._retry or not shutil.which("aplay"):
            return
        self.device = self.device or _alsa_device()
        try:
            self.proc = subprocess.Popen(
                ["aplay", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE", "-c", "1",
                 "-r", str(self.rate), "--buffer-time=250000"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.error = ""
        except OSError as e:
            self.proc = None
            self.error = str(e)
            self._retry = time.monotonic() + 5

    def write(self, pcm: bytes) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self.proc = None
            self._start()
            if self.proc is None:
                return
        try:
            self.proc.stdin.write(pcm)
        except (BrokenPipeError, OSError, ValueError):
            self.close()
            self._retry = time.monotonic() + 2

    def close(self) -> None:
        p, self.proc = self.proc, None
        if p:
            try:
                p.stdin.close()
            except OSError:
                pass
            try:
                p.terminate()
                p.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass


def to_pcm(x: np.ndarray, volume: float) -> bytes:
    return np.clip(x * (volume * 32767.0), -32767, 32767).astype("<i2").tobytes()


def tone(rate: int, n: int, hz: float, phase: float, amp: float = 0.35) -> tuple[np.ndarray, float]:
    w = 2 * np.pi * hz / rate
    t = phase + w * np.arange(n)
    return (amp * np.sin(t)).astype(np.float32), float((phase + w * n) % (2 * np.pi))


class WavWriter:
    def __init__(self, path: str, rate: int):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.rate = rate
        self.f = open(path + ".part", "wb")
        self.bytes = 0
        self.started = time.time()
        self._hdr_t = 0.0
        self._header()

    def _header(self) -> None:
        pos = self.f.tell()
        self.f.seek(0)
        self.f.write(b"RIFF" + struct.pack("<I", 36 + self.bytes) + b"WAVEfmt " +
                     struct.pack("<IHHIIHH", 16, 1, 1, self.rate, self.rate * 2, 2, 16) +
                     b"data" + struct.pack("<I", self.bytes))
        if pos > 44:
            self.f.seek(pos)
        self.f.flush()

    def write(self, pcm: bytes) -> None:
        self.f.write(pcm)
        self.bytes += len(pcm)
        now = time.monotonic()
        if now - self._hdr_t > 2.0:
            self._hdr_t = now
            self._header()
            try:
                os.fsync(self.f.fileno())
            except OSError:
                pass

    @property
    def seconds(self) -> float:
        return self.bytes / 2 / self.rate

    def close(self) -> str:
        self._header()
        self.f.close()
        os.replace(self.path + ".part", self.path)
        return self.path


def recover() -> None:
    """Finish recordings left as .part by a crash or power loss."""
    try:
        names = os.listdir(REC_DIR)
    except OSError:
        return
    for n in names:
        if n.endswith(".wav.part"):
            p = os.path.join(REC_DIR, n)
            try:
                size = os.path.getsize(p)
                if size <= 44:
                    os.remove(p)
                    continue
                with open(p, "r+b") as f:
                    f.seek(4)
                    f.write(struct.pack("<I", size - 8))
                    f.seek(40)
                    f.write(struct.pack("<I", size - 44))
                os.replace(p, p[:-5])
            except OSError:
                pass


def rec_name(mhz: float, mode: str) -> str:
    return os.path.join(REC_DIR, time.strftime("%Y-%m-%d_%H%M%S") + f"_{mhz:.4f}MHz_{mode}.wav")
