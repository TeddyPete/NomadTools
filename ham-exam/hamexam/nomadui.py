"""Nomad UI standard for CardputerZero apps (one file, copy it into any Nomad app).

What every Nomad app does on the 320x170 screen:

  * Title bar is green, the highlighted row is blue, a field being edited is red.
  * Menus:   Up/Down move (plain F / X work too, no Fn needed).
             OK (Enter) or Right selects.  Left or ESC goes back one level;
             ESC on the main page quits.  (Plain Z / C = Left / Right.)
  * Keys 4-8 (the five number keys right under the screen) run the most
             used actions of a screen; their labels sit at the bottom of the
             screen with a short line pointing down to each key (keybar).
  * Fn+H     shows / hides the help for the current screen.
  * Hold ESC goes to HOME (the launcher does that; apps never fight it).
             This is the official CardputerZero key spec:
             https://cardputer.cc/#/documents/cp0-keys
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
    nomadui.render(surface, fonts, "Hotspot", form.view(6), form.hint())
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, Callable

# ---- colors (RGB) -----------------------------------------------------------
# No published CardputerZero/APPLaunch color standard exists, so this is the
# Nomad scheme Ted picked: green title, blue highlight, red while editing.
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
FONT_SIZES = {"title": 19, "row": 17, "small": 14, "tiny": 12}

# ---- keys -----------------------------------------------------------------------
UP, DOWN = {"up"}, {"down"}
SELECT = {"enter", "right"}
BACK = {"esc", "left"}
# Plain letters printed under the arrows on the CardputerZero keycaps.
NAV_LETTERS = {"f": "up", "x": "down", "z": "left", "c": "right"}

HINT_MENU = "↑↓ move  OK/→ open  ←/ESC back"
HINT_FORM = "↑↓ move  OK/→ edit  ESC back"
HINT_EDIT = "OK save  ESC cancel"

# ---- official CardputerZero key spec (cardputer.cc/#/documents/cp0-keys) ---------
HELP = "help"                  # Fn+H sends KEY_HELP (evdev 138): show / hide help
SOFT_KEYS = "45678"            # number keys under the screen, left to right
SOFT_X = (49, 105, 161, 217, 273)   # recommended icon centres
SOFT_Y = 153
SOFT_SIZE = 22                 # recommended icon size (22 x 22)
SOFT_W = 52                    # our label boxes are 52 wide so text fits
KEYBAR_H = 30                  # bottom strip y 140..170
ROWS_KEYS = (H - TITLE_H - KEYBAR_H - 2) // ROW_H   # 5 rows above a keybar
KEYBAR_BG = (14, 17, 26)
SOFT_BG = (36, 48, 76)
SOFT_FG = (235, 240, 255)
SOFT_LINE = (150, 200, 255)

KEYS_HELP = [
    "Keys",
    "F / X  move up / down",
    "OK or C/→  open or select",
    "Z/← or ESC  back one level",
    "4 5 6 7 8  the actions shown at",
    "   the bottom of the screen",
    "Hold ESC  go to HOME",
    "Fn+H  show / hide this help",
]


def soft_index(char: str) -> int | None:
    """0..4 for number keys 4..8, else None."""
    return SOFT_KEYS.index(char) if char and len(char) == 1 and char in SOFT_KEYS else None


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
        return self.kind in ("text", "ip", "mask", "secret", "number", "decimal")

    @property
    def selectable(self) -> bool:
        return self.kind != "header"


ALLOWED = {"ip": set("0123456789."), "mask": set("0123456789./"), "number": set("0123456789"),
           "decimal": set("0123456789.-")}


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


_title_fonts: dict = {}
# The launcher draws its status icons (signal, clock, battery) over the
# right end of the title bar, from about x=232, so titles fit left of that.
TITLE_MAX_W = 222


def title_image(text: str, maxw: int = TITLE_MAX_W, f: dict | None = None):
    """The title in the title font, stepped down a size or two when a long
    name ("Nomad Display Control") would not fit, so it is never cut off."""
    f = f or fonts()
    img = f["title"].render(text, True, TITLE_FG)
    size = FONT_SIZES["title"]
    while img.get_width() > maxw and size > FONT_SIZES["small"]:
        size -= 1
        if size not in _title_fonts:
            import os
            import pygame
            path = next((p for p in FONT_PATHS if os.path.exists(p)), None)
            _title_fonts[size] = pygame.font.Font(path, size) if path else pygame.font.Font(None, int(size * 1.35))
        img = _title_fonts[size].render(text, True, TITLE_FG)
    return img


def as_view(row, selected: bool) -> RowView:
    """Accept RowView, "text", (text, color) or (text, color, right_text)."""
    if isinstance(row, RowView):
        return row
    if isinstance(row, str):
        row = (row, FG)
    return RowView(row[0], row[2] if len(row) > 2 else "", "selected" if selected else "normal", row[1])


def render(surf, title: str, rows: list, hint: str = "", selected: int | None = None,
           right: str = "", f: dict | None = None, keys: list | None = None) -> None:
    """Draw a whole Nomad screen: green title, up to ROWS rows, hint bar.
    With keys (labels for number keys 4..8) the hint bar becomes a keybar and
    ROWS_KEYS rows fit."""
    f = f or fonts()
    if keys and any(keys):
        rows = rows[:ROWS_KEYS]
    surf.fill(BG)
    surf.fill(TITLE_BG, (0, 0, W, TITLE_H))
    img = title_image(title, f=f)
    surf.blit(img, (6, max(0, (TITLE_H - img.get_height()) // 2)), (0, 0, W - 12, TITLE_H))
    if right:
        img = f["small"].render(right, True, TITLE_RIGHT)
        surf.fill(TITLE_BG, (W - img.get_width() - 12, 0, img.get_width() + 12, TITLE_H))
        surf.blit(img, (W - img.get_width() - 6, 5))
    y = TITLE_H + 1
    for i, row in enumerate(rows[:ROWS]):
        draw_row(surf, f["row"], y, as_view(row, selected == i))
        y += ROW_H
    if keys and any(keys):
        draw_keybar(surf, keys, f)
    elif hint:
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


# ---- keybar for number keys 4..8 -------------------------------------------------

def _fit(f: dict, text: str, width: int):
    font = f["small"]
    if font.size(text)[0] > width:
        font = f.get("tiny") or font
    return font


def draw_keybar(surf, keys: list, f: dict | None = None, y0: int | None = None) -> None:
    """Labels for number keys 4..8 along the bottom, each with a short line
    pointing down to its key. keys: up to 5 labels, None/"" leaves a key out.
    A label can be ("text", color) to tint it (e.g. red for Stop)."""
    import pygame
    f = f or fonts()
    sw, sh = surf.get_size()
    sx = sw / W                       # scale when drawn on a bigger surface
    top = sh - int(KEYBAR_H * sx) if y0 is None else y0
    surf.fill(KEYBAR_BG, (0, top, sw, sh - top))
    surf.fill((40, 46, 62), (0, top, sw, 1))
    bw, bh = int(SOFT_W * sx), int(SOFT_SIZE * sx)
    by = top + int(2 * sx)
    for i, cx in enumerate(SOFT_X):
        lab = keys[i] if i < len(keys) else None
        if not lab:
            continue
        color = SOFT_FG
        if isinstance(lab, (tuple, list)):
            lab, color = lab[0], lab[1]
        x = int(cx * sx)
        r = pygame.Rect(x - bw // 2, by, bw, bh)
        pygame.draw.rect(surf, SOFT_BG, r, border_radius=max(3, int(4 * sx)))
        font = _fit(f, lab, bw - 4)
        img = font.render(lab, True, color)
        if img.get_width() > bw - 4:
            img = pygame.transform.smoothscale(img, (bw - 4, img.get_height()))
        surf.blit(img, (x - img.get_width() // 2, by + (bh - img.get_height()) // 2))
        surf.fill(SOFT_LINE, (x - max(1, int(sx)) // 2, by + bh + 1, max(1, int(sx)), sh - (by + bh + 1)))


# ---- Fn+H help ------------------------------------------------------------------

def wrap_text(font, text, width: int, indent: str = "") -> list[str]:
    out = []
    for para in (text if isinstance(text, list) else str(text).split("\n")):
        words, cur = str(para).split(" "), ""
        for w in words:
            trial = f"{cur} {w}" if cur else w
            if cur and font.size(trial)[0] > width:
                out.append(cur)
                cur = indent + w
            else:
                cur = trial
        out.append(cur)
    return out


class HelpView:
    """Full-screen help shown with Fn+H. text: this screen's help (str or
    lines); the standard key list is added after it."""
    LINE_H = 17

    def __init__(self, title: str, text="", keys: list | None = None):
        self.title = f"Help: {title}" if title else "Help"
        self.text = text
        self.keys = keys or []
        self.top = 0
        self._lines = None

    def lines(self, f: dict) -> list:
        if self._lines is None:
            font = f["small"]
            out = []
            if self.text:
                out += [(l, FG) for l in wrap_text(font, self.text, W - 14)] + [("", FG)]
            names = [k[0] if isinstance(k, (tuple, list)) else k for k in self.keys]
            soft = [f"{SOFT_KEYS[i]}  {n}" for i, n in enumerate(names) if n]
            if soft:
                out += [("Number keys", WARN)] + [(l, FG) for l in soft] + [("", FG)]
            out += [(KEYS_HELP[0], WARN)] + [(l, FG) for l in KEYS_HELP[1:]]
            self._lines = out
        return self._lines

    def rows(self) -> int:
        return (H - TITLE_H - HINT_H - 4) // self.LINE_H

    def handle(self, key) -> str | None:
        """Returns "close" when the help should go away."""
        name, char, ctrl = _k(key)
        name = nav_name(name, char, ctrl)
        n = len(self._lines or [])
        if name in ("up", "pageup"):
            self.top = max(0, self.top - (1 if name == "up" else self.rows()))
        elif name in ("down", "pagedown"):
            self.top = max(0, min(n - self.rows(), self.top + (1 if name == "down" else self.rows())))
        elif name in (HELP, "esc", "enter", "left", "backspace"):
            return "close"
        return None

    def render(self, surf, f: dict | None = None) -> None:
        f = f or fonts()
        ls = self.lines(f)
        surf.fill(BG)
        surf.fill(TITLE_BG, (0, 0, W, TITLE_H))
        img = title_image(self.title, f=f)
        surf.blit(img, (6, max(0, (TITLE_H - img.get_height()) // 2)), (0, 0, W - 12, TITLE_H))
        y = TITLE_H + 2
        for text, color in ls[self.top:self.top + self.rows()]:
            surf.blit(f["small"].render(text, True, color), (7, y), (0, 0, W - 12, self.LINE_H))
            y += self.LINE_H
        if len(ls) > self.rows():
            span = H - TITLE_H - HINT_H
            bh = max(8, span * self.rows() // len(ls))
            by = TITLE_H + (span - bh) * self.top // max(1, len(ls) - self.rows())
            surf.fill((90, 100, 130), (W - 3, by, 3, bh))
        surf.fill(HINT_BG, (0, H - HINT_H, W, HINT_H))
        hint = "\u2191\u2193 scroll  Fn+H/ESC close" if len(ls) > self.rows() else "Fn+H / ESC / OK close"
        surf.blit(f["small"].render(hint, True, HINT_FG), (6, H - HINT_H + 1))
