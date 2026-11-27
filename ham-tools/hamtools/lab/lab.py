"""Run a design through the NEC2 engine and turn the numbers into what a ham
wants to know: SWR, resonance, bandwidth, gain, takeoff angle, front-to-back.

Port of Ask Elmer's analysis.ts / optimize.ts (tune) for the CardputerZero.
"""
from __future__ import annotations

import cmath
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import nec
from .nec import C0
from .templates import Template, find_band

DEVICES = {   # id: (name, ratio)  ratio = antenna side : 50 ohm side
    "choke-1-1": ("1:1 choke balun", 1.0),
    "balun-4-1": ("4:1 current balun", 4.0),
    "unun-49-1": ("49:1 EFHW transformer", 49.0),
    "unun-64-1": ("64:1 EFHW transformer", 64.0),
    "unun-9-1": ("9:1 unun", 9.0),
    "qsection-75": ("75 ohm Q-section", 2.25),
    "tuner": ("Antenna tuner", 1.0),
    "none": ("Direct feed", 1.0),
}


def swr_of(zr: float, zi: float, z0: float = 50.0) -> float:
    g = abs(complex(zr - z0, zi) / complex(zr + z0, zi)) if (zr + z0) or zi else 1
    return 999.0 if g >= 0.999999 else (1 + g) / (1 - g)


def line_transform(zl: complex, z0: float, length: float, mhz: float, alpha: float, vf: float) -> complex:
    beta = 2 * math.pi * mhz / (C0 * vf)
    g = complex(alpha * length, beta * length)
    ch, sh = cmath.cosh(g), cmath.sinh(g)
    return z0 * (zl * ch + z0 * sh) / (z0 * ch + zl * sh)


def through_match(zr: float, zi: float, mhz: float, device: str, design_mhz: float) -> complex:
    """Impedance on the 50 ohm side of the matching device."""
    z = complex(zr, zi)
    if device == "qsection-75":
        lam = C0 / design_mhz
        return line_transform(z, 75, lam / 4 * 0.66, mhz, 1e-6, 0.66)
    ratio = DEVICES.get(device, ("", 1.0))[1]
    return z / ratio


def sweep_freqs(center: float, half: float, n: int) -> list:
    lo, hi = center * (1 - half), center * (1 + half)
    return [float(f"{lo + (hi - lo) * i / (n - 1):.9g}") for i in range(n)]


WORKERS = max(1, min(4, os.cpu_count() or 1))


def run_parallel(decks: list) -> list:
    """Run several NEC2 decks at once (one nec2c process per core): real-ground
    (Sommerfeld) runs cost about 0.3 s per frequency on the CardputerZero."""
    if len(decks) == 1:
        return [nec.run_deck(decks[0])]
    with ThreadPoolExecutor(WORKERS) as ex:
        return list(ex.map(nec.run_deck, decks))


def design_sweep(t: Template, mhz: float, wide: bool = False) -> list:
    if wide:
        lo = max(1.5, mhz * 0.45)
        hi = min(30, max(mhz * 4.2, mhz + 2)) if mhz < 30 else mhz * 1.6
        return sweep_freqs((lo + hi) / 2, (hi - lo) / (hi + lo), 49)
    half = t.span or 0.03
    b = find_band(mhz)
    if t.id != "mag-loop" and b:
        half = max(half, (b[3] - b[2]) / 2 / mhz * 1.35, max(b[3] - mhz, mhz - b[2]) / mhz * 1.1)
    return sweep_freqs(mhz, min(half, 0.25), 25)


@dataclass
class Result:
    mhz: float
    zr: float = float("nan")
    zi: float = float("nan")
    swr: float = 999.0
    sweep: list = field(default_factory=list)      # (mhz, swr, zr, zi)
    resonances: list = field(default_factory=list)
    min_swr: tuple = (0.0, 999.0)
    bw2: tuple | None = None
    gain: float | None = None
    takeoff: float | None = None
    azimuth: float | None = None
    fb: float | None = None
    az_bw: float | None = None
    efficiency: float | None = None
    polarization: str = ""
    az_slice: list = field(default_factory=list)   # (phi, gain)
    el_slice: list = field(default_factory=list)   # (elev 0..180, gain)
    pattern3d: list = field(default_factory=list)  # (theta, phi, gain) on a 6 x 10 degree grid
    wires: list = field(default_factory=list)      # ((x, y, z), (x, y, z)) in metres
    free_space: bool = False
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    secs: float = 0.0


def _z_of(report: str):
    res, _err = nec.parse_output(report)
    if not res or not res[0].feeds:
        return None
    f = res[0].feeds[0]
    return f["zr"], f["zi"]


def impedance_at(model: nec.Model, mhz: float):
    return impedances([model], mhz)[0]


def impedances(models: list, mhz: float) -> list:
    """Feed impedance of several models at one frequency, run in parallel."""
    decks = []
    for m in models:
        segs, _ = nec.segment_model(m, mhz)
        decks.append(nec.build_deck(m, [mhz], segs))
    return [_z_of(rep) for rep in run_parallel(decks)]


def sweep_stats(points: list, design: float):
    res = []
    for a, b in zip(points, points[1:]):
        rising = a[3] <= 0 < b[3]
        falling = a[3] >= 0 > b[3] and abs(b[3] - a[3]) < 4 * max(a[2], b[2])
        if rising or falling:
            t = -a[3] / (b[3] - a[3]) if b[3] != a[3] else 0
            res.append(a[0] + t * (b[0] - a[0]))
    mn = min(points, key=lambda p: p[1]) if points else (design, 999)
    bw = None
    i = min(range(len(points)), key=lambda k: abs(points[k][0] - design)) if points else 0
    if points and points[i][1] <= 2:
        lo = hi = i
        while lo > 0 and points[lo - 1][1] <= 2:
            lo -= 1
        while hi < len(points) - 1 and points[hi + 1][1] <= 2:
            hi += 1

        def edge(inside, outside):
            if outside < 0 or outside >= len(points):
                return points[inside][0]
            a, b = points[inside], points[outside]
            return a[0] + (2 - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
        bw = (edge(lo, lo - 1), edge(hi, hi + 1))
    return res, (mn[0], mn[1]), bw


def pattern_stats(r: Result, pts: list, free: bool) -> None:
    if not pts:
        return
    mx = max(pts, key=lambda p: p[4])
    idx = {(round(p[0], 6), round(p[1] % 360, 6)): p for p in pts}

    def at(th, ph):
        return idx.get((round(th, 6), round(ph % 360, 6)))
    r.gain, r.takeoff, r.azimuth = mx[4], 90 - mx[0], mx[1]
    r.az_slice = sorted([(p[1], p[4]) for p in pts if abs(p[0] - mx[0]) < 1e-6])
    grid = {}
    for p in pts:
        th, ph = round(p[0]), round(p[1]) % 360
        if th % 6 == 0 and ph % 10 == 0:
            grid[(th, ph)] = p[4]
    r.pattern3d = sorted((th, ph, g) for (th, ph), g in grid.items())
    thetas = sorted({p[0] for p in pts})
    el = []
    for th in thetas:
        f = at(th, mx[1])
        if f:
            el.append((90 - th, f[4]))
    for th in reversed(thetas):
        b = at(th, mx[1] + 180)
        if b:
            el.append((90 + th, b[4]))   # 180 - (90 - th)
    r.el_slice = el
    back = at(mx[0], mx[1] + 180)
    r.fb = mx[4] - back[4] if back else None
    # azimuth -3 dB beamwidth
    s = r.az_slice
    if len(s) > 2:
        i = max(range(len(s)), key=lambda k: s[k][1])
        lim = s[i][1] - 3
        nn = len(s)

        def find(d):
            for k in range(1, nn):
                j = (i + d * k) % nn
                if s[j][1] < lim:
                    pj = (i + d * (k - 1)) % nn
                    a, b = s[pj][1], s[j][1]
                    return k - 1 + (a - lim) / (a - b)
            return None
        lft, rgt = find(-1), find(1)
        if lft is not None and rgt is not None:
            step = abs(s[1][0] - s[0][0])
            bw = (lft + rgt) * step
            r.az_bw = bw if bw < 359 else None
    pv, ph = mx[2], mx[3]
    r.polarization = "vertical" if pv > ph + 6 else "horizontal" if ph > pv + 6 else "mixed"


def run_design(t: Template, p: dict, mhz: float, ground: nec.Ground, material: str, device: str,
               wide: bool = False, pattern_step: tuple = (3, 5)) -> Result:
    t0 = time.monotonic()
    r = Result(mhz)
    if t.ground == "mininec" and ground.kind == "real":
        ground = nec.Ground("real", ground.er, ground.sigma, "mininec")
    model = t.model(p, mhz, ground, material)
    r.wires = [(tuple(w.a), tuple(w.b)) for w in model.wires]
    freqs = design_sweep(t, mhz, wide)
    segs, r.warnings = nec.segment_model(model, max(freqs + [mhz]))
    # 1) sweep: impedance only, split across the cores
    chunks = [freqs[i::WORKERS] for i in range(WORKERS)] if ground.kind == "real" else [freqs]
    res = []
    for rep in run_parallel([nec.build_deck(model, sorted(c), segs) for c in chunks if c]):
        part, errs = nec.parse_output(rep)
        res += part
        r.errors += errs
    res.sort(key=lambda fr: fr.mhz)
    for fr in res:
        if fr.feeds:
            f = fr.feeds[0]
            z = through_match(f["zr"], f["zi"], fr.mhz, device, mhz)
            r.sweep.append((fr.mhz, swr_of(z.real, z.imag), f["zr"], f["zi"]))
    r.resonances, r.min_swr, r.bw2 = sweep_stats(r.sweep, mhz)
    # 2) design frequency: impedance, power budget and pattern
    mininec = ground.kind == "real" and ground.method == "mininec"
    deck = nec.build_deck(model, [mhz], segs, pattern=pattern_step, currents=mininec)
    res2, errs = nec.parse_output(nec.run_deck(deck))
    r.errors += errs
    r.free_space = ground.kind == "free"
    if res2 and res2[0].feeds:
        fr = res2[0]
        f = fr.feeds[0]
        r.zr, r.zi = f["zr"], f["zi"]
        z = through_match(r.zr, r.zi, mhz, device, mhz)
        r.swr = swr_of(z.real, z.imag)
        pts, avg = fr.pattern, fr.average_gain
        if mininec and fr.currents:
            from .farfield import compute_pattern, segments
            pos, dl, cur = segments(model, segs, fr.currents)
            pin = fr.input_w or f["power"] or 1e-9
            pts, avg = compute_pattern(pos, dl, cur, mhz, pin, (ground.er, ground.sigma), *pattern_step)
        pattern_stats(r, pts, r.free_space)
        if avg is not None:
            r.efficiency = min(1.0, avg / (1 if r.free_space else 2)) * 100
        elif fr.efficiency is not None:
            r.efficiency = fr.efficiency
    r.secs = time.monotonic() - t0
    return r


# ---- tune ---------------------------------------------------------------------------

def _swr_after(z, mhz, device):
    m = through_match(z[0], z[1], mhz, device, mhz)
    return swr_of(m.real, m.imag)


def tune_reactance(build, p: dict, key: str, mhz: float, device: str, lo=0.7, hi=1.4, progress=None):
    """Secant search on one setting for zero feed reactance at the design frequency."""
    base = float(p[key])

    def ev(val):
        return impedance_at(build({**p, key: val}), mhz)
    x0, z0 = base, ev(base)
    if not z0:
        return None
    x1 = base * (0.98 if z0[1] > 0 else 1.02)
    z1 = ev(x1)
    if not z1:
        return None
    for i in range(14):
        if progress:
            progress((i + 1) / 14)
        if abs(z1[1]) < 0.25:
            break
        d = z1[1] - z0[1]
        x2 = x1 * 1.01 if abs(d) < 1e-9 else x1 - z1[1] * (x1 - x0) / d
        x2 = min(max(x2, x1 * 0.85, base * lo), x1 * 1.15, base * hi)
        x0, z0, x1 = x1, z1, x2
        z2 = ev(x1)
        if not z2:
            return None
        z1 = z2
    return x1, z1, _swr_after(z1, mhz, device)


def tune_swr(build, p: dict, key: str, mhz: float, device: str, lo=0.8, hi=1.25, progress=None):
    """Lowest SWR by a zooming grid search (robust for sharp resonances)."""
    base = float(p[key])
    a, b = base * lo, base * hi
    best = None
    passes = 4
    for ps in range(passes):
        nn = 16 if ps == 0 else 8
        xs = [a * (b / a) ** (i / (nn - 1)) for i in range(nn)]
        zs = impedances([build({**p, key: x}) for x in xs], mhz)
        bi, bs = -1, float("inf")
        for i, z in enumerate(zs):
            if not z:
                continue
            s = _swr_after(z, mhz, device) - min(z[0], 50) * 1e-4
            if s < bs:
                bi, bs = i, s
        if bi < 0:
            return best
        best = (xs[bi], zs[bi], _swr_after(zs[bi], mhz, device))
        a, b = xs[max(0, bi - 1)], xs[min(nn - 1, bi + 1)]
        if progress:
            progress((ps + 1) / passes)
    return best


def tune_magloop(build, p: dict, mhz: float, device: str, progress=None):
    q = dict(p)
    for i in range(4):
        lo, hi = (0.85, 1.15) if i == 0 else (0.985, 1.015)
        base = float(q["cap"])
        xs = [base * lo * (hi / lo) ** (k / 15) for k in range(16)]
        zs = impedances([build({**q, "cap": x}) for x in xs], mhz)
        ok = [(z[0], x) for x, z in zip(xs, zs) if z]
        if not ok:
            break
        zr, cap = max(ok)
        q["cap"] = cap
        if progress:
            progress((i + 1) / 5)
        if zr <= 0:
            break
        k = (50 / zr) ** 0.25
        if abs(math.log(k)) < 0.02:
            break
        q["coupling"] = min(35, max(5, float(q["coupling"]) * k))
    r = tune_swr(build, q, "cap", mhz, device, 0.994, 1.006)
    if r:
        q["cap"] = r[0]
    return q, r


def tune(t: Template, p: dict, mhz: float, ground: nec.Ground, material: str, device: str, progress=None):
    """Returns (new params, (value, (zr, zi), swr)) or (p, None)."""
    if not t.tune:
        return p, None
    if t.ground == "mininec" and ground.kind == "real":
        ground = nec.Ground("real", ground.er, ground.sigma, "mininec")

    def build(q):
        return t.model(q, mhz, ground, material)
    cfg = t.tune
    key = cfg["param"]
    if cfg["mode"] == "magloop":
        return tune_magloop(build, p, mhz, device, progress)
    if cfg["mode"] == "reactance":
        r = tune_reactance(build, p, key, mhz, device, cfg.get("lo", 0.7), cfg.get("hi", 1.4), progress)
    else:
        r = tune_swr(build, p, key, mhz, device, cfg.get("lo", 0.8), cfg.get("hi", 1.25), progress)
    if not r:
        return p, None
    return {**p, key: r[0]}, r
