"""The online parts, each cached in ~/.config/askelmer-ham-tools/ so the
last download still works offline: solar data (N0NBH, hamqsl.com), POTA
spots, POTA parks and SOTA summits near you, and satellite orbits (AMSAT,
with CelesTrak as a backup). Plain urllib, short timeouts."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import time
import urllib.request

from . import __version__, config_dir

UA = "AskElmer-HamTools/" + __version__ + " (+https://askelmer.com)"
SOLAR_URL = "https://www.hamqsl.com/solarxml.php"
POTA_SPOTS_URL = "https://api.pota.app/spot/activator"
POTA_PARKS_URL = "https://pota.app/all_parks_ext.csv"
SOTA_SUMMITS_URL = "https://storage.sota.org.uk/summitslist.csv"
TLE_URLS = ["https://www.amsat.org/tle/current/nasabare.txt",
            "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle"]


def cache_dir() -> str:
    return config_dir()


def _path(name: str) -> str:
    return os.path.join(cache_dir(), name)


def _save(name: str, data) -> None:
    os.makedirs(cache_dir(), exist_ok=True)
    tmp = _path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        if isinstance(data, str):
            fh.write(data)
        else:
            json.dump(data, fh)
    os.replace(tmp, _path(name))


def _load(name: str):
    try:
        with open(_path(name), encoding="utf-8") as fh:
            return json.load(fh) if name.endswith(".json") else fh.read()
    except (OSError, ValueError):
        return None


def age_of(name: str) -> float | None:
    try:
        return time.time() - os.path.getmtime(_path(name))
    except OSError:
        return None


def get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def stream(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


# ---- solar data ------------------------------------------------------------------------------

def parse_solar(xml: str) -> dict:
    def tag(t):
        m = re.search(rf"<{t}>\s*([^<]*?)\s*</{t}>", xml)
        return m.group(1) if m else ""
    d = {k: tag(k) for k in ("updated", "solarflux", "aindex", "kindex", "xray", "sunspots", "geomagfield",
                             "signalnoise", "solarwind", "muf")}
    d["bands"] = {}
    for name, when, cond in re.findall(r'<band name="([^"]+)" time="(day|night)">([^<]*)</band>', xml):
        d["bands"].setdefault(name, {})[when] = cond.strip()
    d["vhf"] = [(n, loc, c.strip()) for n, loc, c in
                re.findall(r'<phenomenon name="([^"]+)" location="([^"]+)">([^<]*)</phenomenon>', xml)]
    return d


def solar(refresh: bool = False) -> dict | None:
    """Solar data: fresh from hamqsl.com when refresh, else the cached copy."""
    if refresh:
        xml = get(SOLAR_URL).decode("utf-8", "replace")
        d = parse_solar(xml)
        if not d.get("solarflux"):
            raise OSError("hamqsl.com sent no solar data. Try again later.")
        d["fetched"] = time.time()
        _save("solar.json", d)
        return d
    return _load("solar.json")


# ---- POTA spots ------------------------------------------------------------------------------

def pota_spots(refresh: bool = True) -> list:
    if refresh:
        data = json.loads(get(POTA_SPOTS_URL).decode("utf-8", "replace"))
        spots = [{k: s.get(k) for k in ("activator", "frequency", "mode", "reference", "name", "locationDesc",
                                         "grid6", "latitude", "longitude", "spotTime", "comments", "count")}
                 for s in data if not s.get("invalid")]
        _save("pota_spots.json", {"fetched": time.time(), "spots": spots})
        return spots
    d = _load("pota_spots.json")
    return d["spots"] if d else []


# ---- parks and summits near you ----------------------------------------------------------------

RADIUS_KM = 250


def download_parks(lat: float, lon: float, progress=None) -> int:
    """POTA parks within RADIUS_KM, from the full list (streamed, not kept)."""
    keep = []
    with stream(POTA_PARKS_URL, 60) as r:
        text = io.TextIOWrapper(r, encoding="utf-8", errors="replace")
        rows = csv.reader(text)
        head = next(rows)
        ix = {k: head.index(k) for k in ("reference", "name", "active", "locationDesc", "latitude", "longitude")}
        for n, row in enumerate(rows):
            try:
                la, lo = float(row[ix["latitude"]]), float(row[ix["longitude"]])
            except (ValueError, IndexError):
                continue
            if row[ix["active"]] != "1" or abs(la - lat) > 3 or _km(lat, lon, la, lo) > RADIUS_KM:
                continue
            keep.append([row[ix["reference"]], row[ix["name"]], row[ix["locationDesc"]], la, lo])
            if progress and n % 5000 == 0:
                progress(n)
    _save("parks.json", {"fetched": time.time(), "lat": lat, "lon": lon, "items": keep})
    return len(keep)


def download_summits(lat: float, lon: float, progress=None) -> int:
    keep = []
    today = time.strftime("%Y%m%d")
    with stream(SOTA_SUMMITS_URL, 90) as r:
        text = io.TextIOWrapper(r, encoding="utf-8", errors="replace")
        text.readline()                       # "SOTA Summits List (Date=...)"
        rows = csv.reader(text)
        head = next(rows)
        ix = {k: head.index(k) for k in ("SummitCode", "SummitName", "AltM", "AltFt", "Longitude", "Latitude",
                                         "Points", "ValidTo", "ActivationCount")}
        for n, row in enumerate(rows):
            try:
                la, lo = float(row[ix["Latitude"]]), float(row[ix["Longitude"]])
            except (ValueError, IndexError):
                continue
            if abs(la - lat) > 3 or _km(lat, lon, la, lo) > RADIUS_KM:
                continue
            vt = row[ix["ValidTo"]]
            if len(vt) == 10 and vt[6:] + vt[3:5] + vt[:2] < today:
                continue                       # retired summit
            keep.append([row[ix["SummitCode"]], row[ix["SummitName"]], row[ix["AltFt"]], la, lo,
                         row[ix["Points"]], row[ix["ActivationCount"]]])
            if progress and n % 10000 == 0:
                progress(n)
    _save("summits.json", {"fetched": time.time(), "lat": lat, "lon": lon, "items": keep})
    return len(keep)


def nearby(kind: str, lat: float, lon: float) -> tuple[list, dict | None]:
    """Cached parks or summits sorted by distance: ([(km, item)], meta)."""
    d = _load(f"{kind}.json")
    if not d:
        return [], None
    out = sorted(((_km(lat, lon, it[3], it[4]), it) for it in d["items"]), key=lambda x: x[0])
    return out, d


# ---- satellite orbits --------------------------------------------------------------------------

def parse_tles(text: str) -> dict:
    """{catalog number: (name, line1, line2)}."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out = {}
    for i in range(len(lines) - 2):
        a, b, c = lines[i], lines[i + 1], lines[i + 2]
        if b.startswith("1 ") and c.startswith("2 ") and not a.startswith(("1 ", "2 ")):
            try:
                out[int(b[2:7])] = (a.strip(), b, c)
            except ValueError:
                pass
    return out


def update_tles() -> int:
    last = None
    for url in TLE_URLS:
        try:
            text = get(url, 20).decode("ascii", "replace")
            tles = parse_tles(text)
            if len(tles) > 10:
                _save("tle.txt", text)
                return len(tles)
        except OSError as e:
            last = e
    raise OSError(f"Couldn't download orbits ({last}).")


def tles() -> dict:
    t = _load("tle.txt")
    if t:
        return parse_tles(t)
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tle.txt")
    try:
        return parse_tles(open(here, encoding="ascii", errors="replace").read())
    except OSError:
        return {}


def tle_age_days() -> float | None:
    """Age of the newest element set we have, from its epoch."""
    best = None
    for _name, l1, _l2 in tles().values():
        try:
            yy, doy = int(l1[18:20]), float(l1[20:32])
        except ValueError:
            continue
        year = 2000 + yy if yy < 57 else 1900 + yy
        import calendar
        epoch = calendar.timegm((year, 1, 1, 0, 0, 0, 0, 0, 0)) + (doy - 1) * 86400
        best = epoch if best is None else max(best, epoch)
    return None if best is None else (time.time() - best) / 86400
