"""Morse engine: the code table, PARIS / Farnsworth timing, playback schedules,
an adaptive straight-key decoder and a fist grader.

Ported from Ask Elmer's app/src/games/morse/engine.ts and practiceText.ts so
the Cardputer app teaches exactly what askelmer.com teaches. Pure Python.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

# International Morse code (ITU-R M.1677-1). "." = dit, "-" = dah.
MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....", "I": "..",
    "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "/": "-..-.", "=": "-...-",
}
# Prosigns are sent run together. Written in text as <AR>, <SK>, <BT>.
PROSIGNS = {"AR": ".-.-.", "SK": "...-.-", "BT": "-...-"}

# Koch method teaching order (as used by LCWO). Starts with K and M.
KOCH_ORDER = ["K", "M", "U", "R", "E", "S", "N", "A", "P", "T", "L", "W", "I", ".", "J", "Z", "=", "F", "O", "Y",
              ",", "V", "G", "5", "/", "Q", "9", "2", "H", "3", "8", "B", "?", "4", "7", "C", "1", "D", "6", "0", "X"]

HAM_WORDS = {
    "CQ": "Calling any station", "DE": "From (this is)", "K": "Over, go ahead", "R": "Received",
    "73": "Best regards", "RST": "Signal report", "599": "Perfect signal report", "QTH": "My location is",
    "QSL": "I confirm receipt", "QSO": "A contact", "QRZ": "Who is calling me?", "QRS": "Please send slower",
    "UR": "Your / you are", "TU": "Thank you", "TNX": "Thanks", "FER": "For", "ES": "And",
    "FB": "Fine business (great)", "OM": "Old man (any operator)", "OP": "Operator", "GM": "Good morning",
    "GE": "Good evening", "GL": "Good luck", "HW": "How do you copy?", "PSE": "Please", "AGN": "Again",
    "RIG": "Radio equipment", "ANT": "Antenna", "WX": "Weather", "NAME": "My name is",
    "POTA": "Parks on the Air", "SOTA": "Summits on the Air",
}

_REVERSE = {v: f"<{k}>" for k, v in PROSIGNS.items()}
_REVERSE.update({v: k for k, v in MORSE.items()})   # "=" wins over <BT>: it can be typed


def char_for(code: str) -> str | None:
    return _REVERSE.get(code)


def code_for(ch: str) -> str | None:
    up = ch.upper()
    m = re.fullmatch(r"<([A-Z]{2})>", up)
    if m:
        return PROSIGNS.get(m.group(1))
    return MORSE.get(up)


@dataclass
class Token:
    text: str   # "A", "7", "<AR>", or " " for a word space
    code: str   # dots and dashes, "" for a word space


def tokenize(text: str) -> list[Token]:
    """Unknown characters are dropped; runs of spaces become one word gap."""
    out: list[Token] = []
    src = text.upper().strip()
    i = 0
    while i < len(src):
        ch = src[i]
        if ch.isspace():
            if out and out[-1].code:
                out.append(Token(" ", ""))
            i += 1
            continue
        if ch == "<":
            end = src.find(">", i)
            name = src[i + 1:end] if end > i else ""
            if name in PROSIGNS:
                out.append(Token(f"<{name}>", PROSIGNS[name]))
                i = end + 1
                continue
        code = MORSE.get(ch)
        if code:
            out.append(Token(ch, code))
        i += 1
    return out


def encode(text: str) -> str:
    return " ".join("/" if t.code == "" else t.code for t in tokenize(text))


def pretty(code: str) -> str:
    return code.replace(".", "·").replace("-", "−")


def sound_out(ch: str) -> str:
    """'dah-di-dah' style, the way CW operators learn a character."""
    code = code_for(ch) or ""
    return "-".join("dah" if e == "-" else ("dit" if i == len(code) - 1 else "di") for i, e in enumerate(code))


def chars_of(text: str) -> list[str]:
    return [t.text for t in tokenize(text) if t.code]


# ---- timing -------------------------------------------------------------------------

def unit_ms(wpm: float) -> float:
    return 1200.0 / wpm


@dataclass
class Timing:
    char_wpm: float
    eff_wpm: float
    unit: float       # dit length, ms
    char_gap: float   # between characters, ms
    word_gap: float   # between words, ms


def timing(char_wpm: float, eff_wpm: float | None = None) -> Timing:
    """PARIS timing with Farnsworth spacing (ARRL): characters at char_wpm, only
    the gaps stretched so the overall speed is eff_wpm."""
    u = unit_ms(char_wpm)
    if eff_wpm is None or eff_wpm >= char_wpm:
        return Timing(char_wpm, char_wpm, u, 3 * u, 7 * u)
    spacing = 60000.0 / eff_wpm - 31 * u
    return Timing(char_wpm, eff_wpm, u, 3 * spacing / 19, 7 * spacing / 19)


@dataclass
class Schedule:
    tokens: list
    elements: list    # (start_ms, dur_ms, ".", token_index)
    spans: list       # per token (start, end)
    total: float


def schedule(text_or_tokens, t: Timing) -> Schedule:
    tokens = tokenize(text_or_tokens) if isinstance(text_or_tokens, str) else list(text_or_tokens)
    if isinstance(text_or_tokens, str) and text_or_tokens[-1:].isspace() and tokens:
        tokens.append(Token(" ", ""))
    els, spans, now = [], [], 0.0
    for ti, tok in enumerate(tokens):
        if not tok.code:
            now += t.word_gap - t.char_gap
            spans.append((now, now))
            continue
        start = now
        for i, el in enumerate(tok.code):
            if i:
                now += t.unit
            dur = t.unit if el == "." else 3 * t.unit
            els.append((now, dur, el, ti))
            now += dur
        spans.append((start, now))
        now += t.char_gap
    return Schedule(tokens, els, spans, now)


# ---- straight-key decoder -------------------------------------------------------------

@dataclass
class Mark:
    at: float
    dur: float
    el: str
    gap_before: float | None


@dataclass
class Decoded:
    char: str            # "#" when the code is not in the table
    code: str
    marks: list = field(default_factory=list)
    space_before: bool = False


def classify_mark(dur: float, dit: float) -> str:
    return "." if dur < 2 * dit else "-"


def two_means(values: list) -> tuple[float, float] | None:
    """1-D two-means split; None unless the clusters are clearly apart (>= 1.8x)."""
    if len(values) < 2:
        return None
    s = sorted(values)
    if s[-1] / max(s[0], 1e-9) < 1.8:
        return None
    best = None
    for i in range(1, len(s)):
        a, b = s[:i], s[i:]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        cost = sum((v - ma) ** 2 for v in a) + sum((v - mb) ** 2 for v in b)
        if best is None or cost < best[2]:
            best = (ma, mb, cost)
    if not best or best[1] / max(best[0], 1e-9) < 1.8:
        return None
    return best[0], best[1]


class KeyDecoder:
    """Feed key-down / key-up times (ms, any monotonic clock) and call poll(now)
    from a timer; characters come out when enough silence has passed. The dit
    length adapts by two-means clustering of recent marks, so a slow, steady
    beginner (or a radio signal at any speed) is read correctly."""

    def __init__(self, initial_dit_ms: float = 100, char_gap_units: float = 2.5, word_gap_units: float = 5):
        self.dit = initial_dit_ms
        self.cgu, self.wgu = char_gap_units, word_gap_units
        self.down_at = None
        self.last_up = None
        self.pending: list[Mark] = []
        self.pending_space = False
        self.recent: list[float] = []
        self.history: list[Mark] = []

    @property
    def is_down(self) -> bool:
        return self.down_at is not None

    @property
    def wpm(self) -> float:
        return 1200.0 / self.dit

    def key_down(self, t: float) -> list[Decoded]:
        if self.down_at is not None:
            return []
        out = self.poll(t)
        self.down_at = t
        return out

    def key_up(self, t: float) -> None:
        if self.down_at is None:
            return
        dur = max(1.0, t - self.down_at)
        gap = None if self.last_up is None or not self.pending else self.down_at - self.last_up
        self._observe(dur)
        m = Mark(self.down_at, dur, classify_mark(dur, self.dit), gap)
        self.pending.append(m)
        self.history.append(m)
        if len(self.history) > 400:
            del self.history[:100]
        self.down_at = None
        self.last_up = t

    def poll(self, now: float) -> list[Decoded]:
        if self.down_at is not None or self.last_up is None:
            return []
        silence = now - self.last_up
        out = []
        if self.pending and silence >= self.cgu * self.dit:
            out.append(self._flush())
        if not self.pending_space and not self.pending and silence >= self.wgu * self.dit:
            self.pending_space = True
        return out

    def flush(self) -> list[Decoded]:
        return [self._flush()] if self.pending else []

    def reset(self) -> None:
        self.down_at = self.last_up = None
        self.pending, self.pending_space = [], False
        self.history.clear()

    def _flush(self) -> Decoded:
        for m in self.pending:
            m.el = classify_mark(m.dur, self.dit)
        code = "".join(m.el for m in self.pending)
        d = Decoded(char_for(code) or "#", code, self.pending, self.pending_space)
        self.pending, self.pending_space = [], False
        return d

    def _observe(self, dur: float) -> None:
        self.recent.append(dur)
        if len(self.recent) > 16:
            self.recent.pop(0)
        split = two_means(self.recent)
        if split:
            est = (split[0] + split[1] / 3) / 2
            self.dit = min(600.0, max(20.0, 0.3 * self.dit + 0.7 * est))
        else:
            target = dur if dur < 2 * self.dit else dur / 3
            self.dit = min(600.0, max(20.0, 0.5 * self.dit + 0.5 * target))


@dataclass
class Fist:
    dit: float
    dah: float | None
    ratio: float | None
    dit_spread: float
    dah_spread: float
    gap_units: float | None
    score: int


def analyze_fist(chars) -> Fist | None:
    """Grade a straight-key fist from Decoded characters."""
    marks = [m for c in chars for m in c.marks]
    if not marks:
        return None

    def mean(xs):
        return sum(xs) / len(xs)

    def cv(xs):
        if len(xs) < 2:
            return 0.0
        m = mean(xs)
        return (mean([(x - m) ** 2 for x in xs]) ** 0.5) / m

    dits = [m.dur for m in marks if m.el == "."]
    dahs = [m.dur for m in marks if m.el == "-"]
    dit = mean(dits) if dits else (mean(dahs) / 3 if dahs else marks[0].dur)
    dah = mean(dahs) if dahs else None
    ratio = dah / dit if dits and dah else None
    gaps = [m.gap_before for c in chars for m in c.marks[1:] if m.gap_before is not None]
    gap_units = mean(gaps) / dit if gaps else None
    ds, hs = cv(dits), cv(dahs)
    parts = []
    if ratio is not None:
        parts.append((min(1, max(0, 1 - abs(ratio - 3) / 2)), 0.4))
    spread = (ds + hs) / 2 if dits and dahs else (ds if dits else hs)
    parts.append((min(1, max(0, 1 - spread / 0.5)), 0.4))
    if gap_units is not None:
        parts.append((min(1, max(0, 1 - abs(gap_units - 1) / 1.5)), 0.2))
    w = sum(p[1] for p in parts)
    score = round(100 * sum(v * wt for v, wt in parts) / w)
    return Fist(dit, dah, ratio, ds, hs, gap_units, score)


# ---- practice text (only characters the learner has unlocked) -------------------------

WORD_BANK = [
    "UR", "ES", "FB", "OK", "TU", "GM", "GA", "GE", "OM", "YL", "CQ", "DE", "KN", "SK", "RST", "QTH", "QSL", "QRS", "QRZ",
    "WX", "RIG", "ANT", "PSE", "AGN", "TNX", "FER", "HW", "CPY", "NAME", "VERT", "YAGI", "DIPOLE", "POTA", "SOTA",
    "ME", "RE", "MUSE", "SURE", "USER", "MURK", "EMU", "RUSE", "SUM", "RUN", "SUN", "NUT", "PUT", "TUNE", "TUNER", "MAP",
    "PARK", "MARK", "STAR", "TEAM", "RANK", "SNAP", "TRAP", "PAST", "SPARK", "SMART", "NEAR", "TEST", "SET", "NET", "TEN",
    "LAMP", "PLANT", "WALL", "TALL", "WALK", "TALK", "WAIT", "SLEW", "NEW", "TWIN", "WILL", "LIST", "LISTEN", "METER",
    "PLAN", "SPLIT", "SIMPLE", "TIME", "KEY", "FINE", "FAST", "SLOW", "JOIN", "FROZEN", "ZONE", "WAVE", "RADIO", "MORSE",
    "CODE", "HAM", "COLD", "HOT", "RAIN", "SNOW", "WARM", "SOLAR", "POWER", "GROUND", "BAND", "CLEAR", "COPY", "HELLO",
    "FRIEND", "CALL", "QUICK", "BRAVO", "EXTRA", "GENERAL",
]
QSO_TIERS = [
    ["73", "TU", "ES", "FB", "UR", "OK", "GM", "R R"],
    ["UR 599", "NAME TED", "QTH MN", "TU 73", "RST 599", "GE OM", "FB OM", "OP TED"],
    ["CQ CQ DE K0XYZ", "DE N0CALL K", "QTH ST PAUL", "WX SUNNY", "RIG 100W", "ANT DIPOLE", "TNX FER CALL"],
    ["UR RST 579 579", "QSL VIA BURO", "HW CPY?", "NAME ANN ANN", "R TNX 73 ES GL", "PSE QRS K", "QTH DULUTH MN"],
    ["CQ CQ CQ DE W0XYZ K", "GE OM UR 599 = NAME TED", "R R TNX NAME ANN QTH MN", "TU FER QSO 73 DE K0XYZ",
     "RIG 5W ANT VERT", "WX COLD -5C = 73"],
]
_SHAPE = [(1, 3), (1, 5), (2, 5), (3, 6), (4, 8)]


def unlocked(learned: int) -> list[str]:
    return KOCH_ORDER[:max(0, learned)]


def fits(text: str, allowed) -> bool:
    return bool(text.strip()) and all(c == " " or c in allowed for c in text)


def practice_message(tier: int, allowed, used=(), rng: random.Random | None = None) -> str:
    """A message for a difficulty tier using only allowed characters: real QSO
    fragments first, then bank words, then 3-5 character random groups."""
    r = rng or random
    t = max(0, min(tier, len(_SHAPE) - 1))
    qso = [m for m in QSO_TIERS[t] if fits(m, allowed)]
    fresh = [m for m in qso if m not in used]
    if fresh and r.random() < 0.6:
        return r.choice(fresh)
    words, maxlen = _SHAPE[t]
    bank = [w for w in WORD_BANK if len(w) <= maxlen and fits(w, allowed)]
    chars = [c for c in allowed if c != " "]
    msg = ""
    for _ in range(6):
        parts = []
        for _ in range(words):
            if len(bank) >= 3 and r.random() < 0.75:
                parts.append(r.choice(bank))
            else:
                n = min(maxlen, 3 + int(r.random() * 3))
                parts.append("".join(r.choice(chars) for _ in range(n)))
        msg = " ".join(parts)
        if msg not in used:
            return msg
    return r.choice(qso) if qso else msg


# ---- call signs and reports (for the park hunt) ----------------------------------------

CUT = {"9": "N", "0": "T", "5": "E", "1": "A"}   # cut numbers, as in "5NN"


def normalize_rst(s: str) -> str:
    back = {"N": "9", "T": "0", "E": "5", "A": "1"}
    return "".join(back.get(c, c) for c in s.upper().replace(" ", ""))


def make_call(r: random.Random, allowed, district: str | None = None) -> str | None:
    """A US-format call sign (random placeholder) using allowed characters."""
    digits = [d for d in "0123456789" if d in allowed]
    letters = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c in allowed]
    if not digits or not letters:
        return None
    digit = district if district and district in allowed else r.choice(digits)
    prefixes = [p for p in ("K", "W", "N", "KD", "KE", "KF", "KI", "WB", "AC", "AE") if all(c in allowed for c in p)]
    prefix = r.choice(prefixes) if prefixes else r.choice(letters)
    n = 3 if len(prefix) == 1 else (2 if r.random() < 0.5 else 3)
    return prefix + digit + "".join(r.choice(letters) for _ in range(n))
