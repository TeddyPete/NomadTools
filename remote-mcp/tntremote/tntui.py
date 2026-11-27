"""TNT UI standard for CardputerZero apps (one file, copy it into any TNT app).

What every TNT app does on the 320x170 screen:

  * Title bar is green, the highlighted row is blue, a field being edited is red.
  * Menus:   Up/Down move (plain F / X work too, no Fn needed).
             OK (Enter) or Right selects.  Left or ESC goes back one level;
             ESC on the main page quits.  (Plain Z / C = Left / Right.)
  * Fields:  OK or Right on a text field starts editing it right there and the
             row turns red.  While editing every key types (F/X/Z/C are just
             letters), Fn+Left/Right move the cursor, DEL deletes, OK saves and
             goes back to the menu, ESC cancels the edit.
             On On/Off and choice fields OK or Right just flips the value.

The only dependency is pygame, and only for render(). Key handling works
with any key object that has .name and .char (and optionally .ctrl), where
.name is "up", "down", "left", "right", "enter", "esc", "backspace",
"delete", "home", "end", "tab", "pageup", "pagedown" or the typed character.

Use it like this:

    form = EditList([Field("ssid", "Name"), Field("pw", "Password", "secret"),
                     Field("save", "Save", "action")], {"ssid": "", "pw": ""})
    ev = form.handle(key)        # "back", "action:save", "changed:ssid" or None
    tntui.render(surface, fonts, "Hotspot", form.view(6), form.hint())
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, Callable

# ---- colors (RGB) -----------------------------------------------------------
# No published CardputerZero/APPLaunch color standard exists, so this is the
# TNT scheme Ted picked: green title, blue highlight, red while editing.
BG = (8, 10, 16)
FG = (235, 235, 235)
DIM = (145, 155, 170)
TITLE_BG = (18, 120, 52)      # green title bar
TITLE_FG = (255, 255, 255)
TITLE_RIGHT = (210, 255, 215)
SEL_BG = (30, 90, 200)        # blue highlight
EDIT_BG = (190, 28, 28)       # red while editing
EDIT_FIELD = (90, 8, 8)       # darker red box behind the text being typed
OK = (110, 220, 120)
WARN = (255, 200, 90)
BAD = (255, 110, 100)
HINT_BG = (24, 28, 40)
HINT_FG = (150, 200, 255)

# ---- layout (320x170) -----------------------------------------------------------
W, H = 320, 170
TITLE_H, ROW_H, HINT_H = 26, 20, 19
ROWS = (H - TITLE_H - HINT_H - 2) // ROW_H     # 6 rows of 17 px bold text
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
FONT_SIZES = {"title": 19, "row": 17, "small": 14}

# ---- keys -----------------------------------------------------------------------
UP, DOWN = {"up"}, {"down"}
SELECT = {"enter", "right"}
BACK = {"esc", "left"}
# Plain letters printed under the arrows on the CardputerZero keycaps.
NAV_LETTERS = {"f": "up", "x": "down", "z": "left", "c": "right"}

HINT_MENU = "↑↓ move  OK/→ open  ←/ESC back"
HINT_FORM = "↑↓ move  OK/→ edit  ESC back"
HINT_EDIT = "OK save  ESC cancel"


def nav_name(name: str, char: str = "", ctrl: bool = False) -> str:
    """Key name for menus: plain F/X/Z/C become up/down/left/right."""
    if char and not ctrl and char.lower() in NAV_LETTERS:
        return NAV_LETTERS[char.lower()]
    return name


def _k(key) -> tuple[str, str, bool]:
    return key.name, getattr(key, "char", "") or "", bool(getattr(key, "ctrl", False))


# ---- editable list ------------------------------------------------------------------

@dataclass
class Field:
    """One row. kind: text | ip | mask | secret | number | bool | choice | header | action."""
    key: str
    label: str
    kind: str = "text"
    choices: list | tuple = ()          # choice: values; bool: (on_name, off_name)
    help: str = ""                      # shown in the hint bar while editing
    visible: Callable[[dict], bool] | None = None
    maxlen: int = 64
    color: Any = None                   # label color override

    @property
    def editable(self) -> bool:
        return self.kind in ("text", "ip", "mask", "secret", "number")

    @property
    def selectable(self) -> bool:
        return self.kind != "header"


ALLOWED = {"ip": set("0123456789."), "mask": set("0123456789./"), "number": set("0123456789")}


@dataclass
class RowView:
    label: str
    value: str = ""
    state: str = "normal"       # normal | selected | editing | header
    color: Any = None
    cursor: int | None = None   # cursor position in value while editing


@dataclass
class EditList:
    fields: list
    values: dict
    sel: int = 0
    top: int = 0
    editing: bool = False
    buf: str = ""
    pos: int = 0
    orig: dict = _field(default_factory=dict)

    def __post_init__(self):
        self.values = dict(self.values)
        self.orig = dict(self.values)
        items = self.shown()
        self.sel = next((i for i, f in enumerate(items) if f.selectable), 0)

    # -- state --
    def shown(self) -> list:
        return [f for f in self.fields if f.visible is None or f.visible(self.values)]

    @property
    def current(self) -> Field | None:
        items = self.shown()
        if not items:
            return None
        self.sel = max(0, min(self.sel, len(items) - 1))
        return items[self.sel]

    @property
    def changed(self) -> bool:
        return self.values != self.orig

    def select(self, key: str) -> None:
        for i, f in enumerate(self.shown()):
            if f.key == key:
                self.sel = i

    def start_edit(self) -> None:
        f = self.current
        if f and f.editable:
            self.editing = True
            self.buf = str(self.values.get(f.key, ""))
            self.pos = len(self.buf)

    def _move(self, d: int) -> None:
        items = self.shown()
        for _ in range(len(items)):
            self.sel = (self.sel + d) % len(items)
            if items[self.sel].selectable:
                return

    # -- keys --
    def handle(self, key) -> str | None:
        """Feed one key. Returns "back", "action:<key>", "changed:<key>",
        "edit:<key>", "cancel:<key>" or None."""
        name, char, ctrl = _k(key)
        f = self.current
        if f is None:
            return "back" if name in BACK else None
        if self.editing:
            return self._edit_key(f, name, char, ctrl)
        name = nav_name(name, char, ctrl)
        if name in UP:
            self._move(-1)
        elif name in DOWN:
            self._move(1)
        elif name == "pageup":
            for _ in range(ROWS):
                self._move(-1)
        elif name == "pagedown":
            for _ in range(ROWS):
                self._move(1)
        elif name in SELECT or (char == " " and f.kind in ("bool", "choice")):
            if f.kind == "action":
                return f"action:{f.key}"
            if f.kind == "bool":
                self.values[f.key] = not self.values.get(f.key)
                return f"changed:{f.key}"
            if f.kind == "choice":
                ch = [str(c) for c in f.choices]
                cur = str(self.values.get(f.key))
                self.values[f.key] = ch[(ch.index(cur) + 1) % len(ch)] if cur in ch else ch[0]
                return f"changed:{f.key}"
            if f.editable:
                self.start_edit()
                return f"edit:{f.key}"
        elif name in BACK:
            return "back"
        return None

    def _edit_key(self, f: Field, name: str, char: str, ctrl: bool) -> str | None:
        if name == "enter":
            v = self.buf if f.kind == "secret" else self.buf.strip()
            self.editing = False
            self.values[f.key] = v
            return f"changed:{f.key}"
        if name == "esc":
            self.editing = False
            return f"cancel:{f.key}"
        if name == "left":
            self.pos = max(0, self.pos - 1)
        elif name == "right":
            self.pos = min(len(self.buf), self.pos + 1)
        elif name == "home":
            self.pos = 0
        elif name == "end":
            self.pos = len(self.buf)
        elif name == "backspace":
            if self.pos:
                self.buf = self.buf[:self.pos - 1] + self.buf[self.pos:]
                self.pos -= 1
        elif name == "delete":
            self.buf = self.buf[:self.pos] + self.buf[self.pos + 1:]
        elif ctrl and char.lower() == "u":
            self.buf, self.pos = "", 0
        elif char and not ctrl and len(self.buf) < f.maxlen:
            if f.kind in ALLOWED and char not in ALLOWED[f.kind]:
                return None
            self.buf = self.buf[:self.pos] + char + self.buf[self.pos:]
            self.pos += 1
        return None

    # -- drawing --
    def fmt(self, f: Field) -> str:
        v = self.values.get(f.key)
        if f.kind == "bool":
            names = tuple(f.choices) if f.choices else ("On", "Off")
            return names[0] if v else names[1]
        if f.kind in ("header", "action"):
            return ""
        if f.kind == "secret":
            return "•" * len(str(v or "")) if v else "(none)"
        return str(v if v is not None else "")

    def view(self, n: int = ROWS) -> list[RowView]:
        items = self.shown()
        self.current  # clamps sel
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + n:
            self.top = self.sel - n + 1
        out = []
        for i, f in enumerate(items[self.top:self.top + n], start=self.top):
            if f.kind == "header":
                out.append(RowView(f.label, state="header", color=f.color or WARN))
                continue
            label = f"[ {f.label} ]" if f.kind == "action" else f.label
            color = f.color or (OK if f.kind == "action" else FG)
            if i == self.sel and self.editing:
                out.append(RowView(label, self.buf, "editing", color, self.pos))
            else:
                out.append(RowView(label, self.fmt(f), "selected" if i == self.sel else "normal", color))
        return out

    def hint(self) -> str:
        if self.editing:
            f = self.current
            extra = f"  {f.help}" if f and f.help and len(f.help) <= 20 else ""
            return HINT_EDIT + extra
        f = self.current
        if f and f.kind in ("bool", "choice"):
            return "↑↓ move  OK/→ change  ESC back"
        return HINT_FORM


# ---- rendering (pygame) ---------------------------------------------------------

_fonts: dict = {}


def fonts() -> dict:
    """{"title", "row", "small"} pygame fonts, DejaVu Sans Bold when present."""
    if not _fonts:
        import os
        import pygame
        pygame.font.init()
        path = next((p for p in FONT_PATHS if os.path.exists(p)), None)
        for name, size in FONT_SIZES.items():
            _fonts[name] = pygame.font.Font(path, size) if path else pygame.font.Font(None, int(size * 1.35))
    return _fonts


def as_view(row, selected: bool) -> RowView:
    """Accept RowView, "text", (text, color) or (text, color, right_text)."""
    if isinstance(row, RowView):
        return row
    if isinstance(row, str):
        row = (row, FG)
    return RowView(row[0], row[2] if len(row) > 2 else "", "selected" if selected else "normal", row[1])


REMOTE_ON = (255, 150, 30)     # orange dot: TNT MCP Link is on (Claude can reach the device)
REMOTE_ROOT = (255, 60, 60)    # red dot: ... and Admin (sudo) is allowed


def remote_state() -> str:
    """"", "on" or "root": read from the flag file the TNT MCP Link server keeps."""
    import os
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    try:
        state = ""
        for name in ("tnt-remote", "nomad-ai-bridge", "nomad-mcp"):   # TNT MCP Link, Nomad AI Bridge (was Nomad MCP)
            try:
                with open(os.path.join(run, name, "active")) as fh:
                    state = "root" if "root" in fh.read() else (state or "on")
            except OSError:
                pass
        return state
    except OSError:
        return ""


def render(surf, title: str, rows: list, hint: str = "", selected: int | None = None,
           right: str = "", f: dict | None = None) -> None:
    """Draw a whole TNT screen: green title, up to ROWS rows, hint bar.
    While TNT MCP Link is on, every TNT app shows an orange dot (red with sudo)
    at the right end of the title bar."""
    import pygame
    f = f or fonts()
    surf.fill(BG)
    surf.fill(TITLE_BG, (0, 0, W, TITLE_H))
    surf.blit(f["title"].render(title, True, TITLE_FG), (6, 2), (0, 0, W - 12, TITLE_H))
    rs = remote_state()
    dot = 16 if rs else 0
    if right:
        img = f["small"].render(right, True, TITLE_RIGHT)
        surf.fill(TITLE_BG, (W - img.get_width() - 12 - dot, 0, img.get_width() + 12 + dot, TITLE_H))
        surf.blit(img, (W - img.get_width() - 6 - dot, 5))
    if rs:
        surf.fill(TITLE_BG, (W - dot - 4, 0, dot + 4, TITLE_H))
        pygame.draw.circle(surf, REMOTE_ROOT if rs == "root" else REMOTE_ON, (W - 10, TITLE_H // 2), 6)
    y = TITLE_H + 1
    for i, row in enumerate(rows[:ROWS]):
        draw_row(surf, f["row"], y, as_view(row, selected == i))
        y += ROW_H
    if hint:
        surf.fill(HINT_BG, (0, H - HINT_H, W, HINT_H))
        surf.blit(f["small"].render(hint, True, HINT_FG), (6, H - HINT_H + 1), (0, 0, W - 12, HINT_H))


def draw_row(surf, font, y: int, r: RowView) -> None:
    if r.state == "editing":
        surf.fill(EDIT_BG, (0, y, W, ROW_H))
        lw = font.size(r.label)[0]
        fx = min(lw + 14, W - 150)
        surf.blit(font.render(r.label, True, TITLE_FG), (6, y + 1), (0, 0, fx - 10, ROW_H))
        fw = W - fx - 4
        surf.fill(EDIT_FIELD, (fx - 3, y + 1, fw + 1, ROW_H - 2))
        # scroll so the cursor stays in view
        start = 0
        while start < r.cursor and font.size(r.value[start:r.cursor])[0] > fw - 8:
            start += 1
        text = r.value[start:]
        surf.blit(font.render(text, True, (255, 255, 255)), (fx, y + 1), (0, 0, fw - 2, ROW_H))
        cx = fx + font.size(r.value[start:r.cursor])[0]
        surf.fill((255, 255, 255), (min(cx, W - 6), y + 3, 2, ROW_H - 6))
        return
    sel = r.state == "selected"
    if sel:
        surf.fill(SEL_BG, (0, y, W, ROW_H))
    color = r.color or FG
    vw = 0
    if r.value:
        img = font.render(r.value, True, FG if sel else DIM)
        lw = font.size(r.label)[0]
        vw = min(img.get_width(), max(W // 2, W - 12 - lw - 12))
        surf.blit(img, (W - vw - 6, y + 1), (0, 0, vw, ROW_H))
    room = W - 12 - (vw + 10 if vw else 0)
    surf.blit(font.render(r.label, True, color), (6, y + 1), (0, 0, room, ROW_H))
