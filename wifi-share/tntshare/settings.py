"""Saved settings (~/.config/tnt-wifi-share/settings.json)."""
from __future__ import annotations

import ipaddress
import json
import os
import secrets
import string

CONF_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "tnt-wifi-share")
CONF = os.path.join(CONF_DIR, "settings.json")


def _default_password() -> str:
    alphabet = "".join(c for c in string.ascii_lowercase + string.digits if c not in "l1o0")
    return "".join(secrets.choice(alphabet) for _ in range(10))


def _default_ssid() -> str:
    try:
        mac = open("/sys/class/net/wlan0/address").read().strip().replace(":", "")[-4:].upper()
    except OSError:
        mac = secrets.token_hex(2).upper()
    return f"TNT-Share-{mac}"


DEFAULTS = {
    # Mode 1, Wi-Fi -> Ethernet: the Pi's address on the switch side
    "share_ip": "192.168.50.1",
    "share_mask": "255.255.255.0",
    "share_dhcp": True,
    # Ethernet uplink used by mode 2 (hotspot)
    "uplink_dhcp": True,
    "uplink_ip": "192.168.1.50",
    "uplink_mask": "255.255.255.0",
    "uplink_gw": "192.168.1.1",
    "uplink_dns": "1.1.1.1 8.8.8.8",
    # Mode 2 hotspot
    "hs_ssid": "",
    "hs_password": "",
    "hs_channel": "6",
    "hs_ip": "192.168.60.1",
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONF) as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    changed = False
    if not cfg["hs_ssid"]:
        cfg["hs_ssid"], changed = _default_ssid(), True
    if not cfg["hs_password"]:
        cfg["hs_password"], changed = _default_password(), True
    if changed:
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=1)
    os.chmod(tmp, 0o600)  # holds the hotspot password
    os.replace(tmp, CONF)


# ---- validation helpers -------------------------------------------------

def valid_ip(s: str) -> bool:
    try:
        ipaddress.IPv4Address(s.strip())
        return True
    except ValueError:
        return False


def mask_to_prefix(mask: str) -> int | None:
    """'255.255.255.0' or '24' or '/24' -> 24; None if invalid."""
    m = mask.strip().lstrip("/")
    if m.isdigit():
        n = int(m)
        return n if 1 <= n <= 30 else None
    try:
        n = ipaddress.IPv4Network(f"0.0.0.0/{m}").prefixlen
    except ValueError:
        return None
    return n if 1 <= n <= 30 else None


def check_host(ip: str, mask: str) -> str | None:
    """Error text if ip/mask can't be a host address, else None."""
    if not valid_ip(ip):
        return f"Bad IP address: {ip}"
    p = mask_to_prefix(mask)
    if p is None:
        return f"Bad subnet mask: {mask}"
    iface = ipaddress.IPv4Interface(f"{ip.strip()}/{p}")
    if iface.ip in (iface.network.network_address, iface.network.broadcast_address):
        return f"{ip} is not a usable host address in /{p}"
    return None


def check_hotspot(ssid: str, password: str) -> str | None:
    if not 1 <= len(ssid.encode()) <= 32:
        return "SSID must be 1-32 characters"
    if not 8 <= len(password) <= 63:
        return "Password must be 8-63 characters"
    return None
