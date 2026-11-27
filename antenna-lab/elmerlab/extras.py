"""Antenna Lab 0.2: beam optimizer, feed line loss, and real measurements
(NanoVNA over USB, or a Touchstone .s1p file) to lay over the model.
"""
from __future__ import annotations

import glob
import math
import os
import time

from . import lab, nec
from .templates import Template, wl

# ---- feed line --------------------------------------------------------------------------
# Matched-line attenuation, dB per 100 ft at 10/50/100/400 MHz (Ask Elmer coax.ts),
# with velocity factors.
TABLE_MHZ = (10, 50, 100, 400)
CABLES = {
    "RG-58": ((1.1, 2.5, 3.8, 8.4), 0.66),
    "RG-8X": ((0.9, 2.1, 3.1, 6.6), 0.78),
    "RG-213": ((0.55, 1.3, 1.9, 4.1), 0.66),
    "LMR-400": ((0.4, 0.9, 1.2, 2.5), 0.85),
}


def db_per_100ft(cable: str, mhz: float) -> float:
    table = CABLES[cable][0]
    xs = [math.log(f) for f in TABLE_MHZ]
    ys = [math.log(v) for v in table]
    x = math.log(max(mhz, 0.1))
    i = 0
    while i < len(xs) - 2 and x > xs[i + 1]:
        i += 1
    t = (x - xs[i]) / (xs[i + 1] - xs[i])
    return math.exp(ys[i] + t * (ys[i + 1] - ys[i]))


def line_loss(cable: str, length_ft: float, mhz: float, swr_load: float) -> dict:
    """Matched loss, total loss with the antenna's SWR (ARRL), and the SWR the
    radio sees at the other end of the line."""
    ml = db_per_100ft(cable, mhz) * length_ft / 100
    a = 10 ** (ml / 10)
    g = (swr_load - 1) / (swr_load + 1) if swr_load < 900 else 0.999
    total = 10 * math.log10((a * a - g * g) / (a * (1 - g * g)))
    gin = g / a
    swr_in = (1 + gin) / (1 - gin)
    pct = 100 * 10 ** (-total / 10)
    return {"matched": ml, "total": total, "extra": total - ml, "swr_in": swr_in, "delivered_pct": pct}


# ---- beam optimizer ----------------------------------------------------------------------

GOALS = {
    "Most gain": lambda g, fb: g + 0.05 * min(fb, 25),
    "Best front/back": lambda g, fb: min(fb, 35) + 0.5 * g,
    "Balanced": lambda g, fb: g + 0.25 * min(fb, 30),
}


def _beam_deck(model: nec.Model, mhz: float) -> str:
    segs, _ = nec.segment_model(model, mhz)
    deck = nec.build_deck(model, [mhz], segs)
    # free space, the horizontal plane only: forward is +x (phi 0), rear 120..240
    return deck.replace("XQ 0\n", "RP 0 1 13 1001 90 0 0 30 0 0\n")


def beam_figures(report: str):
    """(gain dBi forward, front-to-rear dB, R, X) or None."""
    res, _ = nec.parse_output(report)
    if not res or not res[0].feeds or not res[0].pattern:
        return None
    f = res[0].feeds[0]
    pat = {round(p[1]) % 360: p[4] for p in res[0].pattern}
    fwd = pat.get(0)
    rear = [v for ph, v in pat.items() if 120 <= ph <= 240]
    if fwd is None or not rear:
        return None
    return fwd, fwd - max(rear), f["zr"], f["zi"]


def optimize_beam(t: Template, p: dict, mhz: float, material: str, goal: str = "Balanced",
                  rounds: int = 10, progress=None) -> dict:
    """Pattern search over a Yagi's reflector and director lengths and the
    element spacings, in free space at the design frequency, keeping the boom
    no longer than it is now and the feed resistance usable (15 ohm or more).
    The driven element is retuned for resonance afterwards by Tune."""
    score_of = GOALS.get(goal, GOALS["Balanced"])
    count = round(float(p.get("count", 3)))
    w = wl(mhz)
    boom = float(p.get(f"pos{count - 1}", 0)) if count > 1 else 0
    keys = [k for k in [f"len{i}" for i in range(count) if i != 1] + [f"pos{i}" for i in range(1, count)]]
    steps = {k: (0.02 * float(p[k]) if k.startswith("len") else 0.025 * w) for k in keys}
    free = nec.Ground("free", 1, 0)

    def valid(q):
        xs = [0.0] + [float(q[f"pos{i}"]) for i in range(1, count)]
        gaps_ok = all(b - a >= 0.04 * w for a, b in zip(xs, xs[1:]))
        return gaps_ok and xs[-1] <= boom * 1.02 + 1e-9 and all(float(q[f"len{i}"]) > 0.3 * w for i in range(count))

    def evaluate(qs):
        decks = [_beam_deck(t.model(q, mhz, free, material), mhz) for q in qs]
        out = []
        for rep in lab.run_parallel(decks):
            fig = beam_figures(rep)
            if not fig:
                out.append((-1e9, None))
                continue
            g, fb, r, x = fig
            s = score_of(g, fb) - max(0.0, 15 - r) * 0.3
            out.append((s, fig))
        return out

    best = dict(p)
    best_s, best_fig = evaluate([best])[0]
    start_fig = best_fig
    for rnd in range(rounds):
        cands = []
        for k in keys:
            for sgn in (1, -1):
                q = dict(best)
                q[k] = float(q[k]) + sgn * steps[k]
                if valid(q):
                    cands.append(q)
        if not cands:
            break
        scored = evaluate(cands)
        i = max(range(len(scored)), key=lambda j: scored[j][0])
        if scored[i][0] > best_s + 0.01:
            best, best_s, best_fig = cands[i], scored[i][0], scored[i][1]
        else:
            for k in keys:
                steps[k] /= 2
        if progress:
            progress((rnd + 1) / rounds)
    return {"params": best, "before": start_fig, "after": best_fig, "goal": goal}


# ---- measurements: NanoVNA and .s1p files ---------------------------------------------------

def gamma_swr(g: complex) -> float:
    m = abs(g)
    return 999.0 if m >= 0.999 else (1 + m) / (1 - m)


def nanovna_ports() -> list:
    by_id = [p for p in glob.glob("/dev/serial/by-id/*") if "nano" in p.lower() or "0483_5740" in p]
    return by_id or sorted(glob.glob("/dev/ttyACM*"))


def nanovna_sweep(start_mhz: float, stop_mhz: float, points: int = 101, port: str | None = None,
                  timeout: float = 20.0) -> list:
    """S11 sweep from a NanoVNA (v1 / H / H4 firmware shell) over USB serial.
    Returns [(mhz, swr, zr, zi)] at the analyzer's 50 ohm port."""
    import termios
    port = port or next(iter(nanovna_ports()), None)
    if not port:
        raise OSError("No NanoVNA found. Plug it into the USB port and turn it on.")
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

        def read_until(marker: bytes, limit: float) -> bytes:
            buf, end = b"", time.monotonic() + limit
            while time.monotonic() < end:
                try:
                    chunk = os.read(fd, 4096)
                    buf += chunk
                    if buf.rstrip().endswith(marker):
                        return buf
                except BlockingIOError:
                    time.sleep(0.02)
            return buf
        os.write(fd, b"\r")
        read_until(b"ch>", 1.5)
        a, b = int(start_mhz * 1e6), int(stop_mhz * 1e6)
        os.write(fd, f"scan {a} {b} {points} 3\r".encode())
        text = read_until(b"ch>", timeout).decode("ascii", "replace")
    finally:
        os.close(fd)
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                f, re_, im = float(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                continue
            out.append(_point(f / 1e6, complex(re_, im)))
    if not out:
        raise OSError("The NanoVNA didn't send a sweep. Check its firmware has the scan command.")
    return out


def _point(mhz: float, g: complex):
    z = 50 * (1 + g) / (1 - g) if abs(1 - g) > 1e-9 else complex(1e6, 0)
    return (mhz, gamma_swr(g), z.real, z.imag)


def read_s1p(path: str) -> list:
    """Touchstone .s1p (RI, MA or DB) to [(mhz, swr, zr, zi)]."""
    unit, fmt, z0 = 1e9, "MA", 50.0
    mult = {"HZ": 1, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}
    out = []
    for raw in open(path, encoding="utf-8", errors="replace"):
        line = raw.split("!")[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            toks = line[1:].upper().split()
            for i, tk in enumerate(toks):
                if tk in mult:
                    unit = mult[tk]
                elif tk in ("RI", "MA", "DB"):
                    fmt = tk
                elif tk == "R" and i + 1 < len(toks):
                    z0 = float(toks[i + 1])
            continue
        p = line.split()
        if len(p) < 3:
            continue
        f, a, b = float(p[0]) * unit / 1e6, float(p[1]), float(p[2])
        if fmt == "RI":
            g = complex(a, b)
        else:
            mag = 10 ** (a / 20) if fmt == "DB" else a
            g = mag * complex(math.cos(math.radians(b)), math.sin(math.radians(b)))
        if abs(z0 - 50) > 1e-6:   # renormalise to 50 ohm
            z = z0 * (1 + g) / (1 - g)
            g = (z - 50) / (z + 50)
        out.append(_point(f, g))
    return out


def find_s1p() -> list:
    """Touchstone files in home and on USB sticks, newest first."""
    pats = [os.path.expanduser("~/*.s1p"), os.path.expanduser("~/*/*.s1p"), "/media/*/*/*.s1p", "/media/*/*.s1p",
            "/media/*/*/*/*.s1p"]
    files = {f for p in pats for f in glob.glob(p)}
    return sorted(files, key=lambda f: -os.path.getmtime(f))
