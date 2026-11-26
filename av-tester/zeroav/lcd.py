"""Status panel on the CardputerZero's 320x170 LCD.

The LCD is written as a Linux framebuffer (/dev/fbN). We find the
framebuffer whose size matches the panel and write RGB565 pixels to it.
If none is found (for example on a desktop PC), the panel falls back to
printing status lines to the terminal so the app still runs.
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pygame

PANEL_SIZES = {(320, 170), (170, 320)}


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

    def show(self, title: str, lines: list[str], hint: str = "") -> None:
        s = self.surf
        s.fill((0, 0, 0))
        s.fill((20, 60, 120), (0, 0, 320, 30))
        s.blit(self.font_big.render(title[:26], True, (255, 255, 255)), (6, 5))
        y = 36
        for line in lines[:5]:
            s.blit(self.font.render(line[:40], True, (230, 230, 230)), (6, y))
            y += 22
        if hint:
            s.blit(self.font.render(hint[:42], True, (150, 200, 255)), (6, 150))
        self._flush([title, *lines, hint])

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
