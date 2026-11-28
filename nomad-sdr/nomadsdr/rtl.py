"""RTL-SDR dongle access through librtlsdr (ctypes, no extra Python packages).

Only the calls Nomad SDR needs: open/close, sample rate, centre frequency
(retuned live, no restart), gain (auto or one of the tuner's steps), PPM
correction, bias-tee (RTL-SDR Blog V3/V4 power for an LNA or active antenna)
and direct sampling (the V3's HF input, below about 28.8 MHz).

The dongle can only be used by one program at a time. If ZeroRadio, ZeroSDR
or rtl_tcp has it open, open() raises RtlError with a readable message.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import os


class RtlError(Exception):
    pass


_lib = None


def lib():
    global _lib
    if _lib is None:
        name = ctypes.util.find_library("rtlsdr") or "librtlsdr.so.0"
        try:
            _lib = ctypes.CDLL(name)
        except OSError as e:
            raise RtlError("librtlsdr is not installed (apt install librtlsdr0)") from e
        _lib.rtlsdr_get_device_name.restype = ctypes.c_char_p
        _lib.rtlsdr_get_device_count.restype = ctypes.c_uint32
        _lib.rtlsdr_get_center_freq.restype = ctypes.c_uint32
        _lib.rtlsdr_get_tuner_type.restype = ctypes.c_int
        _lib.rtlsdr_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32]
        for fn, args in (("rtlsdr_close", [ctypes.c_void_p]),
                         ("rtlsdr_set_sample_rate", [ctypes.c_void_p, ctypes.c_uint32]),
                         ("rtlsdr_set_center_freq", [ctypes.c_void_p, ctypes.c_uint32]),
                         ("rtlsdr_get_center_freq", [ctypes.c_void_p]),
                         ("rtlsdr_set_tuner_gain_mode", [ctypes.c_void_p, ctypes.c_int]),
                         ("rtlsdr_set_tuner_gain", [ctypes.c_void_p, ctypes.c_int]),
                         ("rtlsdr_set_agc_mode", [ctypes.c_void_p, ctypes.c_int]),
                         ("rtlsdr_set_freq_correction", [ctypes.c_void_p, ctypes.c_int]),
                         ("rtlsdr_set_direct_sampling", [ctypes.c_void_p, ctypes.c_int]),
                         ("rtlsdr_set_offset_tuning", [ctypes.c_void_p, ctypes.c_int]),
                         ("rtlsdr_reset_buffer", [ctypes.c_void_p]),
                         ("rtlsdr_get_tuner_type", [ctypes.c_void_p]),
                         ("rtlsdr_get_tuner_gains", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]),
                         ("rtlsdr_read_sync", [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                               ctypes.POINTER(ctypes.c_int)])):
            getattr(_lib, fn).argtypes = args
        if hasattr(_lib, "rtlsdr_set_bias_tee"):
            _lib.rtlsdr_set_bias_tee.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _lib.rtlsdr_get_device_usb_strings.argtypes = [ctypes.c_uint32, ctypes.c_char_p,
                                                       ctypes.c_char_p, ctypes.c_char_p]
    return _lib


TUNERS = {0: "unknown", 1: "E4000", 2: "FC0012", 3: "FC0013", 4: "FC2580", 5: "R820T", 6: "R828D"}


def devices() -> list[dict]:
    """Dongles plugged in: [{"index", "name", "vendor", "product", "serial"}]."""
    try:
        L = lib()
    except RtlError:
        return []
    out = []
    for i in range(L.rtlsdr_get_device_count()):
        m, p, s = (ctypes.create_string_buffer(256) for _ in range(3))
        L.rtlsdr_get_device_usb_strings(i, m, p, s)
        out.append({"index": i, "name": (L.rtlsdr_get_device_name(i) or b"").decode(errors="replace"),
                    "vendor": m.value.decode(errors="replace"), "product": p.value.decode(errors="replace"),
                    "serial": s.value.decode(errors="replace")})
    return out


def usb_present() -> bool:
    """True if an RTL2832 dongle is on USB (even when another app holds it)."""
    for d in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        try:
            v = open(d).read().strip()
            p = open(os.path.join(os.path.dirname(d), "idProduct")).read().strip()
        except OSError:
            continue
        if v == "0bda" and p in ("2838", "2832"):
            return True
    return False


class Rtl:
    def __init__(self, index: int = 0):
        L = lib()
        self.L = L
        self.dev = ctypes.c_void_p()
        r = L.rtlsdr_open(ctypes.byref(self.dev), index)
        if r < 0 or not self.dev:
            self.dev = None
            if usb_present():
                raise RtlError("The SDR dongle is busy. Close ZeroRadio, ZeroSDR or rtl_tcp and try again.")
            raise RtlError("No RTL-SDR dongle found. Plug it into USB.")
        self.tuner = TUNERS.get(L.rtlsdr_get_tuner_type(self.dev), "unknown")
        n = L.rtlsdr_get_tuner_gains(self.dev, None)
        arr = (ctypes.c_int * max(1, n))()
        L.rtlsdr_get_tuner_gains(self.dev, arr)
        self.gains = [arr[i] / 10 for i in range(max(0, n))]      # dB
        self.has_bias_tee = hasattr(L, "rtlsdr_set_bias_tee")
        self._n = ctypes.c_int()
        self._buf = None
        self.direct = 0

    def set_rate(self, rate: int) -> None:
        self.L.rtlsdr_set_sample_rate(self.dev, int(rate))

    def set_freq(self, hz: float) -> None:
        self.L.rtlsdr_set_center_freq(self.dev, int(round(hz)))

    def set_gain(self, db: float | None) -> None:
        """None = tuner auto gain, else the nearest tuner gain step."""
        if db is None or not self.gains:
            self.L.rtlsdr_set_tuner_gain_mode(self.dev, 0)
            return
        g = min(self.gains, key=lambda x: abs(x - db))
        self.L.rtlsdr_set_tuner_gain_mode(self.dev, 1)
        self.L.rtlsdr_set_tuner_gain(self.dev, int(round(g * 10)))

    def set_ppm(self, ppm: int) -> None:
        if ppm:
            self.L.rtlsdr_set_freq_correction(self.dev, int(ppm))

    def set_bias_tee(self, on: bool) -> bool:
        if not self.has_bias_tee:
            return False
        return self.L.rtlsdr_set_bias_tee(self.dev, 1 if on else 0) == 0

    def set_direct(self, mode: int) -> None:
        """0 off, 1 I branch, 2 Q branch (RTL-SDR Blog V3 HF input)."""
        if mode != self.direct:
            self.L.rtlsdr_set_direct_sampling(self.dev, int(mode))
            self.direct = mode

    def start(self) -> None:
        self.L.rtlsdr_reset_buffer(self.dev)

    def read(self, nbytes: int) -> bytes:
        if self._buf is None or len(self._buf) != nbytes:
            self._buf = ctypes.create_string_buffer(nbytes)
        r = self.L.rtlsdr_read_sync(self.dev, self._buf, nbytes, ctypes.byref(self._n))
        if r < 0:
            raise RtlError("The SDR dongle stopped (unplugged?)")
        return self._buf.raw[:self._n.value]

    def close(self) -> None:
        if self.dev:
            try:
                if self.has_bias_tee:
                    self.L.rtlsdr_set_bias_tee(self.dev, 0)   # never leave the antenna powered
            finally:
                self.L.rtlsdr_close(self.dev)
            self.dev = None
