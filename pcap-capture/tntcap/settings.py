"""Capture settings, kept in ~/.config/tnt-packet-capture/settings.json."""
from __future__ import annotations

import json
import os

from . import capture as C
from . import netinfo

DEFAULTS = {
    "iface": "",            # "" = the wired port (eth0)
    "preset": "all",
    "host": "",
    "port": "",
    "custom": "",
    "tag": "",
    "duration": "No limit",
    "size": "100 MB",
    "mode": "Stop at limit",   # or "Ring buffer"
    "snap": "Full packets",    # or "Headers only"
    "promisc": True,
}


def path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "tnt-packet-capture", "settings.json")


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(path()) as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if cfg["preset"] not in C.PRESET:
        cfg["preset"] = "all"
    if not cfg["iface"]:
        cfg["iface"] = netinfo.wired()
    return cfg


def save(cfg: dict) -> None:
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump({k: cfg.get(k, v) for k, v in DEFAULTS.items()}, f, indent=1)
    os.replace(tmp, path())
