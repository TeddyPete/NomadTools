"""CW decoder for radio audio: finds the tone, follows it with a Goertzel
filter, turns it into key-down / key-up with an adaptive threshold, and
reads the characters with the same adaptive decoder the games use, so the
speed follows the sender (auto WPM).

Audio comes from arecord (ALSA, through PipeWire): the side jack's mic input
by default, or any USB sound card, such as a QMX's own USB audio.
"""
from __future__ import annotations

import subprocess
import threading
import time
from collections import deque

import numpy as np

from . import morse as M

RATE = 8000
BLOCK = 48                 # 6 ms per Goertzel block
CHUNK = BLOCK * 16         # read about 100 ms at a time
LO_HZ, HI_HZ = 300, 1200
SIDE_JACK = "plughw:CARD=ES8389Audio,DEV=0"   # the built-in codec, straight from ALSA


def input_devices() -> list[tuple[str, str]]:
    """(label, arecord device) choices: the default input plus every capture card."""
    out = [("Side jack", SIDE_JACK), ("PipeWire default", "default")]
    try:
        txt = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    for line in txt.splitlines():
        if line.startswith("card "):
            try:
                num = int(line.split()[1].rstrip(":"))
                name = line.split("[", 1)[1].split("]", 1)[0]
            except (IndexError, ValueError):
                continue
            if "ES8389" in name:
                continue          # the side jack is listed already
            out.append((f"USB: {name}"[:28], f"plughw:{num},0"))
    return out


class CwDecoder:
    def __init__(self, device: str = SIDE_JACK, tone_hz: float | None = None):
        self.device = device
        self.fixed_hz = tone_hz
        self.tone = tone_hz or 600.0
        self.text = deque(maxlen=400)       # decoded characters, " " for spaces
        self.level = 0.0                    # 0..1 meter of the tone
        self.snr = 0.0
        self.key = False
        self.error = ""
        self.running = False
        self.dec = M.KeyDecoder(initial_dit_ms=80, char_gap_units=2.5, word_gap_units=5)
        self._proc = None
        self._thread = None
        self._hist = np.zeros(2048, dtype=np.float32)
        self._last_tone = -1e9
        self._t = 0.0                       # ms of audio processed
        self._floor = None
        self._peak = 0.0
        self._down_t = 0.0
        self._env = 0.0
        self._run_len = 0
        self._pending = False
        self._lock = threading.Lock()

    @property
    def wpm(self) -> float:
        return self.dec.wpm

    def start(self) -> None:
        if self.running:
            return
        try:
            self._proc = subprocess.Popen(
                ["arecord", "-q", "-D", self.device, "-f", "S16_LE", "-r", str(RATE), "-c", "2", "-t", "raw"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            self.error = str(e)
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.running = False
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def clear(self) -> None:
        with self._lock:
            self.text.clear()

    def line(self, n: int = 400) -> str:
        with self._lock:
            return "".join(self.text)[-n:]

    # ---- processing ----
    def _loop(self) -> None:
        nbytes = CHUNK * 4                  # stereo: the jack's mic may be on either side
        while self.running and self._proc:
            data = self._proc.stdout.read(nbytes)
            if not data or len(data) < nbytes:
                err = self._proc.stderr.read().decode(errors="replace").strip() if self._proc else ""
                self.error = err.splitlines()[-1] if err else "audio input stopped"
                self.running = False
                break
            x = np.frombuffer(data, dtype="<i2").astype(np.float32).reshape(-1, 2).sum(axis=1) / 65536.0
            self.feed(x)

    def feed(self, x: np.ndarray) -> None:
        """Process samples (float, 8 kHz). Public so tests can feed audio."""
        self._hist = np.concatenate([self._hist, x])[-2048:]
        if not self.fixed_hz and self._t - self._last_tone >= 240:
            self._last_tone = self._t
            self._find_tone()
        nb = len(x) // BLOCK
        blocks = x[:nb * BLOCK].reshape(nb, BLOCK)
        n = np.arange(BLOCK)
        w = np.exp(-2j * np.pi * self.tone * n / RATE) * np.hanning(BLOCK)
        mags = np.abs(blocks @ w) / BLOCK
        bms = 1000.0 * BLOCK / RATE
        for m in mags:
            self._step(float(m), bms)

    def _step(self, m: float, bms: float) -> None:
        self._t += bms
        self._env = 0.6 * self._env + 0.4 * m
        e = self._env
        if self._floor is None:              # first block: start from what we hear
            self._floor, self._peak = max(e, 1e-6), max(e, 1e-6) * 2
        # noise floor creeps up slowly and drops fast; the peak does the reverse
        if e < self._floor:
            self._floor = 0.8 * self._floor + 0.2 * e
        elif not self.key:
            self._floor = 0.997 * self._floor + 0.003 * e
        self._peak = e if e > self._peak else max(self._peak * 0.999, self._floor)
        span = self._peak - self._floor
        self.snr = self._peak / max(self._floor, 1e-7)
        self.level = min(1.0, e / max(self._peak, 1e-6))
        on_th = self._floor + 0.55 * span
        off_th = self._floor + 0.35 * span
        want = self.key
        if self.snr < 3.0:
            want = False
        elif not self.key and e > on_th:
            want = True
        elif self.key and e < off_th:
            want = False
        # a change must hold for 2 blocks (12 ms) to count
        if want != self.key:
            self._run_len += 1
            if self._run_len >= 2:
                self._run_len = 0
                self.key = want
                t = self._t - bms
                if want:
                    out = self.dec.key_down(t)
                    self._down_t = t
                elif t - self._down_t > 1000:
                    # a carrier or a tune-up, not Morse: forget it
                    self.dec.down_at = None
                    out = []
                else:
                    self.dec.key_up(t)
                    out = []
                self._emit(out)
        else:
            self._run_len = 0
        if not self.key:
            self._emit(self.dec.poll(self._t))

    def _emit(self, chars) -> None:
        if not chars:
            return
        with self._lock:
            for c in chars:
                if c.space_before and self.text and self.text[-1] != " ":
                    self.text.append(" ")
                self.text.append(c.char if c.char != "#" else "_")

    def _find_tone(self) -> None:
        x = self._hist * np.hanning(len(self._hist))
        spec = np.abs(np.fft.rfft(x))
        freqs = np.fft.rfftfreq(len(x), 1 / RATE)
        band = (freqs >= LO_HZ) & (freqs <= HI_HZ)
        if not band.any():
            return
        i = int(np.argmax(np.where(band, spec, 0)))
        med = float(np.median(spec[band])) + 1e-9
        if spec[i] / med > 8 and abs(freqs[i] - self.tone) > 25:
            self.tone = float(freqs[i])
            self._floor = None
