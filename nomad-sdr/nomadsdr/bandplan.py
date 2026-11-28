"""US amateur band plan with license privileges, repeater offsets and handy
non-ham channels (weather, air, marine, satellites).

Privileges follow FCC Part 97.301/97.305 (US). Sub-bands follow the ARRL band
plan; repeater offsets are the common US ones and local coordinators can
differ, so the screens say "usual offset".

Classes: "T" Technician, "G" General, "E" Amateur Extra.  For each segment
`who` lists the classes that may transmit there.
"""
from __future__ import annotations

from dataclasses import dataclass

CLASSES = ["None", "Technician", "General", "Extra"]
SHORT = {"Technician": "T", "General": "G", "Extra": "E"}


@dataclass
class Seg:
    lo: float          # MHz
    hi: float
    use: str           # what it is used for
    who: str = "TGE"   # classes that may transmit
    mode: str = "NFM"  # mode to listen with
    call: float = 0.0  # a frequency worth tuning to (calling / centre), MHz


@dataclass
class Band:
    name: str
    lo: float
    hi: float
    segs: list
    hf: bool = False   # needs the HF input (V3 direct sampling / V4)
    note: str = ""


ALL = "TGE"
GE = "GE"
E = "E"

BANDS = [
    Band("160 m", 1.8, 2.0, [Seg(1.8, 2.0, "CW, data, phone", GE, "LSB", 1.910)], True),
    Band("80 m", 3.5, 4.0, [
        Seg(3.5, 3.525, "CW / data (Extra)", E, "CW", 3.510),
        Seg(3.525, 3.6, "CW / data (Tech CW)", ALL, "CW", 3.560),
        Seg(3.6, 3.7, "Phone (Extra)", E, "LSB", 3.650),
        Seg(3.7, 3.8, "Phone (Extra, Advanced)", E, "LSB", 3.750),
        Seg(3.8, 4.0, "Phone", GE, "LSB", 3.885)], True),
    Band("60 m", 5.3305, 5.4065, [
        Seg(5.3305, 5.3335, "Channel 1 (USB)", GE, "USB", 5.3305),
        Seg(5.3465, 5.3495, "Channel 2 (USB)", GE, "USB", 5.3465),
        Seg(5.357, 5.360, "Channel 3 (USB, FT8)", GE, "USB", 5.357),
        Seg(5.3715, 5.3745, "Channel 4 (USB)", GE, "USB", 5.3715),
        Seg(5.4035, 5.4065, "Channel 5 (USB)", GE, "USB", 5.4035)], True, "Channels only, 100 W ERP"),
    Band("40 m", 7.0, 7.3, [
        Seg(7.0, 7.025, "CW / data (Extra)", E, "CW", 7.010),
        Seg(7.025, 7.125, "CW / data (Tech CW)", ALL, "CW", 7.030),
        Seg(7.074, 7.077, "FT8", GE, "USB", 7.074),
        Seg(7.125, 7.175, "Phone (Extra, Advanced)", E, "LSB", 7.150),
        Seg(7.175, 7.3, "Phone", GE, "LSB", 7.200)], True),
    Band("30 m", 10.1, 10.15, [Seg(10.1, 10.15, "CW / data only", GE, "CW", 10.116),
                               Seg(10.136, 10.139, "FT8", GE, "USB", 10.136)], True, "200 W"),
    Band("20 m", 14.0, 14.35, [
        Seg(14.0, 14.025, "CW / data (Extra)", E, "CW", 14.010),
        Seg(14.025, 14.15, "CW / data", GE, "CW", 14.060),
        Seg(14.074, 14.077, "FT8", GE, "USB", 14.074),
        Seg(14.15, 14.225, "Phone (Extra)", E, "USB", 14.200),
        Seg(14.225, 14.35, "Phone", GE, "USB", 14.300)], True),
    Band("17 m", 18.068, 18.168, [Seg(18.068, 18.11, "CW / data", GE, "CW", 18.086),
                                  Seg(18.11, 18.168, "Phone", GE, "USB", 18.130)], True),
    Band("15 m", 21.0, 21.45, [
        Seg(21.0, 21.025, "CW / data (Extra)", E, "CW", 21.010),
        Seg(21.025, 21.2, "CW / data (Tech CW)", ALL, "CW", 21.060),
        Seg(21.2, 21.275, "Phone (Extra)", E, "USB", 21.250),
        Seg(21.275, 21.45, "Phone", GE, "USB", 21.300)], True),
    Band("12 m", 24.89, 24.99, [Seg(24.89, 24.93, "CW / data", GE, "CW", 24.906),
                                Seg(24.93, 24.99, "Phone", GE, "USB", 24.950)], True),
    Band("10 m", 28.0, 29.7, [
        Seg(28.0, 28.3, "CW / data (Tech too)", ALL, "CW", 28.060),
        Seg(28.3, 28.5, "SSB phone (Tech 200 W)", ALL, "USB", 28.400),
        Seg(28.5, 29.0, "SSB phone", GE, "USB", 28.600),
        Seg(29.0, 29.2, "AM", GE, "AM", 29.000),
        Seg(29.3, 29.51, "Satellite downlink", GE, "USB", 29.400),
        Seg(29.52, 29.59, "FM repeater inputs", GE, "NFM", 29.560),
        Seg(29.6, 29.61, "FM simplex calling", GE, "NFM", 29.600),
        Seg(29.62, 29.69, "FM repeater outputs", GE, "NFM", 29.640)], True),
    Band("6 m", 50.0, 54.0, [
        Seg(50.0, 50.1, "CW, beacons", ALL, "CW", 50.090),
        Seg(50.1, 50.3, "SSB, CW (50.125 calling)", ALL, "USB", 50.125),
        Seg(50.313, 50.316, "FT8", ALL, "USB", 50.313),
        Seg(50.3, 51.0, "All modes, digital", ALL, "USB", 50.400),
        Seg(51.0, 52.0, "FM simplex, repeaters", ALL, "NFM", 51.500),
        Seg(52.0, 54.0, "FM repeaters, simplex (52.525)", ALL, "NFM", 52.525)]),
    Band("2 m", 144.0, 148.0, [
        Seg(144.0, 144.1, "CW, EME", ALL, "CW", 144.050),
        Seg(144.1, 144.275, "SSB weak signal (144.200 calling)", ALL, "USB", 144.200),
        Seg(144.275, 144.3, "Beacons", ALL, "CW", 144.280),
        Seg(144.3, 144.5, "Satellites, APRS 144.390", ALL, "NFM", 144.390),
        Seg(144.5, 144.6, "Linear translator inputs", ALL, "USB", 144.550),
        Seg(144.6, 144.9, "FM repeater inputs", ALL, "NFM", 144.700),
        Seg(144.9, 145.1, "Weak signal, packet", ALL, "NFM", 145.010),
        Seg(145.1, 145.2, "Linear translator outputs", ALL, "USB", 145.150),
        Seg(145.2, 145.5, "FM repeater outputs", ALL, "NFM", 145.290),
        Seg(145.5, 145.8, "Misc and experimental", ALL, "NFM", 145.550),
        Seg(145.8, 146.0, "Satellites (ISS 145.800)", ALL, "NFM", 145.800),
        Seg(146.0, 146.4, "FM repeater inputs", ALL, "NFM", 146.010),
        Seg(146.4, 146.6, "FM simplex (146.520 calling)", ALL, "NFM", 146.520),
        Seg(146.6, 147.4, "FM repeater outputs", ALL, "NFM", 146.940),
        Seg(147.4, 147.6, "FM simplex", ALL, "NFM", 147.420),
        Seg(147.6, 148.0, "FM repeater inputs", ALL, "NFM", 147.600)]),
    Band("1.25 m", 219.0, 225.0, [
        Seg(219.0, 220.0, "Fixed digital links", ALL, "NFM", 219.5),
        Seg(222.0, 222.15, "Weak signal CW/SSB", ALL, "USB", 222.100),
        Seg(222.15, 222.25, "Local option, FM", ALL, "NFM", 222.200),
        Seg(222.25, 223.38, "FM repeater inputs", ALL, "NFM", 222.300),
        Seg(223.4, 223.52, "FM simplex (223.500 calling)", ALL, "NFM", 223.500),
        Seg(223.52, 223.64, "Digital, packet", ALL, "NFM", 223.600),
        Seg(223.85, 224.98, "FM repeater outputs", ALL, "NFM", 223.940)]),
    Band("70 cm", 420.0, 450.0, [
        Seg(420.0, 432.0, "ATV, links", ALL, "NFM", 426.250),
        Seg(432.0, 432.1, "EME, weak CW", ALL, "CW", 432.050),
        Seg(432.1, 433.0, "SSB weak signal (432.100)", ALL, "USB", 432.100),
        Seg(433.0, 435.0, "Aux, repeater links", ALL, "NFM", 434.000),
        Seg(435.0, 438.0, "Satellites (ISS 437.800)", ALL, "NFM", 437.800),
        Seg(438.0, 442.0, "ATV, repeater links", ALL, "NFM", 440.000),
        Seg(442.0, 445.0, "FM repeaters (outputs)", ALL, "NFM", 442.000),
        Seg(445.0, 447.0, "FM simplex (446.000 calling)", ALL, "NFM", 446.000),
        Seg(447.0, 450.0, "FM repeaters (outputs)", ALL, "NFM", 447.000)]),
    Band("33 cm", 902.0, 928.0, [
        Seg(902.0, 903.0, "Weak signal (902.100)", ALL, "USB", 902.100),
        Seg(903.0, 906.0, "Digital", ALL, "NFM", 904.0),
        Seg(906.0, 909.0, "FM repeater outputs", ALL, "NFM", 906.500),
        Seg(909.0, 915.0, "ATV, digital", ALL, "NFM", 910.0),
        Seg(915.0, 918.0, "Digital", ALL, "NFM", 916.0),
        Seg(918.0, 921.0, "FM repeater inputs", ALL, "NFM", 918.500),
        Seg(921.0, 927.0, "ATV, digital", ALL, "NFM", 925.0),
        Seg(927.0, 928.0, "FM simplex, links", ALL, "NFM", 927.500)]),
    Band("23 cm", 1240.0, 1300.0, [
        Seg(1240.0, 1270.0, "ATV, digital, satellite up", ALL, "NFM", 1250.0),
        Seg(1270.0, 1276.0, "FM repeater inputs", ALL, "NFM", 1272.0),
        Seg(1282.0, 1288.0, "FM repeater outputs", ALL, "NFM", 1284.0),
        Seg(1294.0, 1295.0, "FM simplex (1294.500)", ALL, "NFM", 1294.500),
        Seg(1296.0, 1297.0, "Weak signal (1296.100)", ALL, "USB", 1296.100)]),
]

# Other channels worth a listen (not ham, receive only).
PRESETS = [
    ("APRS (North America)", 144.390, "NFM"),
    ("2 m simplex calling", 146.520, "NFM"),
    ("70 cm simplex calling", 446.000, "NFM"),
    ("ISS voice / APRS", 145.800, "NFM"),
    ("ISS APRS digipeater", 145.825, "NFM"),
    ("NOAA Weather 162.550", 162.550, "NFM"),
    ("NOAA Weather 162.400", 162.400, "NFM"),
    ("NOAA Weather 162.425", 162.425, "NFM"),
    ("NOAA Weather 162.450", 162.450, "NFM"),
    ("NOAA Weather 162.475", 162.475, "NFM"),
    ("NOAA Weather 162.500", 162.500, "NFM"),
    ("NOAA Weather 162.525", 162.525, "NFM"),
    ("Marine ch 16 (distress)", 156.800, "NFM"),
    ("Air guard 121.5", 121.500, "AM"),
    ("MURS 1", 151.820, "NFM"),
    ("FRS / GMRS 1", 462.5625, "NFM"),
    ("FM broadcast 101.1", 101.100, "WFM"),
    ("WWV 10 MHz time (HF)", 10.000, "AM"),
    ("WWV 15 MHz time (HF)", 15.000, "AM"),
]


def find(mhz: float) -> tuple[Band | None, Seg | None]:
    """The band and the most specific segment for a frequency."""
    for b in BANDS:
        if b.lo - 1e-9 <= mhz <= b.hi + 1e-9:
            best = None
            for s in b.segs:
                if s.lo - 1e-9 <= mhz < s.hi + 1e-9:
                    if best is None or (s.hi - s.lo) < (best.hi - best.lo):
                        best = s
            return b, best
    return None, None


def can_tx(mhz: float, license_class: str) -> bool | None:
    """True / False for a licensed class, None when no class is set."""
    c = SHORT.get(license_class)
    if not c:
        return None
    b, s = find(mhz)
    if not b or not s:
        return False
    return c in s.who


def who_text(who: str) -> str:
    names = {"T": "Tech", "G": "General", "E": "Extra"}
    if who == ALL:
        return "All classes"
    if who == GE:
        return "General, Extra"
    return " ".join(names[c] for c in who) + " only"


def repeater_offset(mhz: float) -> float | None:
    """The usual US repeater offset (MHz) when mhz is a repeater output."""
    f = round(mhz, 4)
    if 145.1 <= f < 145.5:
        return -0.6
    if 146.6 <= f < 147.0:
        return -0.6
    if 147.0 <= f < 147.4:
        return +0.6
    if 223.85 <= f < 225.0:
        return -1.6
    if 442.0 <= f < 445.0:
        return +5.0
    if 447.0 <= f < 450.0:
        return -5.0
    if 29.62 <= f < 29.7:
        return -0.1
    if 51.62 <= f < 52.0 or 52.5 <= f < 54.0:
        return -1.0 if f >= 52.5 else -0.5
    if 906.0 <= f < 909.0:
        return +12.0
    if 1282.0 <= f < 1288.0:
        return -12.0
    return None


def default_mode(mhz: float) -> str:
    b, s = find(mhz)
    if s:
        return s.mode
    if 88.0 <= mhz < 108.0:
        return "WFM"
    if 108.0 <= mhz < 137.0:
        return "AM"
    if mhz < 30.0:
        return "AM"
    return "NFM"


def label(mhz: float) -> str:
    """Short text for the main screen: band and use, or a known service."""
    b, s = find(mhz)
    if b:
        return f"{b.name}  {s.use}" if s else f"{b.name}  (gap in band plan)"
    if 88.0 <= mhz < 108.0:
        return "FM broadcast"
    if 108.0 <= mhz < 118.0:
        return "Air navigation"
    if 118.0 <= mhz < 137.0:
        return "Airband (AM)"
    if 156.0 <= mhz < 162.1:
        return "Marine VHF"
    if 162.39 <= mhz <= 162.56:
        return "NOAA Weather Radio"
    if 151.8 <= mhz <= 154.6:
        return "MURS / business"
    if 462.5 <= mhz <= 467.8:
        return "FRS / GMRS"
    if 1090.0 - 1 <= mhz <= 1090.0 + 1:
        return "ADS-B aircraft"
    for wwv in (2.5, 5.0, 10.0, 15.0, 20.0):
        if abs(mhz - wwv) < 0.005:
            return "WWV / WWVH time signal (AM)"
    if 26.965 <= mhz <= 27.405:
        return "CB radio"
    for lo, hi, name in SW_BANDS:
        if lo <= mhz <= hi:
            return f"Shortwave broadcast {name}"
    if 0.53 <= mhz <= 1.71:
        return "AM broadcast"
    return ""


SW_BANDS = [(3.9, 4.0, "75 m"), (4.75, 5.06, "60 m"), (5.9, 6.2, "49 m"), (7.3, 7.45, "41 m"),
            (9.4, 9.9, "31 m"), (11.6, 12.1, "25 m"), (13.57, 13.87, "22 m"), (15.1, 15.8, "19 m"),
            (17.48, 17.9, "16 m"), (18.9, 19.02, "15 m"), (21.45, 21.85, "13 m"), (25.67, 26.1, "11 m")]
