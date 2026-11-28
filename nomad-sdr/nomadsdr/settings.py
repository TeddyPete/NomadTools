"""Settings in ~/.config/nomad-sdr/settings.json (store rule: per-user config
under ~/.config/<app>/), recordings and logs under ~/.local/share/nomad-sdr/."""
from __future__ import annotations

import json
import os

APP = "nomad-sdr"

DEFAULTS = {
    "freq": 146.520,           # MHz
    "mode": "NFM",
    "filter": {},              # mode -> Hz
    "gain": None,              # None = auto, else dB
    "squelch": None,           # None = off, else dBFS
    "volume": 0.6,
    "ppm": 0,
    "bias_tee": False,
    "hf": "direct",            # HF input: "direct" (V3 direct sampling Q), "upconverter", "off"
    "upconverter_mhz": 125.0,
    "step": 12500,             # Hz
    "license": "None",         # None / Technician / General / Extra
    "grid": "",                # typed Maidenhead locator when there's no GPS
    "rec_squelch": False,      # record only while the squelch is open
    "memories": [],            # [{"name", "freq", "mode"}]
    "aprs_to_rig": True,       # give decoded APRS to Rig Companion
    "aprs_audio": False,       # hear the APRS channel while decoding
    "fox_tone": True,
    "agc": True,
}


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP)


def data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP)


def path() -> str:
    return os.path.join(config_dir(), "settings.json")


def load() -> dict:
    s = dict(DEFAULTS)
    try:
        with open(path()) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save(s: dict) -> None:
    os.makedirs(config_dir(), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, path())
