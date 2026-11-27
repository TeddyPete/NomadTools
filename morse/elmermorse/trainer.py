"""Koch trainer progress and app settings, saved in ~/.config/askelmer-morse/.

Same rules as askelmer.com's trainer (games/morse/trainerStore.ts): start
with K and M; a new character unlocks once the last `unlock_answers` answers
are 90% right, the newest character has 15 tries at 85%, and nothing is in
trouble. Wrong answers never take a learned character away.
"""
from __future__ import annotations

import json
import os
import random
import time

from .morse import KOCH_ORDER

PKG = "askelmer-morse"
UNLOCK_ANSWERS = 60
UNLOCK_ACCURACY = 0.9
NEWEST_TRIES = 15
NEWEST_ACCURACY = 0.85
TROUBLE_MIN_TRIES = 6
TROUBLE_WINDOW = 10
TROUBLE_BELOW = 0.75
RECOVER_AT = 0.85
PER_CHAR = 20
SPACED_GAP = 3
CHAR_SPEEDS = [12, 15, 18, 20, 25]

DEFAULT_SETTINGS = {
    "char_wpm": 15,          # trainer and games: character speed
    "eff_wpm": 8,            # Farnsworth overall speed for copy practice
    "tone": 600,             # sidetone pitch, Hz
    "volume": 60,            # %
    "key_wpm": 18,           # keyer speed (paddle and sending to the radio)
    "key_mode": "Iambic B",  # Iambic A | Iambic B | Straight key
    "swap": False,           # swap dit and dah paddles
    "radio": "Off",          # Off | GPIO key-out | QMX over USB
    "tx": False,             # transmit switch: never saved as on
    "key_pin": 23,           # GPIO for the optocoupler (EXT pin 3)
    "dit_pin": 22,           # EXT pin 5
    "dah_pin": 26,           # EXT pin 1
    "serial": "auto",        # QMX virtual COM port
    "audio_in": "plughw:CARD=ES8389Audio,DEV=0",   # CW decoder input: the side jack
    "call": "",              # your call sign, for the hunt and the QSO
}


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, PKG)


def acc(bits) -> float | None:
    return sum(bits) / len(bits) if bits else None


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "state.json")
        self.learned = 2
        self.introduced = 0
        self.unlock_answers = UNLOCK_ANSWERS
        self.stats: dict[str, list] = {}
        self.window: list = []
        self.trouble: list[str] = []
        self.confusions: dict[str, dict[str, int]] = {}
        self.last_heard: dict[str, int] = {}
        self.seconds: dict[str, int] = {}
        self.totals = {"attempts": 0, "correct": 0, "best_run": 0, "run": 0}
        self.send = {"results": [], "wpm": []}
        self.games = {"copy_best": 0, "send_best": 0, "hunt_best": 0}
        self.settings = dict(DEFAULT_SETTINGS)
        try:
            d = json.load(open(self.path))
            for k in ("learned", "introduced", "unlock_answers", "stats", "window", "trouble", "confusions",
                      "last_heard", "seconds", "totals", "send", "games"):
                if k in d:
                    setattr(self, k, d[k])
            self.settings.update({k: v for k, v in d.get("settings", {}).items() if k in DEFAULT_SETTINGS})
        except (OSError, ValueError, TypeError):
            pass
        self.learned = max(2, min(len(KOCH_ORDER), int(self.learned)))
        self.settings["tx"] = False   # transmit always starts off

    def save(self) -> None:
        d = {k: getattr(self, k) for k in ("learned", "introduced", "unlock_answers", "stats", "window", "trouble",
                                           "confusions", "last_heard", "seconds", "totals", "send", "games")}
        d["settings"] = {**self.settings, "tx": False}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(d, fh, separators=(",", ":"))
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ---- what is learned -------------------------------------------------------
    @property
    def chars(self) -> list[str]:
        return KOCH_ORDER[:self.learned]

    @property
    def allowed(self) -> set:
        return set(self.chars)

    @property
    def newest(self) -> str:
        return self.chars[-1]

    @property
    def next_char(self) -> str | None:
        return KOCH_ORDER[self.learned] if self.learned < len(KOCH_ORDER) else None

    def char_acc(self, c: str) -> float | None:
        return acc(self.stats.get(c, []))

    def window_acc(self) -> float | None:
        return acc(self.window[-self.unlock_answers:])

    def progress_text(self) -> str:
        w = self.window[-self.unlock_answers:]
        a = acc(w)
        return f"{len(w)}/{self.unlock_answers} answers, {round(100 * a) if a is not None else 0}% right"

    def add_seconds(self, s: float) -> None:
        day = time.strftime("%Y-%m-%d")
        self.seconds[day] = self.seconds.get(day, 0) + int(s)

    def today_minutes(self) -> int:
        return self.seconds.get(time.strftime("%Y-%m-%d"), 0) // 60

    # ---- picking and answering ---------------------------------------------------
    def pick(self, recent: list, rng: random.Random | None = None) -> str:
        """Newest and weak characters more often, ones not heard for a while come
        back, trouble letters first, never three of the same in a row."""
        r = rng or random
        pool = self.chars
        blocked = recent[-1] if len(recent) >= 2 and recent[-1] == recent[-2] else None
        trouble = [c for c in self.trouble if c in pool and c != blocked]
        if trouble and r.random() < 0.5:
            return r.choice(trouble)
        weights = []
        for c in pool:
            a = self.char_acc(c)
            w = 1.0
            if c == self.newest:
                w += 2
            if a is None:
                w += 1
            elif a < 0.8:
                w += 1.5
            if c in self.trouble:
                w += 1
            seen = self.last_heard.get(c)
            if seen is not None and self.totals["attempts"] - seen > SPACED_GAP * len(pool):
                w += 1
            if c == blocked:
                w = 0
            weights.append(w)
        return r.choices(pool, weights)[0]

    def answer(self, heard: str, typed: str) -> str | None:
        """Record one answer. Returns the newly unlocked character, if any."""
        right = typed.upper() == heard
        bit = 1 if right else 0
        s = self.stats.setdefault(heard, [])
        s.append(bit)
        del s[:-PER_CHAR]
        self.window.append(bit)
        del self.window[:-100]
        t = self.totals
        t["attempts"] += 1
        t["correct"] += bit
        t["run"] = t["run"] + 1 if right else 0
        t["best_run"] = max(t["best_run"], t["run"])
        self.last_heard[heard] = t["attempts"]
        if not right and typed:
            row = self.confusions.setdefault(heard, {})
            row[typed.upper()] = min(5, row.get(typed.upper(), 0) + 1)
        recent = s[-TROUBLE_WINDOW:]
        a = acc(recent)
        if heard in self.trouble:
            if a is not None and a >= RECOVER_AT:
                self.trouble.remove(heard)
        elif len(recent) >= TROUBLE_MIN_TRIES and a is not None and a < TROUBLE_BELOW:
            self.trouble.append(heard)
        return self._maybe_unlock()

    def can_unlock(self) -> bool:
        if self.next_char is None or self.trouble:
            return False
        w = self.window[-self.unlock_answers:]
        if len(w) < self.unlock_answers or acc(w) < UNLOCK_ACCURACY:
            return False
        nw = self.stats.get(self.newest, [])[-NEWEST_TRIES:]
        return len(nw) >= NEWEST_TRIES and acc(nw) >= NEWEST_ACCURACY

    def _maybe_unlock(self) -> str | None:
        if not self.can_unlock():
            return None
        c = self.next_char
        self.learned += 1
        self.window = []
        self.save()
        return c

    def reset(self) -> None:
        """Start the trainer over (settings and game bests are kept)."""
        self.learned, self.introduced = 2, 0
        self.stats, self.window, self.trouble = {}, [], []
        self.confusions, self.last_heard = {}, {}
        self.totals = {"attempts": 0, "correct": 0, "best_run": 0, "run": 0}
        self.save()

    def unlock_all(self) -> None:
        self.learned = len(KOCH_ORDER)
        self.introduced = self.learned
        self.window = []
        self.save()

    # ---- sending practice -------------------------------------------------------
    def sent(self, right: bool, wpm: float | None) -> None:
        self.send["results"] = (self.send["results"] + [1 if right else 0])[-100:]
        if right and wpm:
            self.send["wpm"] = (self.send["wpm"] + [round(wpm, 1)])[-20:]


CHEERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "morse-cheers.json")
SPEAKERS = {"elmer": "Elmer", "penny": "Penny", "gus": "Gus"}


def cheer(c: str, rng: random.Random | None = None) -> tuple[str, str]:
    """(speaker name, line) for a newly unlocked character, from Ask Elmer's cheers."""
    r = rng or random
    try:
        lines = json.load(open(CHEERS_PATH, encoding="utf-8"))["lines"]
    except (OSError, ValueError, KeyError):
        return "Elmer", "New character learned. Well done!"
    mine = [x for x in lines if x.get("char") == c] or [x for x in lines if x.get("char") is None]
    x = r.choice(mine)
    return SPEAKERS.get(x["speaker"], x["speaker"].title()), x["text"]
