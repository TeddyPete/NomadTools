"""Settings, saved logins (opt-in only) and saved terminal commands.
Everything lives in ~/.config/tnt-av-net-tools/ with owner-only access."""
from __future__ import annotations

import json
import os

CONF_DIR = os.path.expanduser("~/.config/tnt-av-net-tools")


def _path(name: str) -> str:
    return os.path.join(CONF_DIR, name)


def load(name: str, default):
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name: str, data) -> None:
    os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
    tmp = _path(name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _path(name))


class Config(dict):
    def __init__(self):
        super().__init__(load("config.json", {}))
        self.setdefault("site", "")

    def write(self) -> None:
        save("config.json", dict(self))


# ---- logins: only kept when the user says so on the login form

def get_login(kind: str, host: str) -> dict | None:
    return load("logins.json", {}).get(f"{kind}@{host}")


def put_login(kind: str, host: str, user: str, password: str) -> None:
    data = load("logins.json", {})
    data[f"{kind}@{host}"] = {"user": user, "password": password}
    save("logins.json", data)


def forget_login(kind: str, host: str) -> None:
    data = load("logins.json", {})
    if data.pop(f"{kind}@{host}", None) is not None:
        save("logins.json", data)


def forget_all_logins() -> int:
    data = load("logins.json", {})
    save("logins.json", {})
    return len(data)


# ---- saved command strings per device (terminal)

def get_commands(target: str) -> list[dict]:
    return load("commands.json", {}).get(target, [])


def add_command(target: str, text: str, hex_mode: bool, ending: str) -> None:
    data = load("commands.json", {})
    lst = data.setdefault(target, [])
    entry = {"text": text, "hex": hex_mode, "ending": ending}
    if entry not in lst:
        lst.append(entry)
    save("commands.json", data)


def delete_command(target: str, idx: int) -> None:
    data = load("commands.json", {})
    lst = data.get(target, [])
    if 0 <= idx < len(lst):
        lst.pop(idx)
        save("commands.json", data)
