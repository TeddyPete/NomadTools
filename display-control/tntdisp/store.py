"""Saved displays: ~/.config/tnt-display-control/displays.json (mode 600,
it holds PJLink passwords, Sony keys and TV pairing keys)."""
from __future__ import annotations

import json
import os
import secrets

from .base import Display

CONF_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "tnt-display-control")
CONF = os.path.join(CONF_DIR, "displays.json")


def load() -> list[Display]:
    try:
        with open(CONF) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for d in data.get("displays", []):
        try:
            out.append(Display.from_dict(d))
        except TypeError:
            continue
    return out


def save(displays: list[Display]) -> None:
    os.makedirs(CONF_DIR, exist_ok=True)
    for d in displays:
        if not d.id:
            d.id = secrets.token_hex(4)
    tmp = CONF + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"version": 1, "displays": [d.to_dict() for d in displays]}, f, indent=1)
    os.replace(tmp, CONF)


def rooms(displays: list[Display]) -> list[str]:
    return sorted({d.room.strip() for d in displays if d.room.strip()}, key=str.lower)


def find(displays: list[Display], text: str) -> Display | None:
    """By id, exact name, host, or unique name prefix (case-insensitive)."""
    t = text.lower()
    for d in displays:
        if t in (d.id.lower(), d.name.lower(), d.host):
            return d
    hits = [d for d in displays if d.name.lower().startswith(t)]
    return hits[0] if len(hits) == 1 else None
