"""A rough, offline maximum usable frequency estimate for long hops (3000 km)
from your location, the time and the solar flux. Good enough to say which
HF bands are likely open; it is not a propagation forecast."""
from __future__ import annotations

import math

from . import geo

HF_BANDS = [("160 m", 1.9), ("80 m", 3.7), ("60 m", 5.36), ("40 m", 7.15), ("30 m", 10.12), ("20 m", 14.2),
            ("17 m", 18.1), ("15 m", 21.2), ("12 m", 24.94), ("10 m", 28.5), ("6 m", 50.2)]


def ssn_from_sfi(sfi: float) -> float:
    """Sunspot number from the 10.7 cm flux (SFI = 63.7 + 0.728 R + 0.00089 R^2)."""
    a, b, c = 0.00089, 0.728, 63.7 - sfi
    disc = b * b - 4 * a * c
    return max(0.0, (-b + math.sqrt(max(0.0, disc))) / (2 * a))


def fof2(lat: float, lon: float, t: float, sfi: float) -> float:
    """Critical frequency of the F2 layer, MHz (a smooth empirical shape:
    higher with more sunspots and a higher sun, lower at night and near the poles)."""
    r = ssn_from_sfi(sfi)
    noon = 4.0 + 0.055 * r
    night = 2.2 + 0.018 * r
    el, _ = geo.sun_position(lat, lon, t)
    day = max(0.0, math.sin(math.radians(max(-6.0, el) + 6)) / math.sin(math.radians(96))) ** 0.6
    f = night + (noon - night) * day
    return f * (1 - 0.25 * (abs(lat) / 90) ** 2)


def muf(lat: float, lon: float, t: float, sfi: float) -> float:
    """MUF(3000) estimate at the midpoint of a hop that starts here, MHz: the
    path's midpoint is about 1500 km away, so take the better of the
    ionosphere here and 13 degrees to either side."""
    best = 0.0
    for dlon in (-13.0, 0.0, 13.0):
        best = max(best, fof2(lat, (lon + dlon + 180) % 360 - 180, t, sfi))
    return 3.3 * best


def band_outlook(m: float) -> list:
    """[(band, MHz, word)] for the HF bands against a MUF."""
    out = []
    for name, f in HF_BANDS:
        if f > m:
            word = "closed"
        elif f > 0.85 * m:
            word = "marginal"
        elif f < 0.3 * m and f < 8:
            word = "short hops"
        else:
            word = "open"
        out.append((name, f, word))
    return out


def day_curve(lat: float, lon: float, start: float, sfi: float, hours: int = 24, step_min: int = 30) -> list:
    return [(start + i * step_min * 60, muf(lat, lon, start + i * step_min * 60, sfi))
            for i in range(hours * 60 // step_min + 1)]
