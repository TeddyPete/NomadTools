"""MAC address -> manufacturer, using arp-scan's IEEE list when installed,
plus a built-in list of AV makers so brand detection works without it."""
from __future__ import annotations

import os

FILES = ["/usr/share/arp-scan/ieee-oui.txt", "/usr/share/ieee-data/oui.txt",
         "/usr/share/nmap/nmap-mac-prefixes"]

AV = {
    "00107F": "Crestron Electronics", "0005A6": "Extron Electronics", "00905E": "Biamp Systems",
    "000EDD": "Shure", "006074": "QSC", "001DC1": "Audinate", "0004F2": "Polycom",
    "00408C": "Axis Communications",
}
_db: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _db
    if _db is not None:
        return _db
    db: dict[str, str] = {}
    for path in FILES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line or line[0] in "#\n":
                        continue
                    if path.endswith("oui.txt") and "(hex)" in line:
                        p, _, v = line.partition("(hex)")
                        db[p.strip().replace("-", "").upper()] = v.strip()
                    else:
                        parts = line.rstrip("\n").split(None, 1) if "\t" not in line else line.rstrip("\n").split("\t", 1)
                        if len(parts) == 2 and all(c in "0123456789ABCDEFabcdef" for c in parts[0]):
                            db[parts[0].upper()] = parts[1].strip()
        except OSError:
            continue
        if db:
            break
    for k, v in AV.items():
        db.setdefault(k, v)
    _db = db
    return db


def vendor(mac: str) -> str:
    if not mac:
        return ""
    h = mac.replace(":", "").replace("-", "").replace(".", "").upper()
    if len(h) < 6:
        return ""
    if int(h[1], 16) & 2:
        return "(random/private MAC)"
    db = _load()
    for n in (9, 7, 6):
        v = db.get(h[:n])
        if v:
            return v
    return ""


BRANDS = [("Crestron", ("crestron",)), ("Extron", ("extron",)), ("Biamp", ("biamp",)),
          ("Shure", ("shure",)), ("Q-SYS", ("qsc",)), ("Netgear", ("netgear",)),
          ("Audinate", ("audinate",)), ("Yamaha", ("yamaha",)), ("Sony", ("sony",)),
          ("Barco", ("barco",)), ("Poly", ("polycom",))]


def brand(vendor_name: str) -> str:
    v = (vendor_name or "").lower()
    for b, keys in BRANDS:
        if any(k in v for k in keys):
            return b
    return ""
