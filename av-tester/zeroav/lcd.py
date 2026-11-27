"""Status panel on the CardputerZero's 320x170 LCD.

The LCD is written as a Linux framebuffer (/dev/fbN). We find the
framebuffer whose size matches the panel and write RGB565 pixels to it.
If none is found (for example on a desktop PC), the panel falls back to
printing status lines to the terminal so the app still runs.
"""
from __future__ import annotations

import glob
import os
import threading

import numpy as np
import pygame

PANEL_SIZES = {(320, 170), (170, 320)}
# Nomad colours: green title bar, blue highlight, red while editing a field
TITLE_BG = (18, 120, 52)      # same as nomadui.py
HINT = (150, 200, 255)


def find_lcd_fb() -> tuple[str, int, int, int] | None:
    # APPLaunch tells apps which framebuffer is the LCD; honour that first.
    override = (os.environ.get("ZEROAV_LCD_FB")
                or os.environ.get("APPLAUNCH_LINUX_FBDEV_DEVICE")
                or os.environ.get("LV_LINUX_FBDEV_DEVICE"))
    if override:
        override = os.path.realpath(override)
    for sysdir in sorted(glob.glob("/sys/class/graphics/fb*")):
        dev = "/dev/" + os.path.basename(sysdir)
        try:
            w, h = (int(v) for v in open(f"{sysdir}/virtual_size").read().strip().split(","))
            bpp = int(open(f"{sysdir}/bits_per_pixel").read().strip())
        except (OSError, ValueError):
            continue
        if override and dev == override or not override and (w, h) in PANEL_SIZES:
            return dev, w, h, bpp
    return None


class LcdPanel:
    def __init__(self, headless: bool = False):
        found = None if headless else find_lcd_fb()
        self.dev = None
        if found:
            self.dev, self.fw, self.fh, self.bpp = found
        self.headless = headless
        self.size = (320, 170)
        self.surf = pygame.Surface(self.size)
        self._last_text: list[str] = []
        self.font_big = pygame.font.Font(None, 30)
        self.font = pygame.font.Font(None, 22)
        self.font_small = pygame.font.Font(None, 19)
        self._pending = None
        self.help = None              # nomadui.HelpView shown over everything (Fn+H)
        self._cv = threading.Condition()
        self._worker = None

    def show_async(self, title: str, lines: list[str], hint: str = "", small: bool = False,
                   keys: list | None = None) -> None:
        """Queue a status update and return at once. A background thread
        draws it, so the HDMI render loop never waits on the LCD."""
        with self._cv:
            self._pending = (title, list(lines), hint, small, keys)
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()
            self._cv.notify()

    def draw_async(self, fn) -> None:
        """Queue a custom drawing: fn(surface) draws the whole 320x170 panel."""
        with self._cv:
            self._pending = ("fn", fn)
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._pending is None:
                    self._cv.wait()
                job, self._pending = self._pending, None
            hv = self.help
            if hv is not None:
                hv.render(self.surf)
                if self.dev:
                    self._flush([])
                continue
            if job[0] == "fn":
                job[1](self.surf)
                if self.dev:
                    self._flush([])
            else:
                self.show(*job)

    def wrap(self, lines: list[str], small: bool = True, width: int = 308) -> list[str]:
        """Split lines so each fits the panel width, indenting the rest."""
        font = self.font_small if small else self.font
        out = []
        for line in lines:
            words, cur = line.split(" "), ""
            for w in words:
                trial = f"{cur} {w}" if cur else w
                if cur and font.size(trial)[0] > width:
                    out.append(cur)
                    cur = "   " + w
                else:
                    cur = trial
            out.append(cur)
        return out

    # lines that fit on the panel in normal and small text
    ROWS, ROWS_SMALL = 5, 7
    ROWS_KEYS, ROWS_SMALL_KEYS = 4, 6     # above the 4..8 keybar

    def show(self, title: str, lines: list[str], hint: str = "", small: bool = False,
             keys: list | None = None) -> None:
        """keys: labels for number keys 4..8, drawn as a keybar instead of the hint."""
        s = self.surf
        s.fill((0, 0, 0))
        self._title(title)
        y = 34 if small else 36
        font, step, rows = (self.font_small, 16, self.ROWS_SMALL) if small else (self.font, 22, self.ROWS)
        if keys:
            rows = self.ROWS_SMALL_KEYS if small else self.ROWS_KEYS
        for line in lines[:rows]:
            color = (255, 220, 120) if line.startswith("-- ") else (230, 230, 230)
            img = font.render(line, True, color)
            s.blit(img, (6, y), (0, 0, 310, step))
            y += step
        if keys:
            from . import nomadui
            nomadui.draw_keybar(s, keys)
        else:
            self._hint(hint)
        self._flush([title, *lines, hint])

    def show_help(self, view) -> None:
        """Fn+H: draw a nomadui.HelpView over the whole panel until hide_help()."""
        self.help = view
        self.draw_async(view.render)

    def hide_help(self) -> None:
        self.help = None

    def _title(self, title: str) -> None:
        self.surf.fill(TITLE_BG, (0, 0, 320, 30))
        self.surf.blit(self.font_big.render(title[:26], True, (255, 255, 255)), (6, 5))

    def _hint(self, hint: str) -> None:
        if not hint:
            return
        img = self.font.render(hint, True, HINT)
        if img.get_width() > 310:   # too long: use small text, squeezed to fit
            img = self.font_small.render(hint, True, HINT)
            if img.get_width() > 314:
                img = pygame.transform.smoothscale(img, (314, img.get_height()))
            self.surf.blit(img, (3, 152))
        else:
            self.surf.blit(img, (6, 150))

    def show_list_async(self, title: str, items: list[str], sel: int, hint: str = "",
                        editing: bool = False, keys: list | None = None) -> None:
        """A menu or form: the selected row is blue, or red while it is being edited."""
        self.draw_async(lambda s: self.show_list(title, items, sel, hint, editing, keys))

    def show_list(self, title: str, items: list[str], sel: int, hint: str = "",
                  editing: bool = False, keys: list | None = None) -> None:
        """Drawn with the shared Nomad UI (nomadui.py): green title, 6 rows (5
        with a 4..8 keybar), blue highlight, red row while a field is edited."""
        from . import nomadui
        rows = nomadui.ROWS_KEYS if keys else nomadui.ROWS
        top = max(0, min(sel - rows // 2, len(items) - rows))
        views = []
        for i in range(top, min(len(items), top + rows)):
            label, sep, value = items[i].partition(": ")
            if not sep:
                label, value = items[i], ""
            state = ("editing" if editing else "selected") if i == sel else "normal"
            views.append(nomadui.RowView(label, value, state,
                                       cursor=len(value) if state == "editing" else None))
        nomadui.render(self.surf, title, views, hint, keys=keys)
        mark = ["> " + t if i == sel else "  " + t for i, t in enumerate(items)]
        self._flush([title, *mark, hint + (" [editing]" if editing else "")])

    def save(self, path: str) -> None:
        """Write the current panel image to a PNG (used for store screenshots)."""
        pygame.image.save(self.surf, path)

    def _flush(self, text: list[str]) -> None:
        if not self.dev:
            if self.headless:
                return
            if text != self._last_text:
                print(" | ".join(t for t in text if t), flush=True)
                self._last_text = text
            return
        img = self.surf
        if (self.fw, self.fh) == (170, 320):
            img = pygame.transform.rotate(img, 90)
        arr = pygame.surfarray.pixels3d(img).swapaxes(0, 1).astype(np.uint16)  # (h, w, 3)
        if self.bpp == 16:
            out = ((arr[..., 0] >> 3) << 11) | ((arr[..., 1] >> 2) << 5) | (arr[..., 2] >> 3)
            data = out.astype("<u2").tobytes()
        else:  # 32 bpp XRGB
            a = arr.astype(np.uint32)
            data = ((a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]).astype("<u4").tobytes()
        try:
            with open(self.dev, "wb") as fb:
                fb.write(data)
        except OSError as e:
            print(f"LCD write failed ({e}); using terminal output", flush=True)
            self.dev = None
