"""Commands by name, shared by the screens and the command line, plus
room-wide (group) commands that run on every display at once."""
from __future__ import annotations

import concurrent.futures as cf
import threading

from .base import Display, DisplayError
from .drivers import driver
from . import wol

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

# Commands that change the display (so group mute skips toggle-only TVs).
EXPLICIT_MUTE = {"pjlink", "lg", "sony"}


def lock(d: Display) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(d.id or d.host, threading.Lock())


def run(d: Display, cmd: str, arg=None):
    """cmd: status on off inputs input vol mute avmute pictures picture
    message info pair wol. Returns the driver's result."""
    if cmd == "wol":
        return wol.wake(arg or d.mac, d.host)
    drv = driver(d)
    with lock(d):
        if cmd == "status":
            return drv.status()
        if cmd in ("on", "off"):
            return drv.power(cmd == "on")
        if cmd == "inputs":
            return drv.inputs()
        if cmd == "input":
            return drv.set_input(str(arg))
        if cmd == "vol":
            return drv.volume(int(arg or 1))
        if cmd in ("mute", "avmute"):
            on = None if arg in (None, "toggle") else (arg in (True, "on", "1", "yes"))
            return getattr(drv, cmd)(on)
        if cmd == "pictures":
            return drv.picture_modes()
        if cmd == "picture":
            return drv.set_picture(str(arg))
        if cmd == "message":
            return drv.message(str(arg or "Hello from Nomad Display Control"))
        if cmd == "info":
            return drv.info()
        if cmd == "pair":
            return drv.pair()
        if cmd == "menus":
            return drv.service_menus()
        if cmd == "svcmenu":
            return drv.open_service_menu(str(arg))
        if cmd == "remote":
            return drv.remote(str(arg))
    raise DisplayError(f"Unknown command {cmd}")


def supports(d: Display, cap: str) -> bool:
    return cap in driver(d).caps


def group(displays: list[Display], cmd: str, arg=None) -> list[tuple[Display, bool, str]]:
    """Run cmd on all displays at once: [(display, ok, text)]."""
    def one(d):
        if cmd == "mute" and d.kind not in EXPLICIT_MUTE:
            return d, False, "mute is toggle-only, skipped"
        try:
            r = run(d, cmd, arg)
            return d, True, r if isinstance(r, str) else "OK"
        except (DisplayError, OSError, ValueError) as e:
            return d, False, str(e) or e.__class__.__name__
    if not displays:
        return []
    with cf.ThreadPoolExecutor(min(8, len(displays))) as ex:
        return list(ex.map(one, displays))


def summary(results) -> str:
    ok = sum(1 for _, good, _ in results if good)
    return f"{ok} of {len(results)} OK"


def status_text(st: dict) -> str:
    """'ON  HDMI 1  vol 12  muted' for the screen."""
    if not st:
        return ""
    bits = [str(st.get("power", "?")).upper()]
    if st.get("input"):
        bits.append(str(st["input"])[:14])
    if st.get("volume") is not None:
        bits.append(f"vol {st['volume']}")
    if st.get("mute"):
        bits.append("muted")
    if st.get("avmute"):
        bits.append("pic mute")
    return "  ".join(bits)
