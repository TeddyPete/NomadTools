"""Receiver signal processing in numpy (no SciPy, no GNU Radio).

The dongle runs at 256 kS/s. Every block of HOP new samples goes through one
FFT of N samples (overlap-save). That one FFT gives:

  * the spectrum shown on screen (250 kHz wide),
  * the channel: the bins around the wanted signal are picked, shaped by the
    filter for the mode, and turned back into 32 kHz complex baseband with a
    small inverse FFT (fast-convolution channel filter and decimator),
  * the signal level for the S-meter, squelch and fox-hunt meter.

The wanted signal sits OFFSET (60 kHz) above the dongle's centre so the
dongle's DC spike never lands on it. OFFSET * HOP / RATE is a whole number,
so the channel's phase stays continuous from block to block (no clicks).
"""
from __future__ import annotations

import numpy as np

RATE = 256_000           # dongle sample rate
N = 8192                 # FFT size
HOP = 6144               # new samples per block (overlap N - HOP)
OVER = N - HOP
DEC = 8                  # 256k -> 32k
AF = RATE // DEC         # audio rate, 32000
M = N // DEC             # channel FFT size
BIN = RATE / N           # 31.25 Hz
OFFSET = 60_000          # channel offset from the dongle centre (1920 bins)
K_OFF = int(OFFSET / BIN)
CW_PITCH = 700           # CW tone in Hz

MODES = ["NFM", "AM", "USB", "LSB", "CW", "WFM"]
# Filter choices per mode (Hz), first is the default.
FILTERS = {"NFM": [12500, 16000, 8000, 25000], "AM": [8000, 5000, 10000, 3000],
           "USB": [2700, 2400, 3000, 1800], "LSB": [2700, 2400, 3000, 1800],
           "CW": [500, 250, 1000, 2400], "WFM": [180000]}
SPEC_BINS = 8000         # bins shown (250 kHz)
SPEC_W = 320


def _ramp(x, lo, hi, tw):
    """1 inside [lo, hi], raised-cosine edges tw wide, 0 outside (vectorized)."""
    a = np.clip((x - (lo - tw)) / tw, 0, 1)
    b = np.clip(((hi + tw) - x) / tw, 0, 1)
    out = np.minimum(0.5 - 0.5 * np.cos(np.pi * a), 0.5 - 0.5 * np.cos(np.pi * b))
    return out


def channel_mask(mode: str, bw: float, size: int, bin_hz: float) -> np.ndarray:
    """Frequency-domain filter in FFT order for the channel IFFT of `size`
    bins, with a delay of OVER/2 input samples so the impulse response is
    causal for overlap-save."""
    f = np.fft.fftfreq(size, d=1.0 / (size * bin_hz))
    if mode in ("USB", "CW"):
        lo, hi = (200.0, 200.0 + bw) if mode == "USB" else (CW_PITCH - bw / 2, CW_PITCH + bw / 2)
        lo = max(lo, 50.0)
    elif mode == "LSB":
        lo, hi = -200.0 - bw, -200.0
    else:
        lo, hi = -bw / 2, bw / 2
    tw = max(60.0, min(800.0, bw * 0.12))
    h = _ramp(f, lo, hi, tw)
    delay = OVER / 2 / RATE                       # seconds
    return (h * np.exp(-2j * np.pi * f * delay)).astype(np.complex64)


class AudioFilter:
    """Real audio filter by overlap-save FFT (band-pass, optional de-emphasis)."""

    def __init__(self, lo: float, hi: float, deemph_us: float = 0.0, size: int = 2048, rate: int = AF):
        self.size = size
        self.rate = rate
        f = np.fft.rfftfreq(size, 1.0 / rate)
        h = _ramp(f, lo, hi, max(40.0, lo * 0.6)) if lo > 0 else _ramp(f, -1.0, hi, 400.0)
        if deemph_us:
            h = h / np.sqrt(1 + (2 * np.pi * f * deemph_us * 1e-6) ** 2)
        self.half = size // 2
        self.H = (h * np.exp(-2j * np.pi * f * (self.half / 2) / rate)).astype(np.complex64)
        self.buf = np.zeros(0, np.float32)
        self.hist = np.zeros(self.half, np.float32)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        """Filter any length; output length equals input length (fixed delay)."""
        self.buf = np.concatenate((self.buf, x.astype(np.float32)))
        out = []
        while len(self.buf) >= self.half:
            seg = np.concatenate((self.hist, self.buf[:self.half]))
            self.hist = self.buf[:self.half]
            self.buf = self.buf[self.half:]
            y = np.fft.irfft(np.fft.rfft(seg) * self.H, self.size)
            out.append(y[self.half:].astype(np.float32))
        if not out:
            return np.zeros(0, np.float32)
        return np.concatenate(out)


class Resampler:
    """Linear-interpolation resampler with state (for the APRS decoder's
    22050 Hz input)."""

    def __init__(self, src: int, dst: int):
        self.step = src / dst
        self.pos = 0.0
        self.last = np.zeros(1, np.float32)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        data = np.concatenate((self.last, x))
        n = int((len(data) - 1 - self.pos) / self.step)
        if n <= 0:
            return np.zeros(0, np.float32)
        t = self.pos + self.step * np.arange(n)
        out = np.interp(t, np.arange(len(data)), data).astype(np.float32)
        self.pos = t[-1] + self.step - (len(data) - 1)
        self.last = data[-1:]
        return out


class Receiver:
    """Turns raw dongle bytes into audio, levels and a spectrum."""

    def __init__(self):
        self.prev = np.zeros(OVER, np.complex64)
        self.mode = None
        self.bw = 0
        self.wfm = False
        self.squelch = None          # dBFS threshold or None (open)
        self.sq_open = True
        self.level = -120.0          # channel power, dBFS
        self.peak = -120.0
        self.noise = -120.0          # noise floor estimate across the spectrum, dBFS
        self.spec = np.full(SPEC_W, -120.0, np.float32)
        self.spec_every = 2
        self.agc_gain = 1.0
        self.agc = True
        self.audio_filter = None
        self._n = 0
        self._last = np.complex64(1)
        self._dc = 0.0
        self.deemph_state = 0.0
        self.set_mode("NFM", FILTERS["NFM"][0])

    def set_mode(self, mode: str, bw: float | None = None) -> None:
        bw = bw or FILTERS[mode][0]
        if mode == self.mode and bw == self.bw:
            return
        self.mode, self.bw = mode, bw
        self.wfm = mode == "WFM"
        if self.wfm:
            # WFM: whole 256 kHz band, demodulated at 256k, decimated after.
            self.cmask = channel_mask("NFM", min(bw, 200000), N, BIN)
            self.audio_filter = AudioFilter(30, 15000, 75)
        else:
            self.cmask = channel_mask(mode, bw, M, BIN)
            if mode == "NFM":
                self.audio_filter = AudioFilter(250, min(4000, bw * 0.32))
            elif mode == "AM":
                self.audio_filter = AudioFilter(80, min(5000, bw * 0.55))
            elif mode == "CW":
                self.audio_filter = AudioFilter(CW_PITCH - max(150, bw / 2), CW_PITCH + max(150, bw / 2))
            else:
                self.audio_filter = AudioFilter(150, min(3600, bw + 300))
        self.agc_gain = 1.0

    @property
    def offset(self) -> int:
        """Where the wanted frequency sits from the dongle centre (Hz)."""
        return 0 if self.wfm else OFFSET

    @property
    def shift(self) -> int:
        """Extra tuning shift for the channel: CW listens 700 Hz below so the
        carrier is heard as a 700 Hz tone."""
        return -CW_PITCH if self.mode == "CW" else 0

    # ---- one block ---------------------------------------------------------------
    def process(self, raw: bytes, want_spec: bool = True):
        """raw: HOP*2 bytes of 8-bit IQ. Returns (audio float32 at AF, flat_fm
        float32 at AF or None). flat_fm is the un-filtered FM discriminator
        output for data decoders (APRS)."""
        a = np.frombuffer(raw, np.uint8).astype(np.float32)
        a -= 127.4
        a *= 1.0 / 128.0
        x = a.view(np.complex64)
        if len(x) != HOP:
            x = np.resize(x, HOP)
        seg = np.concatenate((self.prev, x))
        self.prev = seg[HOP:]
        X = np.fft.fft(seg)
        self._n += 1
        if want_spec and self._n % self.spec_every == 0:
            self._spectrum(X)
        if self.wfm:
            Y = X * self.cmask
            y = np.fft.ifft(Y)[OVER:]
        else:
            idx = (K_OFF + np.r_[0:M // 2, -M // 2:0]) % N
            Y = X[idx] * self.cmask
            y = (np.fft.ifft(Y) * (M / N))[OVER // DEC:]
        p = float(np.mean(y.real * y.real + y.imag * y.imag))
        self.level = 10 * np.log10(p + 1e-14)
        self.peak = max(self.level, self.peak - 0.15)
        flat = None
        if self.squelch is not None:
            th = self.squelch + (-2.0 if self.sq_open else 0.0)
            self.sq_open = self.level >= th
        else:
            self.sq_open = True
        m = self.mode
        if m in ("NFM", "WFM"):
            z = np.concatenate(([self._last], y))
            self._last = y[-1]
            d = np.angle(z[1:] * np.conj(z[:-1])).astype(np.float32)
            if self.wfm:
                d = d.reshape(-1, DEC).mean(axis=1) * 0.6
                audio = self.audio_filter(d)
            else:
                d *= AF / (2 * np.pi * 5000.0) * 0.5          # +-5 kHz deviation -> +-0.5
                flat = d
                audio = self.audio_filter(d)
        elif m == "AM":
            env = np.abs(y).astype(np.float32)
            self._dc = 0.995 * self._dc + 0.005 * float(env.mean())
            audio = self._agc(self.audio_filter(env - self._dc))
        else:  # USB, LSB, CW
            audio = self._agc(self.audio_filter(y.real.astype(np.float32)))
        if not self.sq_open:
            audio = audio * 0.0
        return audio, flat

    def _agc(self, x: np.ndarray) -> np.ndarray:
        if not len(x):
            return x
        if not self.agc:
            return x * 40.0
        pk = float(np.max(np.abs(x))) + 1e-9
        target = min(4000.0, 0.35 / pk)
        g0 = self.agc_gain
        g1 = target if target < g0 else g0 + (target - g0) * 0.02   # fast attack, slow release
        self.agc_gain = g1
        return x * np.linspace(g0, g1, len(x), dtype=np.float32)

    def _spectrum(self, X: np.ndarray) -> None:
        P = (X.real * X.real + X.imag * X.imag) * (1.0 / (N * N))
        P = np.fft.fftshift(P)
        mid = N // 2
        s = P[mid - SPEC_BINS // 2: mid + SPEC_BINS // 2].reshape(SPEC_W, -1).max(axis=1)
        db = (10 * np.log10(s + 1e-14)).astype(np.float32)
        self.spec = 0.6 * self.spec + 0.4 * db
        self.noise = 0.9 * self.noise + 0.1 * float(np.percentile(db, 25)) if self.noise > -119 else float(np.percentile(db, 25))
