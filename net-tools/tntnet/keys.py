"""Keyboard input.

On the CardputerZero the built-in keyboard is read straight from its
evdev device (/dev/input/cardputer-zero-internal), so keys work whether or
not the desktop window has focus. On a PC (no such device) pygame key
events are used instead.

Every key press becomes a Key(name, char):
  name: 'up' 'down' 'left' 'right' 'enter' 'esc' 'bksp' 'tab' 'del'
        'pgup' 'pgdn' 'home' 'end' or '' for a plain character
  char: the typed character ('' for named keys)
  ctrl: True when Ctrl was held
"""
from __future__ import annotations

import glob
import os
import select
import struct
from dataclasses import dataclass


@dataclass
class Key:
    name: str = ""
    char: str = ""
    ctrl: bool = False

    def __repr__(self) -> str:
        return f"Key({self.name or repr(self.char)}{' ctrl' if self.ctrl else ''})"

    # Up/Down for lists. Besides the arrow keys (Fn layer on the
    # CardputerZero), accept the Cardputer-style ; and . plus vi-style k/j.
    @property
    def up(self) -> bool:
        return self.name == "up" or (not self.ctrl and self.char in (";", "k", "K"))

    @property
    def down(self) -> bool:
        return self.name == "down" or (not self.ctrl and self.char in (".", "j", "J"))


NAMED = {1: "esc", 14: "bksp", 15: "tab", 28: "enter", 96: "enter", 103: "up", 108: "down",
         105: "left", 106: "right", 104: "pgup", 109: "pgdn", 102: "home", 107: "end", 111: "del"}
# evdev code -> (normal, shifted)
CHARS = {
    2: "1!", 3: "2@", 4: "3#", 5: "4$", 6: "5%", 7: "6^", 8: "7&", 9: "8*", 10: "9(", 11: "0)",
    12: "-_", 13: "=+", 16: "qQ", 17: "wW", 18: "eE", 19: "rR", 20: "tT", 21: "yY", 22: "uU",
    23: "iI", 24: "oO", 25: "pP", 26: "[{", 27: "]}", 30: "aA", 31: "sS", 32: "dD", 33: "fF",
    34: "gG", 35: "hH", 36: "jJ", 37: "kK", 38: "lL", 39: ";:", 40: "'\"", 41: "`~", 43: "\\|",
    44: "zZ", 45: "xX", 46: "cC", 47: "vV", 48: "bB", 49: "nN", 50: "mM", 51: ",<", 52: ".>",
    53: "/?", 57: "  ",
    # keypad codes some keyboard firmwares use for symbols
    55: "**", 74: "--", 78: "++", 83: "..", 98: "//", 117: "==",
    71: "77", 72: "88", 73: "99", 75: "44", 76: "55", 77: "66", 79: "11", 80: "22", 81: "33", 82: "00",
}
SHIFT, CTRL, CAPS = {42, 54}, {29, 97}, 58
EV_KEY = 1
EVENT = struct.Struct("llHHi")


def find_keyboard() -> str | None:
    env = os.environ.get("TNT_KEYBOARD")
    if env:
        return env
    if os.path.exists("/dev/input/cardputer-zero-internal"):
        return "/dev/input/cardputer-zero-internal"
    for d in sorted(glob.glob("/sys/class/input/event*")):
        try:
            name = open(f"{d}/device/name").read().strip().lower()
        except OSError:
            continue
        if "tca8418" in name or "cardputer" in name:
            return "/dev/input/" + os.path.basename(d)
    return None


class EvdevKeyboard:
    def __init__(self, path: str):
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.path = path
        self.shift = self.ctrl = self.caps = False
        self.held: set[int] = set()
        self.last_raw: list[str] = []
        self.log = None
        try:
            d = os.path.expanduser("~/.cache/tnt-av-net-tools")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "keys.log")
            if os.path.exists(path) and os.path.getsize(path) > 200_000:
                os.replace(path, path + ".1")
            self.log = open(path, "a", buffering=1)
            self.log.write(f"--- open {path}\n")
        except OSError:
            self.log = None

    def poll(self, timeout: float = 0.0) -> list[Key]:
        out: list[Key] = []
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return out
        try:
            data = os.read(self.fd, EVENT.size * 64)
        except BlockingIOError:
            return out
        for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _, _, etype, code, value = EVENT.unpack_from(data, i)
            if etype in (EV_KEY, 4):
                raw = f"{'key' if etype == EV_KEY else 'msc'} {code} {value}"
                self.last_raw = (self.last_raw + [raw])[-6:]
                if self.log:
                    try:
                        self.log.write(raw + "\n")
                    except OSError:
                        pass
            if etype != EV_KEY:
                continue
            if code in SHIFT:
                self.shift = value != 0
                continue
            if code in CTRL:
                self.ctrl = value != 0
                continue
            if code == CAPS and value == 1:
                self.caps = not self.caps
                continue
            if value == 0:
                continue
            k = self.translate(code)
            if k:
                out.append(k)
        return out

    def translate(self, code: int) -> Key | None:
        if code in NAMED:
            return Key(NAMED[code], "", self.ctrl)
        pair = CHARS.get(code)
        if not pair:
            return None
        ch = pair[1] if self.shift else pair[0]
        if self.caps and ch.isalpha():
            ch = ch.swapcase()
        return Key("", ch, self.ctrl)

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


def from_pygame(ev) -> Key | None:
    import pygame
    names = {pygame.K_ESCAPE: "esc", pygame.K_BACKSPACE: "bksp", pygame.K_TAB: "tab",
             pygame.K_RETURN: "enter", pygame.K_KP_ENTER: "enter", pygame.K_UP: "up",
             pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
             pygame.K_PAGEUP: "pgup", pygame.K_PAGEDOWN: "pgdn", pygame.K_HOME: "home",
             pygame.K_END: "end", pygame.K_DELETE: "del"}
    ctrl = bool(ev.mod & pygame.KMOD_CTRL)
    if ev.key in names:
        return Key(names[ev.key], "", ctrl)
    ch = ev.unicode or ""
    if not ch and 32 <= ev.key < 127:
        ch = chr(ev.key)
        if ev.mod & pygame.KMOD_SHIFT:
            ch = ch.upper()
    if ctrl and 1 <= ev.key < 256:
        ch = chr(ev.key)
    if ch and ch.isprintable():
        return Key("", ch, ctrl)
    return None
