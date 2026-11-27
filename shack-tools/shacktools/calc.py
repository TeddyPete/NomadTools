"""The math behind Ask Elmer Shack Tools (a Python port of the Ask Elmer web
app's shack calculators, app/src/workshop/shack/lib). No UI here."""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass

# ---- numbers --------------------------------------------------------------------

PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}


def parse_number(raw, prefixes=False, negative=False):
    """A typed number, or None when empty. Raises ValueError with a message
    for something that isn't a number. "1,500", "1.5" and "4.7k" work."""
    s = re.sub(r"\s+", "", str(raw or "")).replace("−", "-").replace("–", "-")
    if not s:
        return None
    mult = 1.0
    if prefixes and len(s) > 1 and s[-1] in PREFIX:
        mult, s = PREFIX[s[-1]], s[:-1]
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"-?\d*,\d+", s):
        s = s.replace(",", ".")
    if not re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?", s, re.I):
        raise ValueError("Type a number, like 12 or 4.7k." if prefixes else "Type a number, like 12 or 3.5.")
    v = float(s) * mult
    if not math.isfinite(v):
        raise ValueError("That number is too large.")
    if v < 0 and not negative:
        raise ValueError("Type a number that isn't negative.")
    return v


def fmt(n: float, sig: int = 4) -> str:
    if n is None:
        return ""
    if not math.isfinite(n):
        return "∞" if n > 0 else "-∞"
    if n == 0:
        return "0"
    a = abs(n)
    if a >= 1e15 or a < 1e-6:
        return f"{n:.{sig - 1}e}"
    s = f"{float(f'{n:.{sig}g}'):f}".rstrip("0").rstrip(".")
    if a >= 10000:
        i, _, d = s.partition(".")
        s = f"{int(i):,}" + (f".{d}" if d else "")
    return s


SI = [(9, "G"), (6, "M"), (3, "k"), (0, ""), (-3, "m"), (-6, "µ"), (-9, "n")]


def si(n: float, unit: str, sig: int = 4) -> str:
    if n is None or not math.isfinite(n) or n == 0:
        return f"{fmt(n, sig)} {unit}"
    a = abs(n)
    exp, p = next(((e, p) for e, p in SI if a >= 10 ** e * 0.9995), SI[-1])
    return f"{fmt(n / 10 ** exp, sig)} {p}{unit}"


# ---- bands and privileges -------------------------------------------------------
# US amateur bands, FCC Part 97.301 (Technician segments as in Ask Elmer's
# bands.ts; General and Extra from 97.301(b)-(d) and 97.305). CW is allowed
# everywhere on the amateur bands. "Data" = RTTY and data; "Phone" = phone and image.

CW_DATA, PHONE, ALL = "CW, RTTY, data", "Phone, image, CW", "All modes"
CLASSES = ["Technician", "General", "Extra"]


@dataclass
class Band:
    name: str
    lo: float
    hi: float
    seg: dict          # class -> [(lo, hi, modes)]
    note: str = ""


def _hf(t, g, e, note=""):
    return {"Technician": t, "General": g, "Extra": e}


TECH_HF = "Technicians: 200 W PEP in their HF segments."
BANDS = [
    Band("160 m", 1.8, 2.0, _hf([], [(1.8, 2.0, ALL)], [(1.8, 2.0, ALL)])),
    Band("80 m", 3.5, 4.0, _hf([(3.525, 3.6, "CW only")],
                               [(3.525, 3.6, CW_DATA), (3.8, 4.0, PHONE)],
                               [(3.5, 3.6, CW_DATA), (3.6, 4.0, PHONE)]), TECH_HF),
    Band("60 m", 5.3305, 5.4065, _hf([], [(5.3305, 5.4065, "Channels and segment")],
                                     [(5.3305, 5.4065, "Channels and segment")]),
         "Not a continuous band: a 5.3515-5.3665 MHz segment (9.15 W ERP) plus channels at 5.332, 5.348, "
         "5.373 and 5.405 MHz (100 W ERP). Check the exact frequencies before you transmit."),
    Band("40 m", 7.0, 7.3, _hf([(7.025, 7.125, "CW only")],
                               [(7.025, 7.125, CW_DATA), (7.175, 7.3, PHONE)],
                               [(7.0, 7.125, CW_DATA), (7.125, 7.3, PHONE)]), TECH_HF),
    Band("30 m", 10.1, 10.15, _hf([], [(10.1, 10.15, CW_DATA)], [(10.1, 10.15, CW_DATA)]),
         "200 W PEP maximum for everyone."),
    Band("20 m", 14.0, 14.35, _hf([], [(14.025, 14.15, CW_DATA), (14.225, 14.35, PHONE)],
                                  [(14.0, 14.15, CW_DATA), (14.15, 14.35, PHONE)])),
    Band("17 m", 18.068, 18.168, _hf([], [(18.068, 18.11, CW_DATA), (18.11, 18.168, PHONE)],
                                     [(18.068, 18.11, CW_DATA), (18.11, 18.168, PHONE)])),
    Band("15 m", 21.0, 21.45, _hf([(21.025, 21.2, "CW only")],
                                  [(21.025, 21.2, CW_DATA), (21.275, 21.45, PHONE)],
                                  [(21.0, 21.2, CW_DATA), (21.2, 21.45, PHONE)]), TECH_HF),
    Band("12 m", 24.89, 24.99, _hf([], [(24.89, 24.93, CW_DATA), (24.93, 24.99, PHONE)],
                                   [(24.89, 24.93, CW_DATA), (24.93, 24.99, PHONE)])),
    Band("10 m", 28.0, 29.7, _hf([(28.0, 28.3, CW_DATA), (28.3, 28.5, "CW and SSB phone")],
                                 [(28.0, 28.3, CW_DATA), (28.3, 29.7, PHONE)],
                                 [(28.0, 28.3, CW_DATA), (28.3, 29.7, PHONE)]), TECH_HF),
    Band("6 m", 50, 54, {c: [(50, 54, ALL)] for c in CLASSES}, "50.0-50.1 MHz is CW only, for every class."),
    Band("2 m", 144, 148, {c: [(144, 148, ALL)] for c in CLASSES}, "144.0-144.1 MHz is CW only, for every class."),
    Band("1.25 m", 222, 225, {c: [(222, 225, ALL)] for c in CLASSES}),
    Band("70 cm", 420, 450, {c: [(420, 450, ALL)] for c in CLASSES},
         "420-430 MHz is not available north of Line A, near the Canadian border."),
    Band("33 cm", 902, 928, {c: [(902, 928, ALL)] for c in CLASSES}),
    Band("23 cm", 1240, 1300, {c: [(1240, 1300, ALL)] for c in CLASSES}),
]


def band_for(mhz: float) -> Band | None:
    return next((b for b in BANDS if b.lo <= mhz <= b.hi), None)


def privilege(mhz: float, cls: str):
    """(band, segment or None, text)."""
    b = band_for(mhz)
    if not b:
        return None, None, "Outside the US amateur bands"
    segs = b.seg.get(cls, [])
    if not segs:
        return b, None, f"No {cls} privileges on {b.name}"
    s = next((s for s in segs if s[0] <= mhz <= s[1]), None)
    if s:
        return b, s, f"Yes: {s[2]}"
    return b, None, f"Not in a {cls} segment"


def wavelength_m(mhz: float) -> float:
    return 300.0 / mhz


# ---- Ohm's law ------------------------------------------------------------------

def solve_ohm(E=None, I=None, R=None, P=None):
    """From exactly two of E, I, R, P: (values dict, formulas dict) or None."""
    known = {k: v for k, v in (("E", E), ("I", I), ("R", R), ("P", P)) if v is not None}
    if len(known) != 2 or any(v <= 0 for v in known.values()):
        return None
    pair = "".join(k for k in "EIRP" if k in known)
    E, I, R, P = (known.get(k) for k in "EIRP")
    if pair == "EI":
        v, f = dict(E=E, I=I, R=E / I, P=E * I), dict(R="E / I", P="E × I")
    elif pair == "ER":
        v, f = dict(E=E, R=R, I=E / R, P=E * E / R), dict(I="E / R", P="E² / R")
    elif pair == "EP":
        v, f = dict(E=E, P=P, I=P / E, R=E * E / P), dict(I="P / E", R="E² / P")
    elif pair == "IR":
        v, f = dict(I=I, R=R, E=I * R, P=I * I * R), dict(E="I × R", P="I² × R")
    elif pair == "IP":
        v, f = dict(I=I, P=P, E=P / I, R=P / (I * I)), dict(E="P / I", R="P / I²")
    else:
        v, f = dict(R=R, P=P, E=math.sqrt(P * R), I=math.sqrt(P / R)), dict(E="√(P × R)", I="√(P / R)")
    return v, f


# ---- decibels -------------------------------------------------------------------

def ratio_to_db(r):
    return 10 * math.log10(r)


def db_to_ratio(db):
    return 10 ** (db / 10)


def watts_to_dbm(w):
    return 10 * math.log10(w * 1000)


def dbm_to_watts(dbm):
    return 10 ** (dbm / 10) / 1000


# ---- SWR ------------------------------------------------------------------------

def swr_figures(swr=None, forward=None, reflected=None):
    """dict(swr, gamma, rl, refl_pct, mismatch) from an SWR or from forward
    and reflected watts. None when the input can't be used."""
    if forward is not None and reflected is not None:
        if not (forward > 0 and 0 <= reflected < forward):
            return None
        g = math.sqrt(reflected / forward)
        swr = (1 + g) / (1 - g)
    elif swr is not None:
        if swr < 1:
            return None
        g = (swr - 1) / (swr + 1)
    else:
        return None
    rl = math.inf if g == 0 else -20 * math.log10(g)
    return dict(swr=swr, gamma=g, rl=rl, refl_pct=g * g * 100, mismatch=-10 * math.log10(1 - g * g))


# ---- coax loss ------------------------------------------------------------------
# Typical matched-line attenuation, dB per 100 ft at 10/50/100/400 MHz (Ask
# Elmer coax.ts: Belden 8240, 9258, 8267 and Times LMR-400 figures).

TABLE_MHZ = (10, 50, 100, 400)
CABLES = [
    ("RG-58", (1.1, 2.5, 3.8, 8.4)),
    ("RG-8X", (0.9, 2.1, 3.1, 6.6)),
    ("RG-213", (0.55, 1.3, 1.9, 4.1)),
    ("LMR-400", (0.4, 0.9, 1.2, 2.5)),
]
FT_PER_M = 3.28084


def db_per_100ft(table, mhz):
    xs = [math.log(f) for f in TABLE_MHZ]
    ys = [math.log(v) for v in table]
    x = math.log(mhz)
    i = 0
    while i < len(xs) - 2 and x > xs[i + 1]:
        i += 1
    t = (x - xs[i]) / (xs[i + 1] - xs[i])
    return math.exp(ys[i] + t * (ys[i + 1] - ys[i]))


def coax_loss(cable: str, length_ft: float, mhz: float, watts: float):
    table = dict(CABLES)[cable]
    per = db_per_100ft(table, mhz)
    loss = per * length_ft / 100
    frac = 10 ** (-loss / 10)
    return dict(per100=per, loss=loss, delivered=watts * frac, pct=frac * 100,
                extrapolated=not TABLE_MHZ[0] <= mhz <= TABLE_MHZ[-1])


# ---- grid squares ---------------------------------------------------------------

def to_grid(lat: float, lon: float) -> str:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude runs -90 to 90 and longitude -180 to 180.")
    x = min(lon + 180, 360 - 1e-9)
    y = min(lat + 90, 180 - 1e-9)
    A = ord("A")
    return (chr(A + int(x // 20)) + chr(A + int(y // 10)) + str(int((x % 20) // 2)) + str(int(y % 10))
            + chr(A + int((x % 2) * 12)).lower() + chr(A + int((y % 1) * 24)).lower())


def norm_grid(raw: str) -> str | None:
    s = re.sub(r"\s+", "", raw or "")
    if not re.fullmatch(r"[A-Ra-r]{2}(\d{2}([A-Xa-x]{2})?)?", s):
        return None
    return s[:2].upper() + s[2:4] + s[4:].lower()


def grid_center(raw: str):
    g = norm_grid(raw)
    if not g:
        return None
    A = ord("A")
    west = (ord(g[0]) - A) * 20 - 180
    south = (ord(g[1]) - A) * 10 - 90
    w, h = 20.0, 10.0
    if len(g) >= 4:
        west += int(g[2]) * 2
        south += int(g[3])
        w, h = 2.0, 1.0
    if len(g) == 6:
        west += (ord(g[4].upper()) - A) * (2 / 24)
        south += (ord(g[5].upper()) - A) * (1 / 24)
        w, h = 2 / 24, 1 / 24
    return south + h / 2, west + w / 2


def parse_coord(raw: str, axis: str):
    s = re.sub(r"[°\s]", "", (raw or "").upper()).replace("−", "-")
    if not s:
        return None
    m = re.fullmatch(r"([-+]?)(\d+(?:\.\d+)?|\.\d+)([NSEW]?)", s)
    if not m:
        raise ValueError("Type decimal degrees, like 41.71 or 72.73W.")
    sign, num, hemi = m.groups()
    if hemi and ((axis == "lat" and hemi in "EW") or (axis == "lon" and hemi in "NS")):
        raise ValueError("Latitude uses N or S, longitude E or W.")
    v = float(num)
    if sign == "-" or hemi in ("S", "W"):
        v = -v
    if abs(v) > (90 if axis == "lat" else 180):
        raise ValueError("That coordinate is out of range.")
    return v


def distance_km(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    a = (math.sin((lat2 - lat1) * r / 2) ** 2
         + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2)
    return 2 * 6371.0088 * math.asin(min(1, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    p1, p2, dl = lat1 * r, lat2 * r, (lon2 - lon1) * r
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.atan2(y, x) / r + 360) % 360


POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg):
    return POINTS[round((deg % 360) / 22.5) % 16]


# ---- time -----------------------------------------------------------------------

def offset_label(minutes: int) -> str:
    if minutes == 0:
        return "UTC±0"
    sign = "+" if minutes > 0 else "-"
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def local_offset_minutes(t: float | None = None) -> int:
    t = time.time() if t is None else t
    lt = time.localtime(t)
    return int(lt.tm_gmtoff // 60)


# ---- phonetics and Q signals ------------------------------------------------------

PHONETIC = {
    "A": "Alfa", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo", "F": "Foxtrot", "G": "Golf",
    "H": "Hotel", "I": "India", "J": "Juliett", "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November",
    "O": "Oscar", "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango", "U": "Uniform",
    "V": "Victor", "W": "Whiskey", "X": "X-ray", "Y": "Yankee", "Z": "Zulu", "0": "Zero", "1": "One",
    "2": "Two", "3": "Three", "4": "Four", "5": "Five", "6": "Six", "7": "Seven", "8": "Eight", "9": "Nine",
    "/": "Stroke",
}


def spell(text: str):
    return [(c, PHONETIC.get(c)) for c in re.sub(r"\s+", "", (text or "").upper())]


Q_SIGNALS = [
    ("QRG", "Your exact frequency is ...", "What is my exact frequency?"),
    ("QRL", "This frequency is in use.", "Is this frequency in use?"),
    ("QRM", "I am receiving interference from other stations.", "Are you being interfered with?"),
    ("QRN", "I am troubled by static (atmospheric noise).", "Are you troubled by static?"),
    ("QRO", "Increase power.", "Shall I increase power?"),
    ("QRP", "Decrease power. Also used for low-power operating.", "Shall I decrease power?"),
    ("QRQ", "Send faster.", "Shall I send faster?"),
    ("QRS", "Send more slowly.", "Shall I send more slowly?"),
    ("QRT", "Stop sending. Often means closing down the station.", "Shall I stop sending?"),
    ("QRU", "I have nothing for you.", "Have you anything for me?"),
    ("QRV", "I am ready.", "Are you ready?"),
    ("QRX", "Wait. I will call you again.", "When will you call me again?"),
    ("QRZ", "You are being called by ...", "Who is calling me?"),
    ("QSB", "Your signals are fading.", "Are my signals fading?"),
    ("QSK", "I can hear you between my signals (break-in).", "Can you hear me between your signals?"),
    ("QSL", "I acknowledge receipt. A QSL card confirms a contact.", "Can you acknowledge receipt?"),
    ("QSO", "I can communicate with ... A QSO is a contact.", "Can you communicate with ...?"),
    ("QSP", "I will relay a message to ...", "Will you relay a message to ...?"),
    ("QSY", "Change frequency (I am changing frequency).", "Shall I change frequency?"),
    ("QTH", "My location is ...", "What is your location?"),
]
