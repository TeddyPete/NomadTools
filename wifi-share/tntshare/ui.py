"""Screens for the 320x170 LCD, driven by the keyboard.

Every screen returns rows to draw and handles keys. The App keeps a stack
of screens; long network jobs run in a worker thread behind a Busy screen
so the display keeps updating.
"""
from __future__ import annotations

import threading
import time

from . import lcd as L
from .keys import Key

# TNT key standard (all TNT apps): Up/Down move the highlight, OK (Enter) or
# Right selects, Left backs out one level, Esc backs out (quits on the main
# page). On the CardputerZero the arrows are Fn+F/X/Z/C.
UP = {"up"}
DOWN = {"down"}
SELECT = {"enter", "right"}
BACK = {"esc", "left"}

# Outside text fields the bare arrow-legend keys also navigate (Ted's request).
NAV_LETTERS = {"f": "up", "x": "down", "z": "left", "c": "right"}


def nav_key(k: Key) -> Key:
    """Turn plain F/X/Z/C into Up/Down/Left/Right (not used in text fields)."""
    if k.char and not k.ctrl and k.char.lower() in NAV_LETTERS:
        return Key(NAV_LETTERS[k.char.lower()])
    return k


HINT_MENU = "\u2191\u2193 move  OK/\u2192 open  \u2190/ESC back"


class Screen:
    title = ""
    text_entry = False  # True: letters type text, F/X/Z/C don't navigate
    hint = "\u2190/ESC back"

    def __init__(self, app):
        self.app = app

    def rows(self) -> tuple[list, int | None]:
        return [], None

    def right(self) -> str:
        return self.app.mode_badge()

    def key(self, k: Key) -> None:
        if k.name in BACK:
            self.app.pop()

    def tick(self) -> None:
        pass


class Menu(Screen):
    """A list of items: (label, action, right_text_or_callable)."""

    def __init__(self, app, title: str, items: list, hint: str = HINT_MENU, numbered=False):
        super().__init__(app)
        self.title, self.items, self.hint, self.numbered = title, items, hint, numbered
        self.sel = 0
        self.top = 0

    def labels(self):
        out = []
        for i, it in enumerate(self.items):
            label = it[0]() if callable(it[0]) else it[0]
            right = it[2] if len(it) > 2 else ""
            r = right() if callable(right) else right
            color = it[3] if len(it) > 3 else L.FG
            color = color() if callable(color) else color
            text = f"{i + 1} {label}" if self.numbered and i < 9 else label
            out.append((text, color, r or ""))
        return out

    def rows(self):
        rows = self.labels()
        n = L.Panel.ROWS
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + n:
            self.top = self.sel - n + 1
        return rows[self.top:self.top + n], self.sel - self.top

    def key(self, k):
        if not self.items:
            return super().key(k)
        if k.name in UP:
            self.sel = (self.sel - 1) % len(self.items)
        elif k.name in DOWN:
            self.sel = (self.sel + 1) % len(self.items)
        elif k.name == "pageup":
            self.sel = max(0, self.sel - L.Panel.ROWS)
        elif k.name == "pagedown":
            self.sel = min(len(self.items) - 1, self.sel + L.Panel.ROWS)
        elif k.name in SELECT:
            act = self.items[self.sel][1]
            if act:
                act()
        elif self.numbered and k.char.isdigit() and k.char != "0" and int(k.char) <= len(self.items):
            self.sel = int(k.char) - 1
            act = self.items[self.sel][1]
            if act:
                act()
        else:
            super().key(k)


class Message(Screen):
    def __init__(self, app, title: str, text: str, color=L.FG, then=None):
        super().__init__(app)
        self.title, self.color, self.then = title, color, then
        self.lines = wrap(app.panel, text)
        self.top = 0
        self.hint = "OK close" + ("  \u2191\u2193 scroll" if len(self.lines) > L.Panel.ROWS else "")

    def rows(self):
        return [(l, self.color) for l in self.lines[self.top:self.top + L.Panel.ROWS]], None

    def key(self, k):
        if k.name in UP:
            self.top = max(0, self.top - 1)
        elif k.name in DOWN:
            self.top = min(max(0, len(self.lines) - L.Panel.ROWS), self.top + 1)
        elif k.name in SELECT | BACK or k.char == " ":
            self.app.pop()
            if self.then:
                self.then()


class Confirm(Screen):
    def __init__(self, app, title: str, text: str, on_yes, yes="OK yes", no="ESC no"):
        super().__init__(app)
        self.title, self.on_yes = title, on_yes
        self.lines = wrap(app.panel, text)
        self.hint = f"{yes}   {no}"

    def rows(self):
        return self.lines, None

    def key(self, k):
        if k.name in SELECT or k.char in ("y", "Y"):
            self.app.pop()
            self.on_yes()
        elif k.name in BACK or k.char in ("n", "N"):
            self.app.pop()


class TextInput(Screen):
    text_entry = True
    """One-line text entry. OK saves, ESC cancels, Left/Right move the cursor
    (Left at the start of the line backs out, like a menu), DEL deletes."""

    def __init__(self, app, title: str, prompt: str, value: str, on_done, secret=False, help_text=""):
        super().__init__(app)
        self.title, self.prompt, self.value, self.on_done = title, prompt, value, on_done
        self.secret = secret
        self.help = help_text
        self.pos = len(value)
        self.hint = "OK save  ESC cancel" + ("  Tab show" if secret else "")

    def rows(self):
        shown = "*" * len(self.value) if self.secret else self.value
        on = int(time.monotonic() * 2) % 2 == 0
        line = shown[:self.pos] + ("|" if on else " ") + shown[self.pos:]
        # keep the cursor visible on long values
        start = 0
        while self.app.panel.text_width(line[start:self.pos + 1]) > 300 and start < self.pos:
            start += 1
        rows = [(self.prompt, L.DIM), (line[start:], L.WARN), ""]
        rows += [(l, L.DIM) for l in wrap(self.app.panel, self.help)][:3]
        return rows, None

    def tick(self):
        self.app.dirty = True

    def key(self, k):
        if k.name == "esc":
            self.app.pop()
        elif k.name == "enter":
            self.app.pop()
            self.on_done(self.value)
        elif k.name == "left":
            if self.pos == 0 and not self.value:
                self.app.pop()
            self.pos = max(0, self.pos - 1)
        elif k.name == "right":
            self.pos = min(len(self.value), self.pos + 1)
        elif k.name == "home":
            self.pos = 0
        elif k.name == "end":
            self.pos = len(self.value)
        elif k.name == "backspace":
            if self.pos:
                self.value = self.value[:self.pos - 1] + self.value[self.pos:]
                self.pos -= 1
        elif k.name == "delete":
            self.value = self.value[:self.pos] + self.value[self.pos + 1:]
        elif k.name == "tab" and self.secret is not None:
            self.secret = not self.secret
        elif k.ctrl and k.char in ("u", "U"):
            self.value, self.pos = "", 0
        elif k.char and not k.ctrl and len(self.value) < 128:
            self.value = self.value[:self.pos] + k.char + self.value[self.pos:]
            self.pos += 1


class Busy(Screen):
    """Runs fn() in a thread; then calls done(result, error)."""
    hint = "Working..."

    def __init__(self, app, title: str, label: str, fn, done):
        super().__init__(app)
        self.title, self.label, self.fn, self.done = title, label, fn, done
        self.result = self.error = None
        self.finished = False
        self.t0 = time.monotonic()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.result = self.fn()
        except Exception as e:  # shown to the user, never crashes the UI
            self.error = e
        self.finished = True
        self.app.wake()

    def rows(self):
        dots = "." * (1 + int(time.monotonic() - self.t0) % 4)
        return [(self.label + dots, L.WARN), "", (f"{int(time.monotonic() - self.t0)} s", L.DIM)], None

    def tick(self):
        self.app.dirty = True
        if self.finished:
            self.app.pop(self)
            self.done(self.result, self.error)

    def key(self, k):
        pass  # can't cancel a network change half way


class Form(Screen):
    """Edit a set of settings. fields: (key, label, kind[, choices]) where kind
    is text | ip | mask | secret | bool | choice | header."""

    def __init__(self, app, title: str, fields: list, values: dict, on_save, validate=None):
        super().__init__(app)
        self.title, self.fields, self.on_save, self.validate = title, fields, on_save, validate
        self.values = dict(values)
        self.orig = dict(values)
        self.items = [f for f in fields]
        self.items.append(("__save", "Save", "action"))
        self.sel = next(i for i, f in enumerate(self.items) if f[2] != "header")
        self.top = 0
        self.hint = "OK/\u2192 change  \u2190/ESC back"

    def visible(self, f) -> bool:
        cond = f[4] if len(f) > 4 else None
        return cond is None or cond(self.values)

    def shown_items(self):
        return [f for f in self.items if self.visible(f)]

    def fmt(self, f) -> str:
        key, kind = f[0], f[2]
        v = self.values.get(key)
        if kind == "bool":
            names = f[3] if len(f) > 3 and isinstance(f[3], tuple) else ("On", "Off")
            return names[0] if v else names[1]
        if kind == "header" or kind == "action":
            return ""
        return str(v)

    def rows(self):
        items = self.shown_items()
        self.sel = min(self.sel, len(items) - 1)
        rows = []
        for f in items:
            if f[2] == "header":
                rows.append((f[1], L.WARN))
            elif f[2] == "action":
                rows.append(("[ Save ]", L.OK))
            else:
                rows.append(("  " + f[1], L.FG, self.fmt(f)))
        n = L.Panel.ROWS
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + n:
            self.top = self.sel - n + 1
        return rows[self.top:self.top + n], self.sel - self.top

    def _move(self, d):
        items = self.shown_items()
        for _ in range(len(items)):
            self.sel = (self.sel + d) % len(items)
            if items[self.sel][2] != "header":
                break

    def save(self):
        err = self.validate(self.values) if self.validate else None
        if err:
            self.app.push(Message(self.app, "Check settings", err, L.BAD))
            return
        self.app.pop(self)
        self.on_save(self.values)

    def key(self, k):
        items = self.shown_items()
        f = items[self.sel]
        if k.name in UP:
            self._move(-1)
        elif k.name in DOWN:
            self._move(1)
        elif k.char in ("s", "S") and k.ctrl is False and f[2] in ("bool", "choice", "action", "header"):
            self.save()
        elif k.name in SELECT or (k.char == " " and f[2] in ("bool", "choice")):
            kind = f[2]
            if kind == "action":
                self.save()
            elif kind == "bool":
                self.values[f[0]] = not self.values[f[0]]
            elif kind == "choice":
                ch = f[3]
                cur = str(self.values[f[0]])
                self.values[f[0]] = ch[(ch.index(cur) + 1) % len(ch)] if cur in ch else ch[0]
            elif kind != "header":
                def done(v, key=f[0]):
                    self.values[key] = v.strip() if f[2] != "secret" else v
                self.app.push(TextInput(self.app, self.title, f[1], str(self.values[f[0]]), done,
                                        secret=False if f[2] == "secret" else None,
                                        help_text=f[3] if len(f) > 3 and isinstance(f[3], str) else ""))
        elif k.name in BACK:
            if self.values != self.orig:
                self.app.push(Confirm(self.app, "Unsaved changes", "Save your changes?",
                                      self.save, yes="OK save", no="ESC discard"))
                # Esc on the confirm discards: pop this form too
                conf = self.app.stack[-1]
                orig_key = conf.key

                def k2(kk, conf=conf, orig_key=orig_key):
                    if kk.name in BACK or kk.char in ("n", "N"):
                        self.app.pop(conf)
                        self.app.pop(self)
                    else:
                        orig_key(kk)
                conf.key = k2
            else:
                self.app.pop(self)


def wrap(panel, text: str, width: int = 304) -> list[str]:
    out = []
    for para in str(text).split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            trial = f"{cur} {w}" if cur else w
            if cur and panel.text_width(trial) > width:
                out.append(cur)
                cur = w
            else:
                cur = trial
        out.append(cur)
    return out
