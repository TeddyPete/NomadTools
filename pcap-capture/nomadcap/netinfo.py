"""Interfaces, link state and addresses, straight from /sys and `ip`."""
from __future__ import annotations

import json
import os
import subprocess


def names() -> list[str]:
    """Capture-able interfaces, wired first."""
    try:
        all_ = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return ["eth0"]
    skip = ("lo", "docker", "veth", "br-", "virbr", "tun", "tap", "wg", "p2p")
    out = [n for n in all_ if not n.startswith(skip)]
    out.sort(key=lambda n: (0 if n.startswith(("eth", "en", "usb")) else 1, n))
    return out or ["eth0"]


def wired() -> str:
    for n in names():
        if n.startswith(("eth", "en")):
            return n
    return "eth0"


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def link(iface: str) -> dict:
    """{'exists', 'up' (carrier), 'speed' Mb/s or 0, 'duplex', 'wifi'}."""
    base = f"/sys/class/net/{iface}"
    if not os.path.isdir(base):
        return {"exists": False, "up": False, "speed": 0, "duplex": "", "wifi": False}
    carrier = _read(base + "/carrier") == "1"
    try:
        speed = int(_read(base + "/speed") or 0)
    except ValueError:
        speed = 0
    return {"exists": True, "up": carrier, "speed": max(speed, 0) if carrier else 0,
            "duplex": _read(base + "/duplex") if carrier else "",
            "wifi": os.path.isdir(base + "/wireless") or os.path.isdir(base + "/phy80211")}


def link_text(iface: str) -> str:
    l = link(iface)
    if not l["exists"]:
        return "missing"
    if not l["up"]:
        return "no link"
    if l["wifi"]:
        return "Wi-Fi"
    if l["speed"] >= 1000:
        return f"{l['speed'] // 1000}G"
    return f"{l['speed']}M" if l["speed"] else "up"


def addresses() -> dict[str, str]:
    """iface -> first IPv4 address."""
    try:
        r = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=5)
        data = json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for d in data:
        for a in d.get("addr_info", []):
            if a.get("family") == "inet" and d.get("ifname") != "lo":
                out.setdefault(d["ifname"], a["local"])
    return out
