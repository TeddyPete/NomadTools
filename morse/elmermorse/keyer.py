"""The keyer: turns paddle or straight-key presses (GPIO or keyboard) into
key-down / key-up, with exact element timing, in its own thread.

Iambic A and B, dit/dah memory, a straight-key mode, and a text sender that
keys typed text at a set speed. Every key change goes to the outputs: the
sidetone, the radio (GPIO optocoupler or the QMX's DTR line, only while the
transmit switch is on) and a listener (the on-screen decoder).
"""
from __future__ import annotations

import threading
import time
from collections import deque

from . import morse as M

STUCK_S = 10.0     # transmit safety: a key held this long is let go


def now_ms() -> float:
    return time.monotonic() * 1000.0


class Keyer:
    def __init__(self, wpm: float = 18, mode: str = "Iambic B", swap: bool = False):
        self.wpm, self.mode, self.swap = wpm, mode, swap
        self.paddle = None             # radio.Paddle or None
        self.kb = {"dit": False, "dah": False, "straight": False}
        self.outputs: list = []        # callables(down: bool)
        self.listener = None           # callable(down: bool, t_ms: float)
        self.radio = None              # object with set(down); only while tx is on
        self.tx = False
        self.down = False
        self.down_since = 0.0
        self.stuck = False
        self.queue: deque = deque()    # (down, at_ms) for typed text
        self.text_busy = False
        self.text_cancel = False
        self._run = False
        self._thread = None
        self._lock = threading.Lock()

    # ---- life ----
    def start(self) -> None:
        if self._run:
            return
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._run = False
        if self._thread:
            self._thread.join(timeout=1)
        self._thread = None
        self._set(False)

    @property
    def unit(self) -> float:
        return 1200.0 / max(5, self.wpm)

    # ---- inputs from the UI thread ----
    def kb_press(self, which: str, down: bool) -> None:
        self.kb[which] = down

    def send_text(self, text: str) -> float:
        """Key typed text at self.wpm. Returns its length in seconds."""
        sched = M.schedule(text, M.timing(self.wpm))
        t0 = now_ms() + 30
        with self._lock:
            self.text_cancel = False
            for start, dur, _el, _ti in sched.elements:
                self.queue.append((True, t0 + start))
                self.queue.append((False, t0 + start + dur))
            self.text_busy = bool(self.queue)
        return sched.total / 1000.0

    def cancel_text(self) -> None:
        with self._lock:
            self.queue.clear()
            self.text_busy = False
        self._set(False)

    # ---- the thread ----
    def _paddles(self) -> tuple[bool, bool, bool]:
        gd, gh = self.paddle.read() if self.paddle else (False, False)
        if self.swap:
            gd, gh = gh, gd
        return gd or self.kb["dit"], gh or self.kb["dah"], self.kb["straight"]

    def _set(self, down: bool) -> None:
        if down == self.down:
            return
        self.down = down
        t = now_ms()
        if down:
            self.down_since = t
        for out in self.outputs:
            try:
                out(down)
            except Exception:
                pass
        if self.radio is not None and (self.tx or not down):
            try:
                self.radio.set(down)
            except Exception:
                pass
        if self.listener:
            self.listener(down, t)

    def _wait(self, until: float, watch_opposite: str | None = None) -> bool:
        """Sleep until `until` ms. Returns True if the opposite paddle was
        pressed meanwhile (iambic memory)."""
        hit = False
        while self._run:
            t = now_ms()
            if t >= until:
                break
            if watch_opposite:
                d, h, _ = self._paddles()
                if (watch_opposite == "dah" and h) or (watch_opposite == "dit" and d):
                    hit = True
            time.sleep(0.0008)
        return hit

    def _element(self, el: str) -> tuple[bool, bool]:
        """Send one element plus the space after it. Returns (opposite pressed
        during it, both paddles squeezed at some point)."""
        u = self.unit
        dur = u if el == "." else 3 * u
        opp = "dah" if el == "." else "dit"
        self._set(True)
        t0 = now_ms()
        d, h, _ = self._paddles()
        squeeze = d and h
        hit = self._wait(t0 + dur, opp)
        self._set(False)
        hit2 = self._wait(t0 + dur + u, opp)
        d, h, _ = self._paddles()
        squeeze = squeeze or (d and h)
        return hit or hit2, squeeze

    def _loop(self) -> None:
        last = None
        memory = None
        while self._run:
            # stuck-key safety for transmit
            if self.down and self.tx and now_ms() - self.down_since > STUCK_S * 1000:
                self.stuck = True
                self.cancel_text()
                self._set(False)
                self.kb = {"dit": False, "dah": False, "straight": False}
            # typed text has its own timeline
            if self.queue:
                with self._lock:
                    item = self.queue[0] if self.queue else None
                if item and now_ms() >= item[1]:
                    with self._lock:
                        if self.queue:
                            self.queue.popleft()
                        if not self.queue:
                            self.text_busy = False
                    self._set(item[0])
                time.sleep(0.0008)
                continue
            dit, dah, straight = self._paddles()
            if self.mode == "Straight key":
                want = straight or dit or dah
                if want != self.down:
                    self._set(want)
                time.sleep(0.0008)
                continue
            if straight != self.down and not (dit or dah):
                self._set(straight)        # space bar is always a straight key
                time.sleep(0.0008)
                continue
            nxt = None
            if memory:
                nxt, memory = memory, None
            elif dit and dah:
                nxt = "-" if last == "." else "."
            elif dit:
                nxt = "."
            elif dah:
                nxt = "-"
            if nxt is None:
                last = None
                time.sleep(0.0008)
                continue
            hit, squeeze = self._element(nxt)
            d, h, _ = self._paddles()
            opposite = "-" if nxt == "." else "."
            if hit and not ((opposite == "." and d) or (opposite == "-" and h)):
                memory = opposite          # dit/dah memory: tapped during the element
            elif self.mode == "Iambic B" and squeeze and not (d or h):
                memory = opposite          # mode B: one more after a squeeze is let go
            last = nxt
