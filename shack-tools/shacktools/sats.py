"""Amateur satellite passes: when the easy FM and linear birds come over,
where to point, and the uplink and downlink corrected for Doppler.

Orbits come from the AMSAT/CelesTrak element sets (online.tles()); the SGP4
propagator is python3-sgp4."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

C_KMS = 299792.458
WGS_A, WGS_F = 6378.137, 1 / 298.257223563


@dataclass
class Bird:
    name: str
    norad: int
    kind: str               # "FM" | "Linear" | "APRS"
    up: float | None        # MHz (centre of the passband for linear)
    down: float | None
    tone: str = ""
    note: str = ""


BIRDS = [
    Bird("ISS", 25544, "FM", 145.990, 437.800, "67.0",
         "Cross-band repeater when it's on. ARISS school contacts on 145.800; APRS digipeater on 145.825."),
    Bird("SO-50", 27607, "FM", 145.850, 436.795, "67.0",
         "Send a 2 s burst of 74.4 Hz tone to arm the 10-minute timer, then 67 Hz to talk."),
    Bird("AO-91", 43017, "FM", 435.250, 145.960, "67.0", "Battery is weak: usually only in sunlight."),
    Bird("PO-101", 43678, "FM", 437.500, 145.900, "141.3", "Turned on to a schedule (see @Diwata2PH)."),
    Bird("RS-44", 44909, "Linear", 145.965, 435.640, "",
         "Inverting: 145.935-145.995 up (LSB/CW), 435.610-435.670 down (USB/CW)."),
    Bird("AO-7", 7530, "Linear", 432.150, 145.950, "",
         "Mode B, inverting: 432.125-432.175 up (LSB), 145.975-145.925 down (USB). Sunlight only."),
    Bird("FO-29", 24278, "Linear", 145.950, 435.850, "",
         "Inverting: 145.900-146.000 up (LSB), 435.900-435.800 down (USB). Turned on to a schedule."),
]


def have_sgp4() -> bool:
    try:
        import sgp4.api  # noqa: F401
        return True
    except ImportError:
        return False


def _jd(t: float) -> tuple[float, float]:
    return 2440587.5, t / 86400.0


def _gmst(t: float) -> float:
    jd = t / 86400.0 + 2440587.5
    tu = (jd - 2451545.0) / 36525.0
    g = 67310.54841 + (876600 * 3600 + 8640184.812866) * tu + 0.093104 * tu * tu - 6.2e-6 * tu ** 3
    return math.radians((g % 86400) / 240.0)


def observer_ecef(lat: float, lon: float, alt_m: float = 0.0):
    la, lo = math.radians(lat), math.radians(lon)
    e2 = WGS_F * (2 - WGS_F)
    n = WGS_A / math.sqrt(1 - e2 * math.sin(la) ** 2)
    h = alt_m / 1000.0
    return ((n + h) * math.cos(la) * math.cos(lo), (n + h) * math.cos(la) * math.sin(lo),
            (n * (1 - e2) + h) * math.sin(la))


class Tracker:
    """One satellite seen from one place."""

    def __init__(self, bird: Bird, tle: tuple, lat: float, lon: float, alt_m: float = 0.0):
        from sgp4.api import Satrec
        self.bird = bird
        self.sat = Satrec.twoline2rv(tle[1], tle[2])
        self.lat, self.lon = lat, lon
        self.obs = observer_ecef(lat, lon, alt_m)
        la, lo = math.radians(lat), math.radians(lon)
        self._sl, self._cl, self._so, self._co = math.sin(la), math.cos(la), math.sin(lo), math.cos(lo)

    def ecef(self, t: float):
        jd, fr = _jd(t)
        e, r, _v = self.sat.sgp4(jd, fr)
        if e != 0:
            return None
        g = _gmst(t)
        cg, sg = math.cos(g), math.sin(g)
        return (cg * r[0] + sg * r[1], -sg * r[0] + cg * r[1], r[2])

    def look(self, t: float):
        """(azimuth, elevation, range km) or None."""
        p = self.ecef(t)
        if p is None:
            return None
        rx, ry, rz = p[0] - self.obs[0], p[1] - self.obs[1], p[2] - self.obs[2]
        s = self._sl * self._co * rx + self._sl * self._so * ry - self._cl * rz
        e = -self._so * rx + self._co * ry
        z = self._cl * self._co * rx + self._cl * self._so * ry + self._sl * rz
        rng = math.sqrt(rx * rx + ry * ry + rz * rz)
        el = math.degrees(math.asin(max(-1.0, min(1.0, z / rng))))
        az = math.degrees(math.atan2(e, -s)) % 360
        return az, el, rng

    def range_rate(self, t: float) -> float:
        """km/s, positive when moving away."""
        a, b = self.look(t - 0.5), self.look(t + 0.5)
        return (b[2] - a[2]) if a and b else 0.0

    def elev(self, t: float) -> float:
        lk = self.look(t)
        return lk[1] if lk else -90.0

    def passes(self, start: float, hours: float = 24, min_el: float = 0.0, step: float = 60.0) -> list:
        """[{aos, los, tca, max_el, aos_az, los_az}] that peak above min_el."""
        out = []
        t, end = start, start + hours * 3600
        prev = self.elev(t)
        in_pass = prev > 0
        aos = start if in_pass else None
        while t < end:
            t2 = t + step
            cur = self.elev(t2)
            if not in_pass and cur > 0:
                aos = self._cross(t, t2, rising=True)
                in_pass = True
            elif in_pass and cur <= 0:
                los = self._cross(t, t2, rising=False)
                p = self._describe(aos, los)
                if p["max_el"] >= min_el:
                    out.append(p)
                in_pass = False
            t, prev = t2, cur
        if in_pass and aos is not None:
            p = self._describe(aos, end)
            p["open_end"] = True
            if p["max_el"] >= min_el:
                out.append(p)
        return out

    def _cross(self, a: float, b: float, rising: bool) -> float:
        for _ in range(10):
            m = (a + b) / 2
            if (self.elev(m) > 0) == rising:
                b = m
            else:
                a = m
        return (a + b) / 2

    def _describe(self, aos: float, los: float) -> dict:
        best_t, best_el = aos, -90.0
        n = max(4, int((los - aos) / 15))
        for i in range(n + 1):
            tt = aos + (los - aos) * i / n
            e = self.elev(tt)
            if e > best_el:
                best_t, best_el = tt, e
        a0, a1 = self.look(aos), self.look(los)
        return {"aos": aos, "los": los, "tca": best_t, "max_el": best_el,
                "aos_az": a0[0] if a0 else 0.0, "los_az": a1[0] if a1 else 0.0}

    def track(self, aos: float, los: float, n: int = 40) -> list:
        return [self.look(aos + (los - aos) * i / n) for i in range(n + 1)]

    def doppler(self, t: float) -> tuple[float | None, float | None]:
        """(uplink to transmit on, downlink to listen on), MHz, so the
        satellite hears its nominal uplink."""
        rr = self.range_rate(t)
        b = self.bird
        up = b.up / (1 - rr / C_KMS) if b.up else None     # shift up so it arrives at b.up
        down = b.down * (1 - rr / C_KMS) if b.down else None
        return up, down


def next_passes(lat: float, lon: float, tles: dict, start: float | None = None, hours: float = 24,
                min_el: float = 10.0, birds=None) -> list:
    """All passes of the listed birds, soonest first: [(Bird, pass dict)]."""
    start = start if start is not None else time.time()
    out = []
    for b in birds or BIRDS:
        tle = tles.get(b.norad)
        if not tle:
            continue
        tr = Tracker(b, tle, lat, lon)
        for p in tr.passes(start, hours, min_el):
            out.append((b, p))
    out.sort(key=lambda x: x[1]["aos"])
    return out
