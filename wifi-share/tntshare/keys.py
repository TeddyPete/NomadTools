"""Keyboard input read straight from Linux evdev (no extra packages).

The CardputerZero's keyboard (tca8418) is a normal Linux input device. We
read key events from every keyboard-like /dev/input/event* device and turn
them into Key(name, char) with a US layout, Shift and Caps Lock.
"""
from __future__ import annotations

import glob
import os
import select
import struct
from dataclasses import dataclass

EV_KEY = 1
_FMT = "llHHi"  # struct input_event: timeval, type, code, value
_SZ = struct.calcsize(_FMT)

_CHARS: dict[int, tuple[str, str]] = {}
for _row, _start in (("1234567890", 2), ("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44)):
    for _i, _c in enumerate(_row):
        _CHARS[_start + _i] = (_c, _c.upper())
for _code, _pair in {2: "1!", 3: "2@", 4: "3#", 5: "4$", 6: "5%", 7: "6^", 8: "7&", 9: "8*",
                     10: "9(", 11: "0)", 12: "-_", 13: "=+", 26: "[{", 27: "]}", 39: ";:",
                     40: "'\"", 41: "`~", 43: "\\|", 51: ",<", 52: ".>", 53: "/?", 57: "  "}.items():
    _CHARS[_code] = (_pair[0], _pair[1])

NAMED = {1: "esc", 14: "backspace", 15: "tab", 28: "enter", 96: "enter", 103: "up", 108: "down",
         105: "left", 106: "right", 111: "delete", 102: "home", 107: "end", 104: "pageup",
         109: "pagedown"}
SHIFT, CTRL, ALT, CAPS = {42, 54}, {29, 97}, {56, 100}, 58


@dataclass
class Key:
    name: str          # "enter", "up", "a", "A", "1" ...
    char: str = ""     # printable character, "" for control keys
    ctrl: bool = False


def _is_keyboard(event_path: str) -> bool:
    """True if the device reports letter keys (KEY_A..KEY_Z)."""
    n = os.path.basename(event_path)
    try:
        words = open(f"/sys/class/input/{n}/device/capabilities/key").read().split()
    except OSError:
        return False
    bits = 0
    for w in words:
        bits = (bits << 64) | int(w, 16)
    return all(bits >> code & 1 for code in (16, 30, 44))  # q, a, z


class Keyboard:
    def __init__(self, devices: list[str] | None = None):
        paths = devices or [p for p in sorted(glob.glob("/dev/input/event*")) if _is_keyboard(p)]
        self.fds = []
        for p in paths:
            try:
                self.fds.append(os.open(p, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                pass
        self.shift = self.ctrl = self.alt = False
        self.caps = False

    @property
    def ok(self) -> bool:
        return bool(self.fds)

    def poll(self, timeout: float) -> list[Key]:
        if not self.fds:
            select.select([], [], [], timeout)
            return []
        r, _, _ = select.select(self.fds, [], [], timeout)
        keys: list[Key] = []
        for fd in r:
            try:
                data = os.read(fd, _SZ * 64)
            except BlockingIOError:
                continue
            except OSError:
                continue
            for off in range(0, len(data) - _SZ + 1, _SZ):
                _, _, etype, code, value = struct.unpack_from(_FMT, data, off)
                if etype == EV_KEY:
                    k = self._feed(code, value)
                    if k:
                        keys.append(k)
        return keys

    def _feed(self, code: int, value: int) -> Key | None:
        down = value != 0
        if code in SHIFT:
            self.shift = down
            return None
        if code in CTRL:
            self.ctrl = down
            return None
        if code in ALT:
            self.alt = down
            return None
        if code == CAPS:
            if value == 1:
                self.caps = not self.caps
            return None
        if not down:
            return None
        if code in NAMED:
            return Key(NAMED[code], ctrl=self.ctrl)
        if code in _CHARS:
            lo, hi = _CHARS[code]
            up = self.shift
            if lo.isalpha() and self.caps:
                up = not up
            ch = hi if up else lo
            return Key(ch, ch, ctrl=self.ctrl)
        return None

    def close(self) -> None:
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds = []
