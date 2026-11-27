"""NEC2 model, deck writer, engine runner and output parser.

Ported from Ask Elmer's Antenna Lab (app/src/workshop/lab/nec/). The browser
version runs nec2c compiled to WebAssembly; here the same engine is the
Debian package `nec2c`, run as a subprocess. All dimensions are metres.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

C0 = 299.792458  # m * MHz


@dataclass
class Wire:
    a: tuple
    b: tuple
    radius: float          # conductor radius, m
    label: str = ""
    group: str = ""
    segs: int | None = None

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)


@dataclass
class Source:
    wire: int              # index into wires
    at: float = 0.5        # 0 = end a, 1 = end b
    mag: float = 1.0
    phase: float = 0.0


@dataclass
class Load:
    wire: int
    at: float
    kind: str = "series"   # series | parallel
    r: float = 0.0
    l: float = 0.0         # henries
    c: float = 0.0         # farads
    label: str = ""


@dataclass
class TLine:
    wire1: int
    at1: float
    wire2: int
    at2: float
    z0: float
    length: float          # electrical length, m


@dataclass
class Ground:
    kind: str = "real"     # free | perfect | real
    er: float = 13.0
    sigma: float = 0.005
    method: str = "sommerfeld"  # sommerfeld | mininec


@dataclass
class Model:
    name: str
    wires: list
    sources: list
    loads: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    material: str = "copper"
    ground: Ground = field(default_factory=Ground)
    ground_loss: float = 0.0   # extra series ohms at the feed (radials, car body)


MATERIALS = {   # S/m; None = lossless
    "perfect": ("Perfect (lossless)", None),
    "copper": ("Copper", 5.8e7),
    "ccs": ("Copper-clad steel", 5.0e7),
    "aluminum": ("Aluminum", 3.0e7),
    "stainless": ("Stainless steel", 1.4e6),
    "steel": ("Galvanized steel", 1.0e6),
}

# ARRL Antenna Book / EZNEC ground table.
GROUNDS = [
    ("free", "Free space", 0, 0),
    ("perfect", "Perfect ground", 0, 0),
    ("city", "City / industrial", 3, 0.001),
    ("poor", "Poor (sandy, rocky)", 10, 0.002),
    ("average", "Average", 13, 0.005),
    ("good", "Good (farmland)", 14, 0.01),
    ("very-good", "Very good (marsh)", 20, 0.0303),
    ("fresh", "Fresh water", 80, 0.001),
    ("salt", "Salt water", 81, 5),
]


def ground_of(gid: str, method: str = "sommerfeld") -> Ground:
    for i, _label, er, sig in GROUNDS:
        if i == gid:
            if i in ("free", "perfect"):
                return Ground(i)
            return Ground("real", er, sig, method)
    return Ground("real", 13, 0.005, method)


# ---- segmentation and deck ----------------------------------------------------------

def segment_model(m: Model, max_mhz: float, per_wl: int = 30) -> tuple[list, list]:
    """Segments per wire (about per_wl per wavelength at the top frequency, odd
    where a source or load sits mid-wire) and geometry warnings."""
    lam = C0 / max_mhz
    target = lam / per_wl
    centre = {s.wire for s in m.sources if 0.02 < s.at < 0.98}
    centre |= {ld.wire for ld in m.loads if 0.02 < ld.at < 0.98}
    segs, warnings = [], []
    for i, w in enumerate(m.wires):
        if w.segs:
            segs.append(w.segs)
            continue
        n = max(1, math.ceil(w.length / target))
        by_r = max(1, math.floor(w.length / (4 * w.radius)))
        n = min(n, by_r)
        if i in centre and n % 2 == 0:
            n += -1 if n + 1 > by_r else 1
        segs.append(max(1, min(n, 400)))
    for i, w in enumerate(m.wires):
        name = w.label or f"Wire {i + 1}"
        sl = w.length / segs[i]
        if sl < 2 * w.radius:
            warnings.append(f"{name}: segments shorter than the wire is thick.")
        if sl > lam / 10:
            warnings.append(f"{name}: segments long for the top frequency.")
        if m.ground.kind != "free" and min(w.a[2], w.b[2]) < -1e-6:
            warnings.append(f"{name} goes below ground level.")
    if sum(segs) > 1500:
        warnings.append(f"{sum(segs)} segments: this may take a while.")
    return segs, warnings


def seg_at(n: int, at: float) -> int:
    return min(n, max(1, math.floor(at * n) + 1))


def _f(x: float) -> str:
    if x == 0:
        return "0"
    a = abs(x)
    if 1e-3 <= a < 1e6:
        return repr(float(f"{x:.9g}"))
    return f"{x:.6e}"


def _fr_cards(freqs: list) -> list:
    if len(freqs) == 1:
        return [f"FR 0 1 0 0 {_f(freqs[0])} 0"]
    step = freqs[1] - freqs[0]
    even = all(i == 0 or abs(v - freqs[i - 1] - step) < abs(step) * 1e-6 + 1e-9 for i, v in enumerate(freqs))
    if even:
        return [f"FR 0 {len(freqs)} 0 0 {_f(freqs[0])} {_f(step)}"]
    return [f"FR 0 1 0 0 {_f(v)} 0" for v in freqs]


def build_deck(m: Model, freqs: list, segs: list, pattern: tuple | None = None,
               currents: bool = False) -> str:
    """pattern: (theta_step, phi_step) degrees for a full radiation pattern."""
    L = [f"CM {m.name}", "CM Built by Ask Elmer Antenna Lab (NEC2 engine)", "CE"]
    for i, w in enumerate(m.wires):
        L.append(f"GW {i + 1} {segs[i]} {_f(w.a[0])} {_f(w.a[1])} {_f(w.a[2])} "
                 f"{_f(w.b[0])} {_f(w.b[1])} {_f(w.b[2])} {_f(w.radius)}")
    g = m.ground
    L.append(f"GE {0 if g.kind == 'free' else 1}")
    sigma = MATERIALS.get(m.material, ("", None))[1]
    if sigma:
        L.append(f"LD 5 0 0 0 {_f(sigma)}")
    for ld in m.loads:
        s = seg_at(segs[ld.wire], ld.at)
        L.append(f"LD {0 if ld.kind == 'series' else 1} {ld.wire + 1} {s} {s} {_f(ld.r)} {_f(ld.l)} {_f(ld.c)}")
    if m.ground_loss > 0:
        for src in m.sources:
            s = seg_at(segs[src.wire], src.at)
            L.append(f"LD 4 {src.wire + 1} {s} {s} {_f(m.ground_loss)} 0")
    for tl in m.lines:
        L.append(f"TL {tl.wire1 + 1} {seg_at(segs[tl.wire1], tl.at1)} {tl.wire2 + 1} "
                 f"{seg_at(segs[tl.wire2], tl.at2)} {_f(tl.z0)} {_f(tl.length)} 0 0 0 0")
    mininec = g.kind == "real" and g.method == "mininec"
    if g.kind == "perfect" or mininec:
        L.append("GN 1")
    elif g.kind == "real":
        L.append(f"GN 2 0 0 0 {_f(g.er)} {_f(g.sigma)}")
    for src in m.sources:
        s = seg_at(segs[src.wire], src.at)
        ph = math.radians(src.phase)
        L.append(f"EX 0 {src.wire + 1} {s} 0 {_f(src.mag * math.cos(ph))} {_f(src.mag * math.sin(ph))}")
    want_currents = currents or (pattern is not None and mininec)
    if not want_currents:
        L.append("PT -1 0 0 0")
    L += _fr_cards(freqs)
    if pattern and not mininec:
        ts, ps = pattern
        tmax = 180 if g.kind == "free" else 90
        L.append(f"RP 0 {round(tmax / ts) + 1} {round(360 / ps)} 1001 0 0 {_f(ts)} {_f(ps)} 0 0")
    else:
        L.append("XQ 0")
    L.append("EN")
    return "\n".join(L) + "\n"


# ---- engine -------------------------------------------------------------------------

class EngineError(RuntimeError):
    pass


def engine_path() -> str | None:
    return shutil.which("nec2c") or next((p for p in ("/usr/bin/nec2c", "/usr/local/bin/nec2c")
                                          if os.path.exists(p)), None)


def run_deck(deck: str, timeout: float = 120) -> str:
    exe = engine_path()
    if not exe:
        raise EngineError("The NEC2 engine (nec2c) is not installed.")
    with tempfile.TemporaryDirectory(prefix="elmerlab-") as d:
        inp, out = os.path.join(d, "in.nec"), os.path.join(d, "out.txt")
        with open(inp, "w") as fh:
            fh.write(deck)
        try:
            r = subprocess.run([exe, "-i", inp, "-o", out], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise EngineError("The engine took too long.") from e
        report = open(out, errors="replace").read() if os.path.exists(out) else ""
        if r.returncode != 0 and not report:
            raise EngineError((r.stderr or r.stdout or f"nec2c exit {r.returncode}").strip()[-200:])
        return report


@dataclass
class FreqResult:
    mhz: float
    feeds: list = field(default_factory=list)      # dicts: tag seg zr zi ir ii power
    currents: list = field(default_factory=list)   # dicts: seg tag mag phase
    pattern: list = field(default_factory=list)    # tuples: theta phi vert horiz total
    input_w: float | None = None
    radiated_w: float | None = None
    efficiency: float | None = None
    average_gain: float | None = None


_NUM = r"([-+0-9.Ee]+)"


def _num(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return float("nan")


def parse_output(text: str) -> tuple[list, list]:
    results: list[FreqResult] = []
    errors: list[str] = []
    cur: FreqResult | None = None
    mode, skip = "none", 0

    def at_freq(mhz):
        for r in results:
            if abs(r.mhz - mhz) < 1e-9:
                return r
        r = FreqResult(mhz)
        results.append(r)
        return r

    for raw in text.split("\n"):
        line = raw.rstrip()
        if re.search(r"\bERROR\b|DATA FAULT", line):
            errors.append(line.strip())
        fm = re.search(r"FREQUENCY\s*[:=]\s*" + _NUM + r"\s*MHZ", line, re.I)
        if fm:
            cur = at_freq(_num(fm.group(1)))
            mode = "none"
            continue
        if cur is None:
            continue
        if "ANTENNA INPUT PARAMETERS" in line:
            mode = "none" if cur.feeds else "feeds"
            skip = 2 if mode == "feeds" else 0
            continue
        if "CURRENTS AND LOCATION" in line:
            mode = "none" if cur.currents else "currents"
            skip = 4
            continue
        if "RADIATION PATTERNS" in line:
            mode, skip = "pattern", 4
            continue
        if "POWER BUDGET" in line or "CHARGE DENSITIES" in line or "NEAR ELECTRIC" in line:
            mode = "none"
        pm = re.search(r"(INPUT POWER|RADIATED POWER|EFFICIENCY)\s*=\s*" + _NUM, line)
        if pm:
            v = _num(pm.group(2))
            if pm.group(1) == "INPUT POWER" and cur.input_w is None:
                cur.input_w = v
            elif pm.group(1) == "RADIATED POWER" and cur.radiated_w is None:
                cur.radiated_w = v
            elif pm.group(1) == "EFFICIENCY" and cur.efficiency is None:
                cur.efficiency = v
            continue
        ag = re.search(r"AVERAGE POWER GAIN\s*[:=]\s*" + _NUM, line)
        if ag:
            cur.average_gain = _num(ag.group(1))
            continue
        if skip > 0:
            skip -= 1
            continue
        t = line.strip()
        if not t:
            if mode == "feeds" and cur.feeds:
                mode = "none"
            if mode == "currents" and cur.currents:
                mode = "none"
            if mode == "pattern" and cur.pattern:
                mode = "none"
            continue
        p = t.split()
        if mode == "feeds" and len(p) >= 11:
            cur.feeds.append({"tag": int(p[0]), "seg": int(p[1]), "ir": _num(p[4]), "ii": _num(p[5]),
                              "zr": _num(p[6]), "zi": _num(p[7]), "power": _num(p[10])})
        elif mode == "currents" and len(p) >= 10:
            cur.currents.append({"seg": int(p[0]), "tag": int(p[1]), "mag": _num(p[8]), "phase": _num(p[9])})
        elif mode == "pattern" and len(p) >= 5 and re.match(r"^[-0-9.]+$", p[0]):
            cur.pattern.append((_num(p[0]), _num(p[1]), _num(p[2]), _num(p[3]), _num(p[4])))
    return results, sorted(set(errors))
