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

# Nomad key standard and look live in nomadui.py (shared by all Nomad apps).
from .nomadui import BACK, DOWN, HINT_MENU, NAV_LETTERS, SELECT, UP, EditList, Field, nav_name  # noqa: E402,F401
from . import nomadui as T  # noqa: E402


def nav_key(k: Key) -> Key:
    """Turn plain F/X/Z/C into Up/Down/Left/Right (not used while typing)."""
    n = nav_name(k.name, k.char, k.ctrl)
    return k if n == k.name else Key(n)


class Screen:
    title = ""
    text_entry = False  # True: letters type text, F/X/Z/C don't navigate
    hint = "\u2190/ESC back"
    help = ""           # Fn+H text for this screen (the standard key list is added)

    def __init__(self, app):
        self.app = app

    def softkeys(self) -> list:
        """Actions on number keys 4..8: up to 5 (label, fn) or None. Their
        labels are drawn at the bottom of the screen (official key spec)."""
        return []

    def keybar(self) -> list | None:
        sk = self.softkeys()
        if not sk or not any(sk):
            return None
        return [(s[0]() if callable(s[0]) else s[0]) if s else None for s in sk]

    @property
    def nrows(self) -> int:
        return T.ROWS_KEYS if self.keybar() else T.ROWS

    def soft(self, k) -> bool:
        """Run the action for number key 4..8. True when the key was used."""
        i = T.soft_index(k.char)
        if i is None or k.ctrl:
            return False
        sk = self.softkeys()
        if i < len(sk) and sk[i] and sk[i][1]:
            sk[i][1]()
            return True
        return False

    def rows(self) -> tuple[list, int | None]:
        return [], None

    def right(self) -> str:
        return ""

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
        n = self.nrows
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
            self.sel = max(0, self.sel - self.nrows)
        elif k.name == "pagedown":
            self.sel = min(len(self.items) - 1, self.sel + self.nrows)
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
        self.hint = "OK close" + ("  \u2191\u2193 scroll" if len(self.lines) > self.nrows else "")

    def rows(self):
        return [(l, self.color) for l in self.lines[self.top:self.top + self.nrows]], None

    def key(self, k):
        if k.name in UP:
            self.top = max(0, self.top - 1)
        elif k.name in DOWN:
            self.top = min(max(0, len(self.lines) - self.nrows), self.top + 1)
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


class Prompt(Screen):
    """Ask for one value. The field starts in edit mode (red): type, OK saves
    and calls on_done(value), ESC cancels."""

    def __init__(self, app, title: str, label: str, value: str, on_done, secret=False, help_text=""):
        super().__init__(app)
        self.title, self.on_done, self.help = title, on_done, help_text
        self.form = EditList([Field("v", label, "secret" if secret else "text", help=help_text, maxlen=128)],
                             {"v": value})
        self.form.start_edit()

    @property
    def text_entry(self):
        return self.form.editing

    @property
    def hint(self):
        return self.form.hint() if self.form.editing else "OK/→ edit  ESC back"

    def rows(self):
        rows = list(self.form.view())
        rows += [""] + [(l, L.DIM) for l in wrap(self.app.panel, self.help)][:3]
        return rows, None

    def key(self, k):
        ev = self.form.handle(k)
        if ev == "changed:v":
            self.app.pop(self)
            self.on_done(self.form.values["v"])
        elif ev in ("cancel:v", "back"):
            self.app.pop(self)


TextInput = Prompt  # old name


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
    """Settings list edited in place (Nomad standard, see nomadui.py).
    fields: (key, label, kind[, extra[, visible_cond]]) where kind is
    text | ip | mask | secret | bool | choice | header; extra is the help
    text, the choice list, or the (on, off) names for a bool."""

    def __init__(self, app, title: str, fields: list, values: dict, on_save, validate=None):
        super().__init__(app)
        self.title, self.on_save, self.validate = title, on_save, validate
        conv = []
        for f in fields:
            key, label, kind = f[0], f[1], f[2]
            extra = f[3] if len(f) > 3 else None
            cond = f[4] if len(f) > 4 else None
            conv.append(Field(key or f"_h{len(conv)}", label, kind,
                              choices=extra if isinstance(extra, (list, tuple)) else (),
                              help=extra if isinstance(extra, str) else "", visible=cond))
        conv.append(Field("__save", "Save", "action"))
        self.form = EditList(conv, values)

    @property
    def values(self):
        return self.form.values

    @property
    def text_entry(self):
        return self.form.editing

    @property
    def hint(self):
        return self.form.hint()

    def rows(self):
        return self.form.view(), None

    def save(self):
        err = self.validate(self.values) if self.validate else None
        if err:
            self.app.push(Message(self.app, "Check settings", err, L.BAD))
            return
        self.app.pop(self)
        self.on_save(self.values)

    def key(self, k):
        ev = self.form.handle(k)
        if ev == "action:__save":
            self.save()
        elif ev == "back":
            if self.form.changed:
                conf = Confirm(self.app, "Unsaved changes", "Save your changes?",
                               self.save, yes="OK save", no="ESC discard")
                orig_key = conf.key

                def k2(kk, conf=conf, orig_key=orig_key):
                    if kk.name in BACK or kk.char in ("n", "N"):
                        self.app.pop(conf)
                        self.app.pop(self)
                    else:
                        orig_key(kk)
                conf.key = k2
                self.app.push(conf)
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
