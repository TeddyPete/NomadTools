"""Ask Elmer Morse: the app. Screens on the LCD, keyboard and GPIO paddle in."""
from __future__ import annotations

import random
import time
from collections import deque

from . import __version__
from . import audio as A
from . import cwdecode as D
from . import lcd as L
from . import morse as M
from . import nomadui as T
from . import radio as R
from .keyer import Keyer
from .keys import Keyboard
from .trainer import CHAR_SPEEDS, Store, cheer
from .ui import BACK, DOWN, SELECT, UP, Confirm, Form, Menu, Message, Prompt, Screen, nav_key, wrap

APP_TITLE = "Ask Elmer"
T.set_about("Ask Elmer Morse", __version__, extra="Learn more at askelmer.com")
HELP_MAIN = ("Ask Elmer Morse: learn CW the Koch way, play the Morse games from askelmer.com, key with a "
             "paddle on the GPIO pins (or the keyboard), send to your radio, and decode CW off the air. "
             "Learn why at askelmer.com.")
TYPE_HINT = "Type what you hear  SPACE again  ESC done"
PUNCT = set(".,?/=")


class App:
    def __init__(self, panel: L.Panel, kb: Keyboard | None):
        self.panel, self.kb = panel, kb
        self.store = Store()
        self.player = A.Player()
        self.stack: list[Screen] = []
        self.helpview = None
        self.dirty = True
        self.quit = False
        self._big = {}

    # ---- helpers ----
    @property
    def s(self) -> dict:
        return self.store.settings

    def big(self, size: int):
        if size not in self._big:
            import os
            import pygame
            p = T.TITLE_FONT_PATHS[0]
            self._big[size] = pygame.font.Font(p if os.path.exists(p) else None, size)
        return self._big[size]

    def timing(self, eff: float | None = None) -> M.Timing:
        return M.timing(float(self.s["char_wpm"]), eff)

    def play(self, text: str, eff: float | None = None, **kw) -> float:
        samples = A.render(text, self.timing(eff), hz=float(self.s["tone"]), volume=int(self.s["volume"]) / 100, **kw)
        return self.player.play(samples)

    # ---- stack ----
    def push(self, s):
        self.stack.append(s)
        self.dirty = True

    def pop(self, s=None):
        if s is None:
            if len(self.stack) > 1:
                gone = self.stack.pop()
                gone.leave()
            else:
                self.quit = True
        elif s in self.stack:
            self.stack.remove(s)
            s.leave()
        self.dirty = True

    def open_about(self):
        """The About screen (shown like Fn+H help, ESC closes it)."""
        self.helpview = T.AboutView()
        self.dirty = True

    def wake(self):
        self.dirty = True

    def run(self):
        self.push(Home(self))
        last = 0.0
        while not self.quit:
            top = self.stack[-1]
            if self.kb:
                self.kb.releases = getattr(top, "morse_keys", set())
            keys = self.kb.poll(getattr(top, "poll_s", 0.1)) if self.kb else (time.sleep(0.1) or [])
            for k in keys:
                if self.stack:
                    self.dispatch(k)
                self.dirty = True
            if self.stack:
                self.stack[-1].tick()
            now = time.monotonic()
            if self.dirty or now - last > 1.0:
                self.draw()
                last = now
                self.dirty = False
        for s in reversed(self.stack):
            s.leave()
        self.player.stop()
        self.store.save()

    def dispatch(self, k):
        top = self.stack[-1]
        if k.up:
            ku = getattr(top, "key_up", None)
            if ku:
                ku(k)
            return
        if self.helpview is not None:
            if self.helpview.handle(k) == "close":
                self.helpview = None
            return
        if k.name == "help":
            self.helpview = T.HelpView(top.title, top.help or HELP_MAIN, top.keybar())
            return
        if not top.text_entry and top.soft(k):
            return
        top.key(k if top.text_entry else nav_key(k))

    def draw(self):
        if not self.stack:
            return
        surf = self.panel.surf
        if self.helpview is not None:
            self.helpview.render(surf, self.panel.fonts)
            self.panel.flush()
            return
        s = self.stack[-1]
        rows, sel = s.rows()
        T.render(surf, s.title, rows, s.hint, sel, s.right(), self.panel.fonts, s.keybar())
        paint = getattr(s, "paint", None)
        if paint:
            paint(surf, self.panel.fonts)
        self.panel.flush()


Screen.leave = lambda self: None   # screens that hold hardware or sound override this


def big_char(app, surf, ch: str, color, x: int = 262, y: int = 30, size: int = 92):
    """A big character on the right of the screen (centred on x)."""
    import pygame
    img = app.big(size).render(ch, True, color)
    w, h = img.get_size()
    box = pygame.Rect(x - 50, y, 100, 106)
    surf.fill(T.SURFACE, box)
    pygame.draw.rect(surf, T.RULE, box, 1)
    surf.blit(img, (x - w // 2, y + (106 - h) // 2))


# ---- home -----------------------------------------------------------------------------

class Home(Menu):
    def __init__(self, app):
        st = app.store
        super().__init__(app, APP_TITLE, [
            ("Learn letters", lambda: app.push(Trainer(app)), lambda: f"{st.learned}/{len(M.KOCH_ORDER)}"),
            ("Copy the code", lambda: app.push(CopyGame(app)), lambda: f"best {st.games['copy_best']}"),
            ("Send the code", lambda: app.push(SendGame(app)), lambda: f"best {st.games['send_best']}"),
            ("Park hunt", lambda: app.push(Hunt(app)), lambda: f"best {st.games['hunt_best']}/3"),
            ("Key and send", lambda: app.push(KeyScreen(app)), lambda: "TX" if app.s["radio"] != "Off" else ""),
            ("CW decoder", lambda: app.push(Decoder(app)), ""),
            ("Progress", lambda: app.push(Progress(app)), lambda: f"{st.today_minutes()} min"),
            ("Settings", lambda: app.push(settings_form(app)), ""),
            ("Paddle and radio", lambda: app.push(Message(app, "Paddle and radio", HARDWARE_HELP)), ""),
            ("About", lambda: app.open_about(), ""),
        ])
        self.help = HELP_MAIN


# ---- learn letters (Koch) --------------------------------------------------------------

class Trainer(Screen):
    title = "Learn letters"
    help = ("The Koch way: you start with K and M. Each new character is played to you first, then you "
            "type each character as you hear it. A new one unlocks when your last 60 answers are 90% "
            "right. SPACE plays it again. Speed is in Settings.")

    def __init__(self, app):
        super().__init__(app)
        self.st = app.store
        self.recent: list[str] = []
        self.cur = None
        self.typed = ""
        self.msg, self.msg_color = "", T.FG
        self.next_at = None
        self.t0 = time.monotonic()
        self.phase = ""
        self.cheer_line = None
        self.start()

    @property
    def text_entry(self):
        return self.phase == "drill"

    @property
    def hint(self):
        if self.phase == "intro":
            return "OK next  SPACE again  ESC done"
        if self.phase == "cheer":
            return "OK meet the new character"
        return TYPE_HINT

    def start(self):
        if self.st.introduced < self.st.learned:
            self.intro(self.st.chars[self.st.introduced])
        else:
            self.drill()

    def intro(self, c):
        self.phase, self.cur = "intro", c
        self.app.play(f"{c} {c} {c}", eff=min(10, float(self.app.s["char_wpm"])))

    def drill(self):
        self.phase = "drill"
        self.cur = self.st.pick(self.recent)
        self.recent = (self.recent + [self.cur])[-3:]
        self.typed = ""
        self.next_at = None
        self.app.play(self.cur)

    def key(self, k):
        if k.name == "esc" or (self.phase != "drill" and k.name in BACK):
            self.app.pop()
            return
        if self.phase == "intro":
            if k.char == " ":
                self.intro(self.cur)
            elif k.name in SELECT:
                self.st.introduced = max(self.st.introduced, M.KOCH_ORDER.index(self.cur) + 1)
                self.st.save()
                self.start()
            return
        if self.phase == "cheer":
            if k.name in SELECT or k.char == " ":
                self.start()
            return
        if self.next_at is not None:
            if k.name in SELECT or k.char == " ":
                self.next_at = time.monotonic()
            return
        if k.char == " ":
            self.app.play(self.cur)
            return
        ch = k.char.upper() if k.char else ""
        if not ch or not (ch.isalnum() or ch in PUNCT):
            return
        self.typed = ch
        new = self.st.answer(self.cur, ch)
        if ch == self.cur:
            self.msg, self.msg_color = "Right!", T.OK
            self.next_at = time.monotonic() + 0.5
        else:
            self.msg = f"It was {self.cur}  {M.sound_out(self.cur)}"
            self.msg_color = T.BAD
            self.next_at = time.monotonic() + 1.8
            self.app.play(self.cur)
        if new:
            self.cheer_line = (new, *cheer(new))
            self.next_at = time.monotonic() + 0.8

    def tick(self):
        if self.next_at is not None and time.monotonic() >= self.next_at and not self.app.player.busy():
            self.next_at = None
            self.msg = ""
            if self.cheer_line:
                self.phase = "cheer"
                self.app.dirty = True
                return
            self.drill()
            self.app.dirty = True

    def rows(self):
        st = self.st
        if self.phase == "intro":
            return [("New character:", T.WARN), (self.cur, T.FG), (M.sound_out(self.cur), T.FG),
                    (M.pretty(M.code_for(self.cur)), T.DIM)], None
        if self.phase == "cheer":
            new, who, line = self.cheer_line
            lines = wrap(self.app.panel, f"{who}: {line}", 300)
            return [(f"You unlocked {new}!", T.OK)] + [(x, T.FG) for x in lines[:3]], None
        chars = " ".join(st.chars)
        if len(chars) > 18:
            chars = "…" + chars[-17:]
        return [("Type what you hear", T.DIM), (self.msg, self.msg_color), "",
                (st.progress_text(), T.FG), (chars, T.DIM)], None

    def paint(self, surf, f):
        if self.phase == "intro":
            big_char(self.app, surf, self.cur, T.AMBER)
        elif self.phase == "drill":
            if self.typed and self.next_at is not None:
                big_char(self.app, surf, self.typed, T.OK if self.typed == self.cur else T.BAD)
            else:
                big_char(self.app, surf, "?", T.DIM)

    def right(self):
        return f"{self.app.s['char_wpm']} WPM"

    def leave(self):
        self.app.player.stop()
        if self.cheer_line and self.phase == "cheer":
            pass
        self.st.add_seconds(time.monotonic() - self.t0)
        self.st.save()


# ---- copy the code ---------------------------------------------------------------------

class CopyGame(Screen):
    title = "Copy the code"
    text_entry = True
    help = ("Messages use only the characters you've learned. Type each character as soon as you hear it. "
            "SPACE hears the message again, once per round. Each round is a little faster. Three misses "
            "and the band closes.")

    def __init__(self, app):
        super().__init__(app)
        self.used: set = set()
        self.new_game()

    def new_game(self):
        self.round, self.score, self.misses = 0, 0, 0
        self.over = False
        self.next_round()

    def next_round(self):
        st = self.app.store
        self.round += 1
        tier = min(4, (self.round - 1) // 2)
        cw = float(self.app.s["char_wpm"])
        self.eff = min(cw, float(self.app.s["eff_wpm"]) + (self.round - 1))
        self.msg = M.practice_message(tier, st.allowed, self.used)
        self.used.add(self.msg)
        self.expect = M.chars_of(self.msg)
        self.pos = 0
        self.typed: list[tuple[str, bool]] = []
        self.replayed = False
        self.note, self.note_color = "", T.FG
        self.done_at = None
        self.app.play(self.msg, eff=self.eff)

    @property
    def hint(self):
        return "OK play again  ESC done" if self.over else TYPE_HINT

    def key(self, k):
        if k.name == "esc":
            self.app.pop()
            return
        if self.over:
            if k.name in SELECT:
                self.new_game()
            return
        if k.char == " ":
            if not self.replayed:
                self.replayed = True
                self.app.play(self.msg, eff=self.eff)
            else:
                self.note, self.note_color = "One replay per round", T.WARN
            return
        ch = k.char.upper() if k.char else ""
        if not ch or not (ch.isalnum() or ch in PUNCT) or self.pos >= len(self.expect):
            return
        want = self.expect[self.pos]
        right = ch == want
        self.typed.append((want if right else ch, right))
        self.pos += 1
        if right:
            self.score += 1
            self.note = ""
        else:
            self.misses += 1
            self.note, self.note_color = f"Missed {want}  {M.pretty(M.code_for(want) or '')}", T.BAD
        if self.misses >= 3:
            self.finish()
        elif self.pos >= len(self.expect):
            self.note, self.note_color = "Round done!", T.OK
            self.done_at = time.monotonic() + 1.2

    def finish(self):
        self.over = True
        self.app.player.stop()
        st = self.app.store
        best = self.score > st.games["copy_best"]
        st.games["copy_best"] = max(st.games["copy_best"], self.score)
        st.save()
        self.note = f"Band closed. {self.score} copied" + (" (new best!)" if best else "")
        self.note_color = T.WARN

    def tick(self):
        if self.done_at and time.monotonic() >= self.done_at:
            self.done_at = None
            self.next_round()
            self.app.dirty = True

    def copy_line(self) -> list:
        """The message so far: copied characters, then underscores."""
        out, i = [], 0
        for tok in M.tokenize(self.msg):
            if not tok.code:
                out.append((" ", T.FG))
                continue
            if i < len(self.typed):
                c, ok = self.typed[i]
                out.append((c if ok else c.lower(), T.OK if ok else T.BAD))
            else:
                out.append(("_", T.DIM))
            i += 1
        return out

    def rows(self):
        dots = "●" * self.misses + "○" * (3 - self.misses)
        line = "".join(c for c, _ in self.copy_line())
        shown = self.msg if self.over or self.pos >= len(self.expect) else ""
        return [(f"Round {self.round}  {self.eff:g} WPM", T.DIM), (line, T.FG), (shown, T.DIM),
                (self.note, self.note_color), (f"Score {self.score}   Misses {dots}", T.FG)], None

    def paint(self, surf, f):
        # colour the copy line character by character
        x, y = 8, T.TITLE_H + 1 + T.ROW_H + 1
        surf.fill(T.BG, (0, y - 1, T.W, T.ROW_H))
        font = f["row"]
        for c, col in self.copy_line():
            img = font.render(c, True, col)
            surf.blit(img, (x, y))
            x += max(img.get_width(), 6) + 1
            if x > T.W - 10:
                break

    def leave(self):
        self.app.player.stop()


# ---- keying (shared by Send the code and Key and send) ----------------------------------

class KeyingScreen(Screen):
    """Holds a keyer with sidetone, the GPIO paddle and keyboard keys, and
    decodes what is keyed."""
    morse_keys = {" ", "j", "k"}
    poll_s = 0.01

    def __init__(self, app, straight_kb=True):
        super().__init__(app)
        s = app.s
        self.keyer = Keyer(float(s["key_wpm"]), s["key_mode"], bool(s["swap"]))
        app.player.sidetone(float(s["tone"]), int(s["volume"]) / 100)
        self.keyer.outputs.append(lambda d: app.player.tone_on() if d else app.player.tone_off())
        self.events: deque = deque()
        self.keyer.listener = lambda d, t: self.events.append((d, t))
        self.paddle = R.Paddle(int(s["dit_pin"]), int(s["dah_pin"]))
        self.keyer.paddle = self.paddle if self.paddle.ok else None
        init_dit = 1200 / float(s["key_wpm"]) if s["key_mode"] != "Straight key" else 100
        self.dec = M.KeyDecoder(initial_dit_ms=init_dit)
        self.keyer.start()

    def key_up(self, k):
        self._kb(k.char, False)

    def _kb(self, ch, down) -> bool:
        if ch == " ":
            self.keyer.kb_press("straight", down)
        elif ch == "j":
            self.keyer.kb_press("dit", down)
        elif ch == "k":
            self.keyer.kb_press("dah", down)
        else:
            return False
        return True

    def drain(self) -> list:
        out = []
        while self.events:
            d, t = self.events.popleft()
            if d:
                out += self.dec.key_down(t)
            else:
                self.dec.key_up(t)
        if not self.dec.is_down:
            out += self.dec.poll(time.monotonic() * 1000)
        return out

    def leave(self):
        self.keyer.stop()
        self.app.player.tone_off()
        self.paddle.close()

    def paddle_text(self) -> str:
        return "GPIO paddle" if self.paddle.ok else "keyboard"


class SendGame(KeyingScreen):
    title = "Send the code"
    help = ("Key the word shown. SPACE is a straight key; J and K are dit and dah paddles; a paddle on the "
            "GPIO pins works too. Leave a short pause between letters. OK checks the word now, Backspace "
            "starts it again. A wrong word costs a miss; three and you're done.")

    def __init__(self, app):
        super().__init__(app)
        self.used: set = set()
        self.new_game()

    def new_game(self):
        self.score, self.misses, self.over = 0, 0, False
        self.note, self.note_color = "", T.FG
        self.next_word()

    def next_word(self):
        st = self.app.store
        tier = min(1, self.score // 4)
        w = ""
        for _ in range(8):
            w = M.practice_message(tier, st.allowed, self.used).split(" ")[0]
            if w not in self.used:
                break
        self.used.add(w)
        self.word = w
        self.got: list = []
        self.dec.reset()
        self.check_at = None

    @property
    def hint(self):
        return "OK play again  ESC done" if self.over else "SPACE key  J/K paddle  OK check  ESC done"

    def key(self, k):
        if self._kb(k.char, True):
            return
        if k.name == "esc":
            self.app.pop()
        elif self.over:
            if k.name in SELECT:
                self.new_game()
        elif k.name == "backspace":
            self.got = []
            self.dec.reset()
        elif k.name in SELECT:
            self.got += self.dec.flush()
            self.check()

    def check(self):
        sent = "".join(c.char for c in self.got)
        if not sent:
            return
        fist = M.analyze_fist(self.got)
        wpm = 1200 / fist.dit if fist else None
        st = self.app.store
        if sent == self.word:
            self.score += 1
            st.sent(True, wpm)
            extra = f"  fist {fist.score}" if fist else ""
            self.note, self.note_color = f"Sent {sent}! {wpm:.0f} WPM{extra}" if wpm else "Sent!", T.OK
        else:
            self.misses += 1
            st.sent(False, None)
            self.note, self.note_color = f"Got {sent.replace('#', '?')}, not {self.word}", T.BAD
        if self.misses >= 3:
            self.over = True
            best = self.score > st.games["send_best"]
            st.games["send_best"] = max(st.games["send_best"], self.score)
            self.note = f"Done: {self.score} words" + (" (new best!)" if best else "")
            self.note_color = T.WARN
        else:
            self.next_word()
        st.save()

    def tick(self):
        new = self.drain()
        if new and not self.over:
            self.got += new
            self.app.dirty = True
        if self.over:
            return
        n = len(self.got)
        if n >= len(self.word) and not self.dec.pending:
            self.check()
            self.app.dirty = True

    def rows(self):
        sent = "".join(c.char for c in self.got).replace("#", "?")
        dots = "●" * self.misses + "○" * (3 - self.misses)
        code = "  ".join(M.pretty(M.code_for(c) or "") for c in self.word) if len(self.word) <= 4 else ""
        return [(f"Send:  {self.word}", T.AMBER), (code, T.DIM), (f"You:  {sent}", T.FG),
                (self.note, self.note_color), (f"Score {self.score}   Misses {dots}", T.FG)], None

    def right(self):
        return self.paddle_text()


class KeyScreen(KeyingScreen):
    title = "Key and send"
    help = ("Key with the GPIO paddle, SPACE (straight key) or J/K (paddles). What you key is decoded "
            "below. Key 4 types a message to send at the keyer speed. Key 5 turns transmit on: only then "
            "is the radio keyed (GPIO key-out, or a QMX over USB). Transmit always starts off and lets go "
            "of a key held over 10 seconds.")

    def __init__(self, app):
        super().__init__(app)
        self.rig = None
        self.status = ""
        self.text = ""
        radio = app.s["radio"]
        if radio == "GPIO key-out":
            k = R.GpioKey(int(app.s["key_pin"]))
            self.rig = k if k.ok else None
            self.status = f"GPIO {app.s['key_pin']} key-out" if k.ok else f"GPIO key-out: {k.error}"[:40]
        elif radio == "QMX over USB":
            path = R.find_rig(app.s["serial"])
            if path:
                r = R.SerialRig(path)
                self.rig = r if r.ok else None
                self.status = f"QMX on {path.split('/')[-1]}" if r.ok else f"{path}: {r.error}"[:40]
            else:
                self.status = "No QMX found on USB"
        else:
            self.status = "Radio off (Settings)"
        self.keyer.radio = self.rig
        self.keyer.tx = False

    def softkeys(self):
        return [("Type", self.type_msg),
                (lambda: "TX on" if self.keyer.tx else "TX off", self.toggle_tx),
                ("WPM-", lambda: self.speed(-1)), ("WPM+", lambda: self.speed(1)),
                ("Stop", self.stop_all)]

    def speed(self, d):
        self.keyer.wpm = max(5, min(40, self.keyer.wpm + d))
        self.app.s["key_wpm"] = int(self.keyer.wpm)
        self.app.store.save()

    def toggle_tx(self):
        if self.keyer.tx:
            self.keyer.tx = False
            self.keyer.cancel_text()
            return
        if not self.rig:
            self.app.push(Message(self.app, "Transmit", f"{self.status}. Pick the radio in Settings and check "
                                  "the cable (Paddle and radio on the home menu).", T.WARN))
            return

        def on():
            self.keyer.tx = True
            self.keyer.stuck = False
        self.app.push(Confirm(self.app, "Transmit", "Key the radio for real? Make sure you're on a CW "
                              "frequency you may use, into an antenna or dummy load.", on, yes="OK transmit"))

    def type_msg(self):
        def send(text):
            text = text.strip().upper()
            if not text:
                return
            self.text += (" " if self.text else "") + "> " + text
            if isinstance(self.rig, R.SerialRig) and self.keyer.tx:
                self.rig.set_speed(int(self.keyer.wpm))
                self.rig.send_text(text)        # the QMX times it and makes its own sidetone
            else:
                self.keyer.send_text(text)      # GPIO key-out when TX is on, sidetone always
        self.app.push(Prompt(self.app, "Send text", "Message", "", send,
                             help_text="Sent at the keyer speed. CQ, call signs, RST and so on."))

    def stop_all(self):
        self.keyer.cancel_text()
        if isinstance(self.rig, R.SerialRig):
            self.rig.stop_text()

    def key(self, k):
        if self._kb(k.char, True):
            return
        if k.name in BACK:
            self.app.pop()
        elif k.name == "backspace":
            self.text = ""

    def tick(self):
        new = self.drain()
        if new:
            for c in new:
                if c.space_before:
                    self.text += " "
                self.text += c.char.replace("#", "?")
            self.text = self.text[-300:]
            self.app.dirty = True
        if self.keyer.stuck:
            self.keyer.stuck = False
            self.keyer.tx = False
            self.app.push(Message(self.app, "Transmit off", "The key was held over 10 seconds, so transmit "
                                  "was switched off.", T.WARN))

    def rows(self):
        lines = wrap(self.app.panel, self.text, 304)[-3:] if self.text else []
        mode = "straight" if self.app.s["key_mode"] == "Straight key" else self.app.s["key_mode"]
        rows = [(self.status, T.DIM), (f"{self.paddle_text()}, {mode}", T.DIM)]
        rows += [(x, T.FG) for x in lines]
        return rows, None

    def right(self):
        return f"{self.keyer.wpm:g} WPM" + ("  TX" if self.keyer.tx else "")

    def paint(self, surf, f):
        if self.keyer.tx:
            surf.fill(T.EDIT_BG, (0, T.TITLE_H - 2, T.W, 2))
        if self.keyer.down:
            import pygame
            pygame.draw.circle(surf, T.BAD if self.keyer.tx else T.AMBER, (306, 42), 7)

    def leave(self):
        super().leave()
        if self.rig:
            self.rig.close()


# ---- CW decoder ------------------------------------------------------------------------

class Decoder(Screen):
    title = "CW decoder"
    help = ("Decodes CW from radio audio. Plug the radio's headphone or line out into the side jack (with a "
            "TRRS cable, into the mic ring), or use a USB sound card, or a QMX's own USB audio. The tone and "
            "the speed are found by themselves. 4 picks the input, 5 locks the tone, 6 clears.")

    def __init__(self, app):
        super().__init__(app)
        self.inputs = D.input_devices()
        cur = app.s["audio_in"]
        self.idx = next((i for i, (_, d) in enumerate(self.inputs) if d == cur), 0)
        self.dec = None
        self.locked = False
        self.last = ""
        self.restart()

    def restart(self):
        if self.dec:
            self.dec.stop()
        dev = self.inputs[self.idx][1]
        self.dec = D.CwDecoder(dev)
        self.dec.start()

    def softkeys(self):
        return [("Input", self.next_input), (lambda: "Locked" if self.locked else "Auto", self.lock),
                ("Clear", lambda: self.dec.clear()), None, None]

    def next_input(self):
        self.idx = (self.idx + 1) % len(self.inputs)
        self.app.s["audio_in"] = self.inputs[self.idx][1]
        self.app.store.save()
        self.restart()

    def lock(self):
        self.locked = not self.locked
        self.dec.fixed_hz = self.dec.tone if self.locked else None

    def tick(self):
        line = self.dec.line()
        if line != self.last:
            self.last = line
        self.app.dirty = True

    def rows(self):
        d = self.dec
        head = f"{d.tone:.0f} Hz   {d.wpm:.0f} WPM" if d.running else (d.error or "Not running")[:34]
        lines = wrap(self.app.panel, self.last, 304)[-3:] if self.last else [("Listening…", T.DIM)]
        return [(head, T.DIM if d.running else T.BAD), (self.inputs[self.idx][0], T.DIM)] + \
            [x if isinstance(x, tuple) else (x, T.FG) for x in lines], None

    def paint(self, surf, f):
        d = self.dec
        x0, y0, w, h = 214, T.TITLE_H + 5, 96, 10
        surf.fill(T.SURFACE, (x0, y0, w, h))
        lv = max(0.0, min(1.0, d.level))
        surf.fill(T.OK if d.key else T.AMBER, (x0, y0, int(w * lv), h))

    def leave(self):
        if self.dec:
            self.dec.stop()


# ---- park hunt -------------------------------------------------------------------------

BANDS = ["80 m", "40 m", "20 m", "15 m", "10 m"]
STATES = ["MN", "WI", "IA", "ND", "SD", "MT", "WY", "CO", "UT", "AZ", "NM", "TX", "OK", "KS", "NE", "MO", "AR",
          "LA", "MS", "AL", "TN", "KY", "IL", "IN", "OH", "MI", "PA", "NY", "VT", "NH", "ME", "MA", "CT", "NJ",
          "DE", "MD", "VA", "WV", "NC", "SC", "GA", "FL", "WA", "OR", "ID", "NV", "CA"]


def open_bands(hour: int, miles: int) -> set:
    """A simple rule of thumb (what askelmer teaches): daytime favours 20, 15
    and 10 m for long paths and 40 m for short ones; night favours 80 and 40."""
    if 8 <= hour <= 17:
        return {"40 m", "20 m"} if miles < 700 else {"20 m", "15 m", "10 m"}
    if 18 <= hour <= 21:
        return {"40 m", "20 m"}
    return {"80 m", "40 m"}


def clock(h: int) -> str:
    return f"{(h - 1) % 12 + 1} {'AM' if h < 12 else 'PM'}"


class Hunt(Screen):
    title = "Park hunt"
    help = ("Three park activators are calling CQ POTA. Read the clue and pick a band that's open for that "
            "time and distance, then copy the activator's call, and their report and state. SPACE hears "
            "it again. Built from the characters you've learned, once you know a digit; before that, all "
            "characters are used.")

    def __init__(self, app):
        super().__init__(app)
        self.rng = random.Random()
        st = app.store
        self.allowed = st.allowed if any(c.isdigit() for c in st.allowed) and len(st.allowed) >= 12 else \
            set(M.KOCH_ORDER)
        self.mine = (app.s.get("call") or "N0CALL").upper()
        self.park_no, self.logged, self.replays = 0, 0, 0
        self.next_park()

    def next_park(self):
        r = self.rng
        self.park_no += 1
        if self.park_no > 3:
            self.finish()
            return
        night = self.park_no == 3
        self.hour = r.choice([21, 22, 23, 0, 1]) if night else r.choice([10, 11, 13, 14, 15, 16])
        self.miles = r.choice([350, 500, 900, 1200, 1500, 2000])
        self.band_i = 2
        self.park = f"US-{r.randint(1000, 9999)}"
        self.call = M.make_call(r, self.allowed) or "K0ABC"
        states = [s for s in STATES if all(c in self.allowed for c in s)] or STATES
        self.state = r.choice(states)
        rst_digit = r.choice([9, 9, 7, 5])
        self.rst = f"5{rst_digit}9"
        self.rst_sent = "".join(M.CUT.get(c, c) if c not in self.allowed else c for c in self.rst)
        self.phase = "band"
        self.buf = ""
        self.tries = 0
        self.note, self.note_color = "", T.FG

    @property
    def text_entry(self):
        return self.phase in ("call", "exchange")

    @property
    def hint(self):
        if self.phase == "band":
            return "↑↓ band  OK listen  ESC done"
        if self.phase in ("call", "exchange"):
            return "Type, OK log it  SPACE again  ESC done"
        return "OK next  ESC done"

    def quality(self):
        return 0.6 + 0.4 * self.rng.random()

    def play_cq(self):
        text = f"CQ POTA DE {self.call} {self.call} K"
        self.play_signal(text)

    def play_exchange(self):
        text = f"{self.mine} TU UR {self.rst_sent} {self.rst_sent} {self.state} {self.state} BK"
        self.play_signal(text)

    def play_signal(self, text):
        q = self.qual
        qrm_text = M.practice_message(1, self.allowed, rng=self.rng)
        tone = float(self.app.s["tone"])
        self.app.play(text, eff=None, noise=0.25 * (1.2 - q), qsb=0.35 * (1 - q) + 0.1,
                      qrm=[(qrm_text, tone + self.rng.choice([-450, 380, 520]), 0.35, 18)], seed=self.rng.randint(1, 999))

    def key(self, k):
        if k.name == "esc" or (not self.text_entry and k.name in BACK):
            self.app.pop()
            return
        if self.phase == "band":
            if k.name in UP:
                self.band_i = (self.band_i - 1) % len(BANDS)
            elif k.name in DOWN:
                self.band_i = (self.band_i + 1) % len(BANDS)
            elif k.name in SELECT:
                self.pick_band()
            return
        if self.phase in ("logged", "over"):
            if k.name in SELECT:
                if self.phase == "over":
                    self.__init__(self.app)
                else:
                    self.next_park()
            return
        if k.char == " ":
            self.replays += 1
            self.play_cq() if self.phase == "call" else self.play_exchange()
        elif k.name == "backspace":
            self.buf = self.buf[:-1]
        elif k.name == "enter":
            self.submit()
        elif k.char and (k.char.isalnum() or k.char in "/"):
            if len(self.buf) < 14:
                self.buf += k.char.upper()
        elif k.char == "-":
            pass

    def pick_band(self):
        band = BANDS[self.band_i]
        good = open_bands(self.hour, self.miles)
        if band in good:
            self.band = band
            self.qual = self.quality()
            self.phase = "call"
            self.note, self.note_color = f"Someone's calling on {band}…", T.OK
            self.play_cq()
        else:
            self.tries += 1
            self.app.player.play(A.render("E", M.timing(20), volume=0.0, noise=0.6, lead_ms=1200))
            why = "nights favour 80 and 40 m" if not 8 <= self.hour <= 21 else \
                ("short daytime hops favour 40 m" if self.miles < 700 else "long daytime paths favour 20-10 m")
            self.note, self.note_color = f"{band}: only static. {why.capitalize()}.", T.BAD

    def submit(self):
        if self.phase == "call":
            if self.buf == self.call:
                self.phase, self.buf = "exchange", ""
                self.note, self.note_color = f"You answered. {self.call} replies…", T.OK
                self.play_exchange()
            else:
                self.tries += 1
                self.note, self.note_color = ("Not quite. Listen again." if self.tries < 4 else
                                              f"It was {self.call}."), T.BAD
                if self.tries >= 4:
                    self.phase, self.buf = "exchange", ""
                    self.play_exchange()
                self.buf = "" if self.tries < 4 else self.buf
        elif self.phase == "exchange":
            parts = self.buf.replace("/", " ").split()
            ok_rst = any(M.normalize_rst(p) == self.rst for p in parts)
            ok_st = self.state in parts or self.buf.endswith(self.state)
            if ok_rst and ok_st:
                self.logged += 1
                self.phase = "logged"
                self.app.player.stop()
                self.note, self.note_color = f"Logged {self.call} at {self.park}, {self.rst} {self.state}", T.OK
            else:
                self.tries += 1
                if self.tries >= 6:
                    self.phase = "logged"
                    self.note, self.note_color = f"It was {self.rst_sent} from {self.state}. Not logged.", T.BAD
                else:
                    self.note, self.note_color = "Report and state, like 5NN MN. Listen again.", T.BAD
                    self.buf = ""

    def finish(self):
        self.phase = "over"
        st = self.app.store
        st.games["hunt_best"] = max(st.games["hunt_best"], self.logged)
        st.save()
        self.note, self.note_color = f"Hunt over: {self.logged} of 3 parks logged, {self.replays} replays", T.WARN

    def rows(self):
        if self.phase == "over":
            return [("73!", T.OK), (self.note, self.note_color), "", ("OK hunt again", T.DIM)], None
        head = (f"Park {self.park_no} of 3:  {clock(self.hour)},  {self.miles:,} miles", T.DIM)
        if self.phase == "band":
            return [head, ("Which band is open?", T.FG), (f"◀  {BANDS[self.band_i]}  ▶", T.AMBER),
                    (self.note, self.note_color)], None
        ask = "Their call:" if self.phase == "call" else "RST and state:"
        if self.phase == "logged":
            return [head, (self.note, self.note_color), "", ("OK next park", T.DIM)], None
        return [head, (self.note, self.note_color), (f"{ask}  {self.buf}_", T.FG)], None

    def right(self):
        return f"{self.logged} logged"

    def leave(self):
        self.app.player.stop()


# ---- progress, settings, hardware --------------------------------------------------------

class Progress(Menu):
    def __init__(self, app):
        self.app = app
        st = app.store
        rows = []
        cells = []
        for c in st.chars:
            a = st.char_acc(c)
            cells.append(f"{c} {round(100 * a) if a is not None else '--'}")
        for i in range(0, len(cells), 4):
            rows.append(("   ".join(cells[i:i + 4]), None, ""))
        send = st.send["results"]
        sp = st.send["wpm"]
        items = [
            (f"Learned {st.learned} of {len(M.KOCH_ORDER)}", None, f"next {st.next_char or '-'}"),
            (st.progress_text(), None, ""),
            ("Today", None, f"{st.today_minutes()} min"),
            ("Best run", None, str(st.totals["best_run"])),
        ]
        if st.trouble:
            items.append(("Needs work: " + " ".join(st.trouble), None, ""))
        if send:
            items.append(("Sending", None, f"{round(100 * sum(send) / len(send))}%"
                          + (f", {sum(sp) / len(sp):.0f} WPM" if sp else "")))
        items += rows
        items += [("[ I know them all: unlock all ]", self.unlock_all, ""),
                  ("[ Start the trainer over ]", self.reset, "")]
        super().__init__(app, "Progress", items)

    def unlock_all(self):
        self.app.push(Confirm(self.app, "Unlock all", "Unlock every character now? Use this if you already "
                              "know Morse.", lambda: (self.app.store.unlock_all(), self.app.pop(self))))

    def reset(self):
        self.app.push(Confirm(self.app, "Start over", "Start the trainer over from K and M? Settings and "
                              "game bests are kept.", lambda: (self.app.store.reset(), self.app.pop(self))))


def settings_form(app):
    s = app.s
    devices = [d for _, d in D.input_devices()]
    if s["audio_in"] not in devices:
        devices.append(s["audio_in"])
    fields = [
        ("", "Speed and sound", "header"),
        ("char_wpm", "Character WPM", "choice", [str(x) for x in CHAR_SPEEDS]),
        ("eff_wpm", "Overall WPM", "choice", [str(x) for x in (5, 6, 8, 10, 12, 15, 18, 20, 25)]),
        ("tone", "Tone Hz", "choice", [str(x) for x in range(400, 951, 50)]),
        ("volume", "Volume %", "choice", [str(x) for x in (20, 40, 60, 80, 100)]),
        ("", "Keying", "header"),
        ("key_wpm", "Keyer WPM", "choice", [str(x) for x in range(8, 41, 2)]),
        ("key_mode", "Paddle", "choice", ["Iambic B", "Iambic A", "Straight key"]),
        ("swap", "Swap paddles", "bool", ("Yes", "No")),
        ("call", "My call", "text", "Your call sign, for the park hunt"),
        ("", "Radio", "header"),
        ("radio", "Radio", "choice", ["Off", "GPIO key-out", "QMX over USB"]),
        ("key_pin", "Key-out GPIO", "choice", ["23", "2", "3", "14", "15"], lambda v: v["radio"] == "GPIO key-out"),
        ("serial", "USB port", "text", "auto, or e.g. /dev/ttyACM0", lambda v: v["radio"] == "QMX over USB"),
        ("audio_in", "Decoder in", "choice", devices),
    ]
    values = {k: (str(v) if k not in ("swap",) else v) for k, v in s.items()}

    def save(v):
        for k in ("char_wpm", "eff_wpm", "tone", "volume", "key_wpm", "key_pin"):
            s[k] = int(v[k])
        for k in ("key_mode", "radio", "serial", "audio_in"):
            s[k] = v[k] or s[k]
        s["swap"] = bool(v["swap"])
        s["call"] = (v["call"] or "").upper().strip()
        app.store.save()

    return Form(app, "Settings", fields, values, save)


HARDWARE_HELP = """Paddle: a 3.5 mm stereo jack wired to the EXT header. Tip = dit to GPIO22 (pin 5), ring = dah to GPIO26 (pin 1), sleeve = GND (pin 4). No resistors needed: the app turns on the pull-ups. A straight key goes tip to sleeve.
Key-out (GPIO): GPIO23 (pin 3) through 330 ohm to the LED of a PC817 optocoupler, LED cathode to GND. The transistor's collector and emitter go to the radio's key jack tip and sleeve. The radio never touches the Cardputer.
QMX over USB: one USB cable. In the QMX's CAT/USB settings, connect the CW keyer to DTR. Typed text goes out with the KY command; the paddle keys DTR live.
Decoder: the radio's headphone or line out into the side jack's mic ring (TRRS), through a 10:1 resistor divider; or a USB sound card; or the QMX's own USB audio.
Transmit is always off until you turn it on with key 5 on the Key and send screen."""


def main_ui() -> int:
    panel = L.Panel()
    kb = Keyboard()
    try:
        App(panel, kb if kb.ok else None).run()
    finally:
        kb.close()
    return 0
