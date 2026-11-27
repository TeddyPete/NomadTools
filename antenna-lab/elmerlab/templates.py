"""Antenna templates: parametric antennas that build a NEC model from a few settings.

Port of Ask Elmer's Antenna Lab templates (app/src/workshop/lab/templates.ts).
Coordinates are metres, Z is up. Wire antennas run along Y, so broadside is
+-X; beams fire toward +X.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .nec import C0, Load, Model, Source, TLine, Wire

# ---- bands, conductors ------------------------------------------------------------

HAM_BANDS = [  # id, name, lo, hi, design MHz
    ("160m", "160 m", 1.8, 2.0, 1.9), ("80m", "80 m", 3.5, 4.0, 3.75),
    ("60m", "60 m", 5.3305, 5.4065, 5.36), ("40m", "40 m", 7.0, 7.3, 7.15),
    ("30m", "30 m", 10.1, 10.15, 10.125), ("20m", "20 m", 14.0, 14.35, 14.175),
    ("17m", "17 m", 18.068, 18.168, 18.118), ("15m", "15 m", 21.0, 21.45, 21.225),
    ("12m", "12 m", 24.89, 24.99, 24.94), ("10m", "10 m", 28.0, 29.7, 28.4),
    ("6m", "6 m", 50, 54, 52), ("2m", "2 m", 144, 148, 146), ("1.25m", "1.25 m", 222, 225, 223.5),
    ("70cm", "70 cm", 420, 450, 440), ("33cm", "33 cm", 902, 928, 915), ("23cm", "23 cm", 1240, 1300, 1270),
]


def band_mhz(bid: str) -> float:
    return next((b[4] for b in HAM_BANDS if b[0] == bid), 0.0)


def band_name(bid: str) -> str:
    return next((b[1] for b in HAM_BANDS if b[0] == bid), bid)


def find_band(mhz: float):
    return next((b for b in HAM_BANDS if b[2] - 1e-9 <= mhz <= b[3] + 1e-9), None)


def nearest_band(target: float) -> str:
    cands = [b for b in HAM_BANDS if b[4] < 60 and b[0] != "60m"]
    return min(cands, key=lambda b: abs(math.log(b[4] / target)))[0]


def awg_mm(g: int) -> float:
    return 0.127 * 92 ** ((36 - g) / 39)


CONDUCTORS = [(f"awg{g}", f"{g} AWG wire", awg_mm(g) / 2000) for g in (10, 12, 14, 16, 18, 20, 22)] + [
    (v, label, d / 2000) for v, label, d in (
        ("tube6", "1/4 in tube", 6.35), ("tube10", "3/8 in tube", 9.53), ("tube13", "1/2 in tube", 12.7),
        ("tube16", "5/8 in tube", 15.9), ("tube19", "3/4 in tube", 19.05), ("tube22", "7/8 in Cu pipe", 22.2),
        ("tube25", "1 in tube", 25.4), ("tube32", "1-1/4 in tube", 31.75))]


def radius_of(cid) -> float:
    return next((r for v, _l, r in CONDUCTORS if v == cid), awg_mm(14) / 2000)


def wl(mhz: float) -> float:
    return C0 / mhz


def coil_turns(uh: float, form_in: float, wire_in: float, pitch_factor: float = 1.5):
    """Wheeler's single-layer coil formula solved for turns."""
    pitch = wire_in * pitch_factor
    d = form_in + wire_in
    a, b, c = d * d, -40 * uh * pitch, -18 * uh * d
    n = (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)
    return n, n * pitch, math.pi * d * n


def coil_recipe(uh: float, form_in: float = 1.5) -> str:
    n, ln, wire = coil_turns(uh, form_in, 0.0641)
    return (f"about {n:.1f} turns of 14 AWG on a {form_in} in form, one wire width apart "
            f"(winding {ln:.1f} in long, {wire / 12:.1f} ft of wire)")


RADIAL_LOSS = [(0, 40, "Ground rod only"), (4, 28, "4 radials"), (8, 18, "8 radials"), (16, 12, "16 radials"),
               (32, 7, "32 radials"), (60, 4, "60 radials"), (120, 2, "120 radials")]


# ---- template structure ------------------------------------------------------------

@dataclass
class Param:
    id: str
    label: str
    kind: str           # length angle count percent select ohms uh pf number
    min: float | None = None
    max: float | None = None
    options: list = field(default_factory=list)   # (value, label)
    help: str = ""
    advanced: bool = False


@dataclass
class Cut:
    part: str
    length: float | None = None
    qty: int | None = None
    note: str = ""


@dataclass
class Built:
    wires: list
    sources: list
    loads: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    ground_loss: float = 0.0
    cut: list = field(default_factory=list)
    notes: list = field(default_factory=list)


@dataclass
class Template:
    id: str
    name: str
    family: str
    blurb: str
    default_mhz: float
    params: object          # (p) -> list[Param]
    defaults: object        # (mhz) -> dict
    build: object           # (p, mhz) -> Built
    tune: dict | None = None    # param, mode (reactance swr magloop), lo, hi, label
    feed: str = "balanced"
    device: str = "choke-1-1"
    ground: str = "real"        # real | mininec | free
    span: float | None = None
    multiband: bool = False

    def model(self, p: dict, mhz: float, ground, material: str = "copper") -> Model:
        b = self.build(p, mhz)
        return Model(self.name, b.wires, b.sources, b.loads, b.lines, material, ground, b.ground_loss)


def V(x, y, z):
    return (float(x), float(y), float(z))


def n(p, k) -> float:
    return float(p[k])


def conductor_param(advanced=False):
    return Param("conductor", "Wire or tubing", "select", options=[(v, l) for v, l, _ in CONDUCTORS], advanced=advanced)


def height_param(label="Height above ground", help=""):
    return Param("height", label, "length", 0.2, 300, help=help)


def band_options(extra=()):
    return list(extra) + [(b[0], b[1]) for b in HAM_BANDS if b[4] < 60]


def loop_wires(pts, r, feed_at, label, feed_len, feed_segs=1):
    """A closed polygon with the feed in the middle of a short wire at feed_at (0-1 around)."""
    edges = [(a, pts[(i + 1) % len(pts)]) for i, a in enumerate(pts)]
    lens = [math.dist(a, b) for a, b in edges]
    per = sum(lens)
    d = ((feed_at % 1) + 1) % 1 * per
    e = 0
    while e < len(edges) - 1 and d > lens[e]:
        d -= lens[e]
        e += 1
    wires, feed_index = [], 0
    for i, (a, b) in enumerate(edges):
        if i != e:
            wires.append(Wire(a, b, r, label, label))
            continue
        L = lens[i]
        half = min(feed_len / 2, L / 3)
        t1 = max(half, min(L - half, d)) - half
        t2 = t1 + 2 * half

        def at(t, a=a, b=b, L=L):
            return tuple(a[k] + (b[k] - a[k]) * t / L for k in range(3))
        if t1 > 1e-6:
            wires.append(Wire(a, at(t1), r, label, label))
        feed_index = len(wires)
        wires.append(Wire(at(t1), at(t2), r, f"{label} (feed)", label, feed_segs))
        if L - t2 > 1e-6:
            wires.append(Wire(at(t2), b, r, label, label))
    return wires, feed_index


def hdef(mhz, k=0.5, lo=3, hi=20):
    return min(max(wl(mhz) * k, lo), hi)


# ---- wire antennas -----------------------------------------------------------------

def _dipole_build(p, mhz):
    L, h = n(p, "length"), n(p, "height")
    return Built([Wire(V(0, -L / 2, h), V(0, L / 2, h), radius_of(p["conductor"]), "Dipole", "Dipole")],
                 [Source(0, 0.5)],
                 cut=[Cut("Leg (center to end insulator)", L / 2, 2), Cut("Total, end to end", L)])


dipole = Template(
    "dipole", "Half-wave dipole", "Wire antennas",
    "The reference antenna: a center-fed half-wave wire. Simple, efficient and predictable.", 14.175,
    lambda p: [Param("length", "Total length", "length", 0.1, 200), height_param(), conductor_param()],
    lambda mhz: {"length": 143 / mhz, "height": hdef(mhz), "conductor": "awg14"},
    _dipole_build, {"param": "length", "mode": "reactance", "label": "total length"})


def _invv_build(p, mhz):
    L, h = n(p, "leg"), n(p, "height")
    half = math.radians(n(p, "apex") / 2)
    c = wl(mhz) / 80
    r = radius_of(p["conductor"])
    dy, dz = L * math.sin(half), L * math.cos(half)
    notes = ["Leg ends are under 1 m (3 ft) off the ground: keep them out of reach."] if h - dz < 1 else []
    return Built([Wire(V(0, -c / 2, h), V(0, c / 2, h), r, "Feed point", "Feed", 1),
                  Wire(V(0, -c / 2, h), V(0, -c / 2 - dy, h - dz), r, "Leg 1", "Leg 1"),
                  Wire(V(0, c / 2, h), V(0, c / 2 + dy, h - dz), r, "Leg 2", "Leg 2")],
                 [Source(0, 0.5)],
                 cut=[Cut("Leg (apex to end insulator)", L + c / 2, 2), Cut("End-to-end span", 2 * dy + c),
                      Cut("Height of the leg ends", h - dz)], notes=notes)


inverted_v = Template(
    "inverted-v", "Inverted V", "Wire antennas",
    "A dipole hung from one center support with the legs sloping down. Closer to 50 ohms than a flat dipole.", 7.15,
    lambda p: [Param("leg", "Each leg", "length", 0.1, 100), height_param("Apex height"),
               Param("apex", "Apex angle", "angle", 60, 175, help="Angle between the legs."), conductor_param()],
    lambda mhz: {"leg": 143 / mhz / 2 * 0.97, "height": hdef(mhz, 0.3, 6, 18), "apex": 110, "conductor": "awg14"},
    _invv_build, {"param": "leg", "mode": "reactance", "label": "leg length"})


def _ocfd_build(p, mhz):
    L, h, off = n(p, "length"), n(p, "height"), n(p, "offset") / 100
    return Built([Wire(V(0, -L / 2, h), V(0, L / 2, h), radius_of(p["conductor"]), "OCFD", "OCFD")],
                 [Source(0, off)],
                 cut=[Cut("Short leg", L * off), Cut("Long leg", L * (1 - off)), Cut("Total", L)],
                 notes=["Add a second choke on the coax a few feet below the balun: OCFDs push "
                        "common-mode current onto the feed line."])


ocfd = Template(
    "ocfd", "Off-center-fed dipole", "Wire antennas",
    "A dipole fed about a third of the way in. Around 200 ohms on several bands, matched with a 4:1 current balun.",
    7.15,
    lambda p: [Param("length", "Total length", "length", 1, 200),
               Param("offset", "Feed point from one end", "percent", 5, 50, help="33% is the classic Windom split."),
               height_param(), conductor_param()],
    lambda mhz: {"length": 143 / mhz, "offset": 33, "height": hdef(mhz, 0.3, 6, 18), "conductor": "awg14"},
    _ocfd_build, {"param": "length", "mode": "swr", "label": "total length"},
    device="balun-4-1", span=0.04, multiband=True)


def _efhw_build(p, mhz):
    L, h1, h2 = n(p, "length"), n(p, "height"), n(p, "farHeight")
    dz = h2 - h1
    y = math.sqrt(max(L * L - dz * dz, L * L / 4))
    cp = min(n(p, "counterpoise"), h1 - 0.1)
    r = radius_of(p["conductor"])
    notes = (["The counterpoise was shortened to fit under the feed point. Run it along the ground or raise the feed."]
             if n(p, "counterpoise") > h1 - 0.1 else [])
    return Built([Wire(V(0, 0, h1), V(0, y, h2), r, "Radiator", "Radiator"),
                  Wire(V(0, 0, h1), V(0, 0, h1 - max(cp, 0.1)), 0.0025, "Counterpoise / coax shield", "Counterpoise")],
                 [Source(0, 0)],
                 cut=[Cut("Radiator (transformer to far insulator)", L),
                      Cut("Counterpoise, or coax to the first choke", max(cp, 0.1))], notes=notes)


efhw = Template(
    "efhw", "End-fed half wave", "Wire antennas",
    "One half-wave wire fed at the end through a 49:1 transformer. Resonant on its harmonics too.", 7.15,
    lambda p: [Param("length", "Radiator length", "length", 1, 200),
               Param("height", "Feed end height", "length", 0.3, 100),
               Param("farHeight", "Far end height", "length", 0.3, 100),
               Param("counterpoise", "Counterpoise", "length", 0.05, 20, help="About 0.05 wavelength."),
               conductor_param()],
    lambda mhz: {"length": 143 / mhz * 1.02, "height": 3, "farHeight": min(10, 143 / mhz * 0.5),
                 "counterpoise": wl(mhz) * 0.05, "conductor": "awg18"},
    _efhw_build, {"param": "length", "mode": "swr", "label": "radiator length"},
    feed="end-fed", device="unun-49-1", span=0.04, multiband=True)


def _fan_build(p, mhz):
    h, r = n(p, "height"), radius_of(p["conductor"])
    c = wl(mhz) / 100
    sp = n(p, "spread")
    wires = [Wire(V(0, -c / 2, h), V(0, c / 2, h), r, "Feed point", "Feed", 1)]
    cut = []

    def add(total, k, name):
        leg = total / 2 - c / 2
        dz = k * sp
        dy = math.sqrt(max(leg * leg - dz * dz, 0.01))
        wires.append(Wire(V(0, -c / 2, h), V(0, -c / 2 - dy, h - dz), r, f"{name} leg", name))
        wires.append(Wire(V(0, c / 2, h), V(0, c / 2 + dy, h - dz), r, f"{name} leg", name))
        cut.append(Cut(f"{name}: each leg", total / 2, 2))
    add(n(p, "length"), 0, f"{mhz:.2f} MHz dipole")
    k = 1
    for b, t in (("band2", "trim2"), ("band3", "trim3")):
        bid = str(p[b])
        if bid == "none" or not band_mhz(bid):
            continue
        add(143 / band_mhz(bid) * (1 + n(p, t) / 100), k, f"{band_name(bid)} dipole")
        k += 1
    return Built(wires, [Source(0, 0.5)], cut=cut,
                 notes=["Spread the shorter dipoles away from the longer ones with spacers; "
                        "the closer they hang, the more they interact."])


fan = Template(
    "fan-dipole", "Fan dipole", "Wire antennas",
    "Two or three dipoles on one feed point, each resonant on its own band. No tuner, no traps.", 7.15,
    lambda p: [Param("length", "Main dipole length", "length", 1, 200),
               Param("band2", "Second band", "select", options=band_options([("none", "None")])),
               Param("trim2", "Second dipole trim", "percent", -15, 15),
               Param("band3", "Third band", "select", options=band_options([("none", "None")])),
               Param("trim3", "Third dipole trim", "percent", -15, 15),
               Param("spread", "Spacing at the ends", "length", 0.05, 3), height_param(), conductor_param(True)],
    lambda mhz: {"length": 143 / mhz, "band2": nearest_band(mhz * 2), "trim2": -2, "band3": "none", "trim3": -2,
                 "spread": max(0.15, wl(mhz) / 140), "height": hdef(mhz, 0.3, 6, 18), "conductor": "awg14"},
    _fan_build, {"param": "length", "mode": "reactance", "label": "main dipole length"}, multiband=True)


def _trap_build(p, mhz):
    h, r = n(p, "height"), radius_of(p["conductor"])
    fh = band_mhz(str(p["highBand"])) or mhz * 2
    C = n(p, "trapPf") * 1e-12
    w = 2 * math.pi * fh * 1e6
    L = 1 / (w * w * C)
    r_par = n(p, "trapQ") * w * L
    inner, outer = n(p, "inner"), n(p, "outer")
    t = min(wl(fh) / 60, 0.3)
    y1 = inner / 2
    wires = [Wire(V(0, -y1, h), V(0, y1, h), r, "Inner dipole", "Inner dipole"),
             Wire(V(0, -y1, h), V(0, -y1 - t, h), r, "Trap", "Trap 1", 1),
             Wire(V(0, y1, h), V(0, y1 + t, h), r, "Trap", "Trap 2", 1),
             Wire(V(0, -y1 - t, h), V(0, -y1 - t - outer, h), r, "Outer extension", "Outer 1"),
             Wire(V(0, y1 + t, h), V(0, y1 + t + outer, h), r, "Outer extension", "Outer 2")]
    loads = [Load(i, 0.5, "parallel", r_par, L, C, "Trap") for i in (1, 2)]
    uh = L * 1e6
    return Built(wires, [Source(0, 0.5)], loads,
                 cut=[Cut("Inner leg (feed to trap)", inner / 2, 2), Cut("Outer extension", outer, 2),
                      Cut(f"Trap: {uh:.2f} uH coil + {n(p, 'trapPf'):g} pF at {fh:.3f} MHz", None, 2,
                          f"Coil: {coil_recipe(uh, 2)}. Capacitor: silver mica, 1 kV or more.")],
                 notes=[f"Each trap is a {uh:.2f} uH coil in parallel with {n(p, 'trapPf'):g} pF. "
                        "Check trap resonance with a NanoVNA before installing."])


def _trap_defaults(mhz):
    hb = nearest_band(mhz * 2)
    return {"highBand": hb, "inner": 143 / band_mhz(hb), "outer": (143 / mhz - 143 / band_mhz(hb)) * 0.35,
            "trapPf": 50, "trapQ": 150, "height": hdef(mhz, 0.3, 6, 18), "conductor": "awg14"}


trap = Template(
    "trap-dipole", "Trap dipole", "Wire antennas",
    "A dipole for a high band with parallel LC traps, then extra wire that makes it resonant on a lower band too.",
    7.15,
    lambda p: [Param("highBand", "Trap band (higher band)", "select", options=band_options()),
               Param("inner", "Inner dipole (trap to trap)", "length", 0.5, 100),
               Param("outer", "Each outer extension", "length", 0.1, 60),
               Param("trapPf", "Trap capacitor", "pf", 10, 500),
               Param("trapQ", "Trap coil Q", "number", 20, 400, advanced=True), height_param(), conductor_param(True)],
    _trap_defaults, _trap_build, {"param": "outer", "mode": "reactance", "label": "outer extensions"},
    multiband=True)


def _doublet_build(p, mhz):
    L, h = n(p, "length"), n(p, "height")
    z = float(p["lineZ"])
    vf = 0.8 if z == 300 else 0.97 if z == 600 else 0.91
    return Built([Wire(V(0, -L / 2, h), V(0, L / 2, h), radius_of(p["conductor"]), "Flat top", "Flat top"),
                  Wire(V(-500, 0, h), V(-500, 0, h + 0.1), 0.001, "Coax end of the line (model only)", "Model only", 1)],
                 [Source(1, 0.5)], lines=[TLine(0, 0.5, 1, 0.5, z, n(p, "lineLength") / vf)],
                 cut=[Cut("Each half of the flat top", L / 2, 2), Cut(f"{z:g} ohm line", n(p, "lineLength"))],
                 notes=["SWR is at the bottom of the ladder line, where the coax or tuner connects."])


DOUBLET_PRESETS = {"g5rv": (31.1, 10.36), "g5rvjr": (15.55, 5.18), "doublet88": (26.8, 15)}

doublet = Template(
    "doublet", "Doublet / G5RV", "Wire antennas",
    "A center-fed wire with open-wire or window line. Multiband with a tuner; the G5RV is the classic version.",
    14.175,
    lambda p: [Param("preset", "Starting design", "select", options=[
                   ("g5rv", "G5RV 102 ft"), ("g5rvjr", "G5RV Jr 51 ft"), ("doublet88", "88 ft doublet"),
                   ("custom", "Custom")]),
               Param("length", "Flat top length", "length", 1, 200),
               Param("lineLength", "Ladder line length", "length", 0.5, 100),
               Param("lineZ", "Line impedance", "select", options=[("450", "450 ohm window"),
                                                                    ("300", "300 ohm twin lead"),
                                                                    ("600", "600 ohm open wire")]),
               height_param(), conductor_param(True)],
    lambda mhz: {"preset": "g5rv", "length": 31.1, "lineLength": 10.36, "lineZ": "450", "height": 10,
                 "conductor": "awg14"},
    _doublet_build, None, feed="ladder", span=0.04, multiband=True)


# ---- verticals -----------------------------------------------------------------------

def _gv_build(p, mhz):
    L = n(p, "length")
    loss = next((o for c, o, _ in RADIAL_LOSS if str(c) == str(p["radials"])), 12)
    k = int(p["radials"]) or None
    return Built([Wire(V(0, 0, 0), V(0, 0, L), radius_of(p["conductor"]), "Radiator", "Radiator")],
                 [Source(0, 0)], ground_loss=loss,
                 cut=[Cut("Radiator", L), Cut("Radial (each, on or just under the ground)", L, k)],
                 notes=[f"Modelled like EZNEC's MININEC ground: currents over perfect ground, the pattern "
                        f"over real ground, plus about {loss} ohms of radial loss."])


ground_vertical = Template(
    "vertical", "Ground-mounted vertical", "Verticals",
    "A quarter-wave vertical at ground level over radials. Low takeoff angle for DX; radials decide efficiency.",
    7.15,
    lambda p: [Param("length", "Radiator height", "length", 0.5, 60),
               Param("radials", "Radials", "select", options=[(str(c), f"{lab} ({o} ohm)") for c, o, lab in RADIAL_LOSS]),
               conductor_param()],
    lambda mhz: {"length": wl(mhz) / 4 * 0.97, "radials": "16", "conductor": "tube32"},
    _gv_build, {"param": "length", "mode": "reactance", "label": "radiator height"},
    feed="unbalanced", ground="mininec")


def _gp_build(p, mhz):
    L, rl, h = n(p, "length"), n(p, "radialLength"), n(p, "height")
    k = round(n(p, "radials"))
    d = math.radians(n(p, "droop"))
    r = radius_of(p["conductor"])
    wires = [Wire(V(0, 0, h), V(0, 0, h + L), r, "Radiator", "Radiator")]
    for i in range(k):
        a = 2 * math.pi * i / k + math.pi / 4
        wires.append(Wire(V(0, 0, h), V(rl * math.cos(d) * math.cos(a), rl * math.cos(d) * math.sin(a),
                                         h - rl * math.sin(d)), r, f"Radial {i + 1}", "Radials"))
    notes = (["Radial tips come within 30 cm (1 ft) of the ground. Raise it or reduce the droop."]
             if h - rl * math.sin(d) < 0.3 else [])
    return Built(wires, [Source(0, 0)], cut=[Cut("Radiator", L), Cut("Radial", rl, k)], notes=notes)


ground_plane = Template(
    "ground-plane", "Elevated ground plane", "Verticals",
    "A quarter-wave vertical on a mast with sloping radials. The go-to for 2 m, and an efficient HF vertical.", 146,
    lambda p: [Param("length", "Radiator", "length", 0.05, 40), Param("radialLength", "Each radial", "length", 0.05, 40),
               Param("radials", "Number of radials", "count", 2, 8),
               Param("droop", "Radial droop", "angle", 0, 60, help="About 45 deg brings the feed close to 50 ohms."),
               height_param("Feed point height"), conductor_param()],
    lambda mhz: {"length": wl(mhz) / 4 * 0.96, "radialLength": wl(mhz) / 4 * 1.02, "radials": 4, "droop": 40,
                 # high enough that the drooping radials clear the ground by 1.5 m
                 "height": 6 if mhz > 50 else max(min(wl(mhz) * 0.15, 10), wl(mhz) / 4 * 1.02 * math.sin(math.radians(40)) + 1.5),
                 "conductor": "tube6" if mhz > 50 else "awg14"},
    _gp_build, {"param": "length", "mode": "reactance", "label": "radiator"}, feed="unbalanced")


def _58_build(p, mhz):
    gp = _gp_build({**p, "droop": 0}, mhz)
    L = n(p, "coil") * 1e-6
    gp.loads = [Load(0, 0, "series", 2 * math.pi * mhz * 1e6 * L / 200, L, 0, "Base coil")]
    gp.cut.append(Cut(f"Base coil: about {L * 1e6:.2f} uH in series with the radiator", None, None,
                      coil_recipe(L * 1e6, 0.5 if mhz > 50 else 1.5)))
    return gp


five_eighths = Template(
    "five-eighths", "5/8-wave vertical", "Verticals",
    "A longer vertical with a base matching coil. Lower angle and more gain than a quarter wave on VHF.", 146,
    lambda p: [Param("length", "Radiator", "length", 0.1, 60), Param("coil", "Base matching coil", "uh", 0.01, 100),
               Param("radialLength", "Each radial", "length", 0.05, 40),
               Param("radials", "Number of radials", "count", 2, 8), height_param("Feed point height"),
               conductor_param()],
    lambda mhz: {"length": wl(mhz) * 0.625 * 0.97, "coil": 45 / mhz, "radialLength": wl(mhz) / 4 * 1.02,
                 "radials": 4, "height": 6 if mhz > 50 else 3, "conductor": "tube6" if mhz > 50 else "tube25"},
    _58_build, {"param": "coil", "mode": "reactance", "lo": 0.3, "hi": 3, "label": "base coil"}, feed="unbalanced")


def _lv_defaults(mhz):
    H = min(2.4, wl(mhz) * 0.1)
    a = radius_of("tube10")
    z0 = 60 * (math.log(2 * H / a) - 1)
    x = z0 / math.tan(2 * math.pi * H / wl(mhz))
    return {"length": H, "coilAt": 50, "coil": x * 2 / (2 * math.pi * mhz * 1e6) * 1e6, "q": 150, "mountLoss": 8,
            "conductor": "tube10"}


def _lv_build(p, mhz):
    H, L, at = n(p, "length"), n(p, "coil") * 1e-6, n(p, "coilAt") / 100
    w = 2 * math.pi * mhz * 1e6
    return Built([Wire(V(0, 0, 0), V(0, 0, H), radius_of(p["conductor"]), "Whip", "Whip", 21)], [Source(0, 0)],
                 [Load(0, at, "series", w * L / n(p, "q"), L, 0, "Loading coil")], ground_loss=n(p, "mountLoss"),
                 cut=[Cut("Whip, overall", H),
                      Cut(f"Loading coil: about {L * 1e6:.1f} uH, {round(at * 100)}% of the way up", None, None,
                          coil_recipe(L * 1e6, 1.5))],
                 notes=["Short verticals have low feed resistance, so coil and ground losses eat a big share "
                        "of the power. A higher coil and a better ground both help."])


loaded_vertical = Template(
    "loaded-vertical", "Coil-loaded short vertical", "Verticals",
    "A short whip with a loading coil: mobile HF, hamsticks and space-limited verticals.", 7.15,
    lambda p: [Param("length", "Whip height", "length", 0.3, 30), Param("coilAt", "Coil position", "percent", 0, 80,
                                                                          help="0% base, 50% center."),
               Param("coil", "Loading coil", "uh", 0.1, 500), Param("q", "Coil Q", "number", 20, 500),
               Param("mountLoss", "Ground or mount loss", "ohms", 0, 50, help="Car body 5-15 ohms."),
               conductor_param()],
    _lv_defaults, _lv_build, {"param": "coil", "mode": "reactance", "lo": 0.3, "hi": 3, "label": "loading coil"},
    feed="unbalanced", ground="mininec", span=0.015)


def _jpole_build(p, mhz):
    Ll, Ls, sp, h = n(p, "long"), n(p, "stub"), n(p, "spacing"), n(p, "height")
    t = min(n(p, "tap"), Ls * 0.8)
    r = min(radius_of(p["conductor"]), sp / 4)
    return Built([Wire(V(0, 0, h), V(sp, 0, h), r, "Shorted bottom", "Bottom", 1),
                  Wire(V(0, 0, h), V(0, 0, h + t), r, "Long element", "Long element"),
                  Wire(V(0, 0, h + t), V(0, 0, h + Ll), r, "Long element", "Long element"),
                  Wire(V(sp, 0, h), V(sp, 0, h + t), r, "Stub", "Stub"),
                  Wire(V(sp, 0, h + t), V(sp, 0, h + Ls), r, "Stub", "Stub"),
                  Wire(V(0, 0, h + t), V(sp, 0, h + t), r, "Feed", "Feed", 1)],
                 [Source(5, 0.5)],
                 cut=[Cut("Long element (from the shorting bar)", Ll), Cut("Short element (stub)", Ls),
                      Cut("Spacing, center to center", sp), Cut("Feed tap above the bottom (slide to tune)", t)],
                 notes=["J-poles need a good choke at the feed, or the coax becomes part of the antenna."])


jpole = Template(
    "j-pole", "J-pole", "Verticals",
    "A half-wave radiator end-fed by a quarter-wave matching stub. Popular for 2 m and 70 cm, no radials.", 146,
    lambda p: [Param("long", "Long element", "length", 0.1, 30), Param("stub", "Short element (stub)", "length", 0.05, 10),
               Param("spacing", "Spacing", "length", 0.005, 1), Param("tap", "Feed tap height", "length", 0.005, 3),
               height_param("Bottom height (on the mast)"), conductor_param()],
    lambda mhz: {"long": 0.75 * wl(mhz) * 0.95, "stub": 0.25 * wl(mhz) * 0.95, "spacing": 0.025 * wl(mhz),
                 "tap": 0.025 * wl(mhz), "height": 5 if mhz > 50 else 3, "conductor": "tube13" if mhz > 50 else "tube25"},
    _jpole_build, {"param": "tap", "mode": "swr", "lo": 0.4, "hi": 2.5, "label": "feed tap"}, feed="unbalanced")


# ---- beams ---------------------------------------------------------------------------

YAGI_SPACING = [0, 0.2, 0.15, 0.2, 0.25, 0.3, 0.3, 0.35, 0.35, 0.4]


def yagi_defaults(mhz, count=3, conductor=None):
    conductor = conductor or ("tube6" if mhz > 50 else "tube19")
    w = wl(mhz)
    p = {"count": count, "conductor": conductor, "height": 6 if mhz > 50 else max(10, w * 0.5)}
    x = 0.0
    for i in range(count):
        x += YAGI_SPACING[i] * w * (0.65 if count == 2 and i == 1 else 1)
        ln = 0.495 if i == 0 else 0.473 if i == 1 else 0.445 - 0.004 * (i - 2)
        p[f"len{i}"] = ln * w * (0.985 if radius_of(conductor) / w > 0.002 else 1)
        p[f"pos{i}"] = x
    return p


def _el_name(i):
    return "Reflector" if i == 0 else "Driven element" if i == 1 else f"Director {i - 1}"


def _yagi_params(p):
    out = [Param("count", "Elements", "count", 2, 10), height_param("Boom height"), conductor_param()]
    for i in range(round(float(p.get("count", 3)))):
        out.append(Param(f"len{i}", f"{_el_name(i)} length", "length", 0.01, 100))
        if i:
            out.append(Param(f"pos{i}", f"{_el_name(i)} position", "length", 0, 200))
    return out


def _yagi_build(p, mhz):
    count, h, r = round(n(p, "count")), n(p, "height"), radius_of(p["conductor"])
    wires, cut = [], []
    for i in range(count):
        L = n(p, f"len{i}")
        x = 0 if i == 0 else n(p, f"pos{i}")
        wires.append(Wire(V(x, -L / 2, h), V(x, L / 2, h), r, _el_name(i), _el_name(i)))
        cut.append(Cut(_el_name(i), L, None, f"{x:.3f} m from the reflector" if i else "Back of the boom"))
    cut.append(Cut("Boom length (plus overhang)", n(p, f"pos{count - 1}") if count > 1 else 0))
    return Built(wires, [Source(1, 0.5)], cut=cut)


yagi = Template(
    "yagi", "Yagi beam", "Beams",
    "A driven element, a reflector and directors on a boom: gain and a strong front-to-back. 2 to 10 elements.", 146,
    _yagi_params, yagi_defaults, _yagi_build, {"param": "len1", "mode": "reactance", "label": "driven element"},
    feed="beam")


def _moxon_build(p, mhz):
    w = wl(mhz)
    r = radius_of(p["conductor"])
    x = math.log10(2 * r / w)
    A = (-0.0008571428571 * x * x - 0.009571428571 * x + 0.3398571429) * w
    B = (-0.002142857143 * x * x - 0.02035714286 * x + 0.008285714286) * w
    C = (0.001809523381 * x * x + 0.01780952381 * x + 0.05164285714) * w
    D = (0.001 * x + 0.07178571429) * w
    k = n(p, "scale") / 100
    a, b, c, d = A * k, B * k, C * k, D * k
    E = b + c + d
    h = n(p, "height")
    xf, xr = E / 2, -E / 2
    return Built([Wire(V(xf, -a / 2, h), V(xf, a / 2, h), r, "Driven element", "Driven"),
                  Wire(V(xf, -a / 2, h), V(xf - b, -a / 2, h), r, "Driven tail", "Driven"),
                  Wire(V(xf, a / 2, h), V(xf - b, a / 2, h), r, "Driven tail", "Driven"),
                  Wire(V(xr, -a / 2, h), V(xr, a / 2, h), r, "Reflector", "Reflector"),
                  Wire(V(xr, -a / 2, h), V(xr + d, -a / 2, h), r, "Reflector tail", "Reflector"),
                  Wire(V(xr, a / 2, h), V(xr + d, a / 2, h), r, "Reflector tail", "Reflector")],
                 [Source(0, 0.5)],
                 cut=[Cut("A: width", a), Cut("B: driven tails", b, 2), Cut("C: gap between tips", c),
                      Cut("D: reflector tails", d, 2), Cut("E: depth", E), Cut("Driven wire total", a + 2 * b),
                      Cut("Reflector wire total", a + 2 * d)])


moxon = Template(
    "moxon", "Moxon rectangle", "Beams",
    "A 2-element beam with folded-back tips: about 6 dBi, a deep rear null and a 50 ohm feed.", 14.175,
    lambda p: [Param("scale", "Size trim", "percent", 85, 115, help="Scales every dimension; 100% is the published design."),
               height_param(), conductor_param()],
    lambda mhz: {"scale": 100, "height": 6 if mhz > 50 else max(8, wl(mhz) * 0.5),
                 "conductor": "tube6" if mhz > 50 else "awg12"},
    _moxon_build, {"param": "scale", "mode": "swr", "lo": 0.95, "hi": 1.05, "label": "size trim"}, feed="beam")


def _quad_build(p, mhz):
    h, r, sp = n(p, "height"), radius_of(p["conductor"]), n(p, "spacing")

    def sq(x, per):
        s = per / 4
        return [V(x, -s / 2, h - s / 2), V(x, s / 2, h - s / 2), V(x, s / 2, h + s / 2), V(x, -s / 2, h + s / 2)]
    dw, fi = loop_wires(sq(sp, n(p, "driven")), r, 1 / 8, "Driven loop", wl(mhz) / 60)
    rp = sq(0, n(p, "reflector"))
    ref = [Wire(a, rp[(i + 1) % 4], r, "Reflector loop", "Reflector loop") for i, a in enumerate(rp)]
    return Built(dw + ref, [Source(fi, 0.5)],
                 cut=[Cut("Driven loop wire", n(p, "driven"), None, f"Each side {n(p, 'driven') / 4:.3f} m"),
                      Cut("Reflector loop wire", n(p, "reflector"), None, f"Each side {n(p, 'reflector') / 4:.3f} m"),
                      Cut("Boom (element spacing)", sp)])


quad = Template(
    "quad", "Cubical quad", "Beams",
    "Two full-wave square loops: about 7 dBi, a quiet receiver and a low takeoff angle for its height.", 14.175,
    lambda p: [Param("driven", "Driven loop perimeter", "length", 0.5, 200),
               Param("reflector", "Reflector perimeter", "length", 0.5, 200),
               Param("spacing", "Element spacing", "length", 0.05, 40), height_param("Loop center height"),
               conductor_param()],
    lambda mhz: {"driven": wl(mhz) * 1.02, "reflector": wl(mhz) * 1.05, "spacing": wl(mhz) * 0.15,
                 "height": 6 if mhz > 50 else max(10, wl(mhz) * 0.6), "conductor": "awg12" if mhz > 50 else "awg14"},
    _quad_build, {"param": "driven", "mode": "reactance", "label": "driven loop"}, feed="loop", device="qsection-75")


# ---- loops ---------------------------------------------------------------------------

def _delta_build(p, mhz):
    P, h = n(p, "perimeter"), n(p, "height")
    sd = P / 3
    tri = sd * math.sqrt(3) / 2
    pts = [V(0, -sd / 2, h - tri), V(0, sd / 2, h - tri), V(0, 0, h)]
    where = str(p["feedAt"])
    at = 1 / 6 if where == "bottom" else (1 / 3 + (sd - P / 4) / P) if where == "side" else 0.002
    wires, fi = loop_wires(pts, radius_of(p["conductor"]), at, "Delta loop", wl(mhz) / 60)
    notes = (["The bottom wire is low: keep it out of reach. Loops carry high RF voltage away from the feed."]
             if h - tri < 1.5 else [])
    return Built(wires, [Source(fi, 0.5)], cut=[Cut("Loop wire, total", P), Cut("Each side", sd, 3),
                                                Cut("Bottom wire height", h - tri)], notes=notes)


delta = Template(
    "delta-loop", "Delta loop", "Loops",
    "A full-wave triangle from one high support. Feed the bottom for horizontal, a side for vertical polarization.",
    7.15,
    lambda p: [Param("perimeter", "Perimeter", "length", 0.5, 400), height_param("Apex height"),
               Param("feedAt", "Feed point", "select", options=[("bottom", "Bottom center (horiz)"),
                                                                ("side", "Down a side (vert)"),
                                                                ("corner", "Bottom corner (mixed)")]),
               conductor_param()],
    lambda mhz: {"perimeter": wl(mhz) * 1.04, "height": hdef(mhz, 0.45, 8, 22), "feedAt": "bottom", "conductor": "awg14"},
    _delta_build, {"param": "perimeter", "mode": "reactance", "label": "perimeter"}, feed="loop", device="qsection-75")


def _sky_build(p, mhz):
    P, h = n(p, "perimeter"), n(p, "height")
    sd = P / 4
    pts = [V(-sd / 2, -sd / 2, h), V(sd / 2, -sd / 2, h), V(sd / 2, sd / 2, h), V(-sd / 2, sd / 2, h)]
    wires, fi = loop_wires(pts, radius_of(p["conductor"]), 1 / 8, "Loop", wl(mhz) / 60)
    return Built(wires, [Source(fi, 0.5)], cut=[Cut("Loop wire, total", P), Cut("Each side (square)", sd, 4)])


sky_loop = Template(
    "sky-loop", "Horizontal sky loop", "Loops",
    "A big horizontal loop around the yard: quiet on receive, strong for NVIS, multiband with a tuner.", 3.75,
    lambda p: [Param("perimeter", "Perimeter", "length", 2, 600), height_param(), conductor_param()],
    lambda mhz: {"perimeter": wl(mhz) * 1.03, "height": 10, "conductor": "awg14"},
    _sky_build, {"param": "perimeter", "mode": "reactance", "label": "perimeter"}, feed="loop", device="balun-4-1",
    multiband=True)


def _ml_defaults(mhz):
    D = min(max(wl(mhz) / 22, 0.6), 2.5)
    R, a = D / 2, 0.011
    L = 4e-7 * math.pi * R * (math.log(8 * R / a) - 2)
    w = 2 * math.pi * mhz * 1e6
    return {"diameter": D, "cap": max(2, 1 / (w * w * L) * 1e12 * 0.92), "coupling": 20, "height": 1.5,
            "conductor": "tube22", "sides": 16}


def _ml_build(p, mhz):
    D, h, k = n(p, "diameter"), n(p, "height"), round(n(p, "sides"))
    R, r = D / 2, radius_of(p["conductor"])
    zc = h + R
    pts = []
    for i in range(k):
        t = -math.pi / 2 + 2 * math.pi * i / k + math.pi / k
        pts.append(V(0, R * math.cos(t), zc + R * math.sin(t)))
    main, mfi = loop_wires(pts, r, 0.5 - 1 / (2 * k), "Main loop", math.pi * D / k / 3)
    cd = D * n(p, "coupling") / 100
    cr = cd / 2
    cz = h + 0.03 + r + cr
    cpts = []
    for i in range(8):
        t = -math.pi / 2 + 2 * math.pi * i / 8 + math.pi / 8
        cpts.append(V(0.002, cr * math.cos(t), cz + cr * math.sin(t)))
    cpl, cfi = loop_wires(cpts, 0.002, 15 / 16, "Coupling loop", math.pi * cd / 8 / 3)
    return Built(main + cpl, [Source(len(main) + cfi, 0.5)],
                 [Load(mfi, 0.5, "series", 0, 0, n(p, "cap") * 1e-12, "Tuning capacitor")],
                 cut=[Cut("Main loop conductor (circumference)", math.pi * D),
                      Cut("Coupling loop (circumference)", math.pi * cd),
                      Cut(f"Tuning capacitor: about {n(p, 'cap'):.1f} pF (vacuum variable or butterfly)")],
                 notes=["Copper loss dominates a small loop: use the fattest tubing you can and solder "
                        "every joint. The capacitor sees thousands of volts at 100 W."])


mag_loop = Template(
    "mag-loop", "Small magnetic loop", "Loops",
    "A small high-Q loop tuned by a capacitor: fits on a balcony. Very narrow bandwidth, very high capacitor voltage.",
    14.175,
    lambda p: [Param("diameter", "Main loop diameter", "length", 0.2, 6), Param("cap", "Tuning capacitor", "pf", 1, 2000),
               Param("coupling", "Coupling loop size", "percent", 8, 35, help="About 1/5 of the main loop."),
               height_param("Loop bottom height"),
               Param("conductor", "Main loop conductor", "select",
                     options=[(v, lab) for v, lab, _ in CONDUCTORS if v.startswith("tube")]),
               Param("sides", "Polygon sides", "count", 8, 24, advanced=True)],
    _ml_defaults, _ml_build, {"param": "cap", "mode": "magloop", "label": "capacitor and coupling loop"},
    feed="mag-loop", device="none", span=0.004)


TEMPLATES = [dipole, inverted_v, ocfd, efhw, fan, trap, doublet, ground_vertical, ground_plane, five_eighths,
             loaded_vertical, jpole, yagi, moxon, quad, delta, sky_loop, mag_loop]


def by_id(tid: str) -> Template | None:
    return next((t for t in TEMPLATES if t.id == tid), None)


def adjust(t: Template, prev: dict, nxt: dict, mhz: float) -> dict:
    """Rebuild dependent settings: Yagi element rows when the count changes, doublet presets."""
    if t.id == "yagi" and round(float(prev.get("count", 3))) != round(float(nxt.get("count", 3))):
        c = max(2, min(10, round(float(nxt["count"]))))
        return {**yagi_defaults(mhz, c, str(nxt["conductor"])), "height": nxt["height"]}
    if t.id == "doublet" and prev.get("preset") != nxt.get("preset") and nxt.get("preset") in DOUBLET_PRESETS:
        ln, ll = DOUBLET_PRESETS[nxt["preset"]]
        return {**nxt, "length": ln, "lineLength": ll, "lineZ": "450"}
    if t.id == "doublet" and (prev.get("length") != nxt.get("length") or prev.get("lineLength") != nxt.get("lineLength")):
        return {**nxt, "preset": "custom"}
    return nxt
