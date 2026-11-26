"""Draws the app's screens on the CardputerZero's 320x170 LCD framebuffer.

Same approach as the TNT AV Tester: render with pygame into a surface and
write RGB565 pixels to the LCD's /dev/fbN. With no LCD (a desktop PC, or
tests) frames can be saved as PNG files instead.
"""
from __future__ import annotations

import glob
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import numpy as np  # noqa: E402
import pygame  # noqa: E402

PANEL_SIZES = {(320, 170), (170, 320)}
W, H = 320, 170

BG = (8, 10, 16)
BAR = (150, 40, 20)       # TNT orange-red title bar
FG = (232, 232, 232)
DIM = (140, 150, 165)
SEL_BG = (40, 80, 150)
OK = (110, 220, 120)
WARN = (255, 200, 90)
BAD = (255, 110, 100)
HINT = (150, 200, 255)


def find_lcd_fb():
    override = (os.environ.get("TNT_LCD_FB") or os.environ.get("APPLAUNCH_LINUX_FBDEV_DEVICE")
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
        if (override and dev == override) or (not override and (w, h) in PANEL_SIZES):
            return dev, w, h, bpp
    return None


class Panel:
    TITLE_H, ROW_H, HINT_H = 24, 18, 18
    ROWS = (H - TITLE_H - HINT_H - 4) // ROW_H  # 6 rows

    def __init__(self, headless: bool = False):
        pygame.font.init()
        found = None if headless else find_lcd_fb()
        self.dev = None
        if found:
            self.dev, self.fw, self.fh, self.bpp = found
        self.surf = pygame.Surface((W, H))
        self.f_title = pygame.font.Font(None, 26)
        self.f = pygame.font.Font(None, 21)
        self.f_small = pygame.font.Font(None, 18)
        self._last = None

    def text_width(self, s: str) -> int:
        return self.f.size(s)[0]

    def draw(self, title: str, rows: list, hint: str = "", selected: int | None = None,
             right: str = "") -> None:
        """rows: list of str or (text, color) or (text, color, right_text)."""
        s = self.surf
        s.fill(BG)
        s.fill(BAR, (0, 0, W, self.TITLE_H))
        s.blit(self.f_title.render(title, True, (255, 255, 255)), (6, 4))
        if right:
            img = self.f_small.render(right, True, (255, 230, 200))
            s.blit(img, (W - img.get_width() - 6, 6))
        y = self.TITLE_H + 3
        for i, row in enumerate(rows[: self.ROWS]):
            if isinstance(row, str):
                row = (row, FG)
            text, color = row[0], row[1]
            rtext = row[2] if len(row) > 2 else ""
            if selected is not None and i == selected:
                s.fill(SEL_BG, (0, y - 1, W, self.ROW_H))
            s.blit(self.f.render(text, True, color), (6, y), (0, 0, W - 12, self.ROW_H))
            if rtext:
                img = self.f.render(rtext, True, DIM if i != selected else FG)
                s.fill(SEL_BG if selected == i else BG, (W - img.get_width() - 10, y - 1, img.get_width() + 10, self.ROW_H))
                s.blit(img, (W - img.get_width() - 6, y))
            y += self.ROW_H
        if hint:
            s.fill((24, 28, 40), (0, H - self.HINT_H, W, self.HINT_H))
            s.blit(self.f_small.render(hint, True, HINT), (6, H - self.HINT_H + 3))
        self.flush()

    def save(self, path: str) -> None:
        pygame.image.save(self.surf, path)

    def flush(self) -> None:
        if not self.dev:
            return
        img = self.surf
        if (self.fw, self.fh) == (170, 320):
            img = pygame.transform.rotate(img, 90)
        arr = pygame.surfarray.pixels3d(img).swapaxes(0, 1).astype(np.uint16)
        if self.bpp == 16:
            out = ((arr[..., 0] >> 3) << 11) | ((arr[..., 1] >> 2) << 5) | (arr[..., 2] >> 3)
            data = out.astype("<u2").tobytes()
        else:
            a = arr.astype(np.uint32)
            data = ((a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]).astype("<u4").tobytes()
        if data == self._last:
            return
        try:
            with open(self.dev, "wb") as fb:
                fb.write(data)
            self._last = data
        except OSError:
            self.dev = None
