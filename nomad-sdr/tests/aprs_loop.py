"""End-to-end APRS check with no radio: build an AX.25 frame, make Bell 202
AFSK audio, FM-modulate it into fake dongle IQ, run it through the receiver
and multimon-ng, and check the packet comes out (and reaches Rig Companion
when it is installed).

    python3 tests/aprs_loop.py [--rig]
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nomadsdr import aprs as P  # noqa: E402
from nomadsdr import dsp  # noqa: E402


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def addr(call: str, last: bool) -> bytes:
    c, _, ssid = call.partition("-")
    b = bytes((ord(ch) << 1) for ch in c.ljust(6)[:6])
    return b + bytes([0x60 | (int(ssid or 0) << 1) | (1 if last else 0)])


def frame(src, dst, path, info) -> bytes:
    calls = [dst, src] + path
    a = b"".join(addr(c, i == len(calls) - 1) for i, c in enumerate(calls))
    body = a + b"\x03\xf0" + info.encode()
    fcs = crc16(body)
    return body + bytes([fcs & 0xFF, fcs >> 8])


def hdlc_bits(data: bytes) -> list[int]:
    bits = []
    flag = [0, 1, 1, 1, 1, 1, 1, 0]
    bits += flag * 40
    ones = 0
    for byte in data:
        for i in range(8):
            b = (byte >> i) & 1
            bits.append(b)
            if b:
                ones += 1
                if ones == 5:
                    bits.append(0)
                    ones = 0
            else:
                ones = 0
    bits += flag * 4
    return bits


def afsk(bits, rate=dsp.AF) -> np.ndarray:
    out = []
    phase = 0.0
    tone = 1200.0
    spb = rate / 1200.0
    acc = 0.0
    for b in bits:
        if b == 0:                       # NRZI: 0 = change tone
            tone = 2200.0 if tone == 1200.0 else 1200.0
        acc += spb
        n = int(acc)
        acc -= n
        t = phase + 2 * np.pi * tone / rate * np.arange(n)
        out.append(np.sin(t))
        phase = (t[-1] + 2 * np.pi * tone / rate) % (2 * np.pi)
    return np.concatenate(out).astype(np.float32)


def iq_from_audio(audio: np.ndarray, dev_hz=3500.0) -> bytes:
    """FM-modulate audio (at AF) onto a carrier 60 kHz above centre at RATE."""
    up = np.repeat(audio, dsp.DEC)
    lead = np.zeros(dsp.RATE // 2, np.float32)
    up = np.concatenate((lead, up, lead))
    t = np.arange(len(up)) / dsp.RATE
    ph = 2 * np.pi * dsp.OFFSET * t + 2 * np.pi * dev_hz * np.cumsum(up) / dsp.RATE
    sig = 0.3 * np.exp(1j * ph) + 0.01 * (np.random.standard_normal(len(t)) + 1j * np.random.standard_normal(len(t)))
    iq = np.empty(2 * len(sig), np.float32)
    iq[0::2], iq[1::2] = sig.real, sig.imag
    return np.clip(iq * 128 + 127.4, 0, 255).astype(np.uint8).tobytes()


def main() -> int:
    rig = "--rig" in sys.argv
    text = "=4459.10N/09310.20W>Nomad SDR loop test"
    f = frame("N0TNT-9", "APNSDR", ["WIDE1-1"], text)
    raw = iq_from_audio(afsk(hdlc_bits(f)))
    rx = dsp.Receiver()
    dec = P.Aprs(to_rig=rig)
    if not dec.start():
        print("decoder:", dec.error)
        return 2
    step = dsp.HOP * 2
    for i in range(0, len(raw) - step, step):
        _, flat = rx.process(raw[i:i + step])
        dec.feed(flat)
    time.sleep(1.0)
    dec.stop()
    time.sleep(0.5)
    got = list(dec.packets)
    for p in got:
        print("decoded:", p["raw"], "| kind", p["kind"], "| pos", p["pos"])
    if rig:
        print("rig companion link:", dec.rig.ok, dec.rig.error)
    dec.close()
    ok = any(p["src"] == "N0TNT-9" and "loop test" in p["info"] for p in got)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
