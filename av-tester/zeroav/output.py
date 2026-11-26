"""GPU output for HDMI.

Drawing a 1920x1080 frame on the CPU and copying it to the screen every
frame is far too slow on the CardputerZero (about 10 fps). Instead:

- Static patterns are drawn once on the CPU and uploaded to the GPU as one
  texture. Each frame just redraws that texture, which the GPU does at full
  refresh rate.
- Moving patterns (the judder box) are drawn with GPU rectangle fills.
- The info overlay is a small text texture, rebuilt once per second.

Presents are synced to vblank, so the measured rate equals the HDMI refresh
rate when the output keeps up.
"""
from __future__ import annotations

import pygame
from pygame._sdl2.video import Renderer, Texture, Window

from .patterns import MovingBox, Pattern


class HdmiOutput:
    def __init__(self, size: tuple[int, int], fullscreen_desktop: bool):
        self.fullscreen_desktop = fullscreen_desktop
        self.window: Window | None = None
        self.renderer: Renderer | None = None
        self._tex: Texture | None = None
        self._tex_key = None
        self._overlay: Texture | None = None
        self._overlay_key = None
        self.open(size)

    def open(self, size: tuple[int, int]) -> None:
        self.close()
        if self.fullscreen_desktop:
            self.window = Window("AV Tester", size=size, fullscreen_desktop=True)
        else:
            self.window = Window("AV Tester", size=size, fullscreen=True)
        try:
            self.renderer = Renderer(self.window, accelerated=1, vsync=True)
            self.accelerated = True
        except Exception:  # no GPU renderer: fall back to software (slow)
            self.renderer = Renderer(self.window, accelerated=-1, vsync=True)
            self.accelerated = False
        self.size = self.window.size
        self._tex = self._overlay = None
        self._tex_key = self._overlay_key = None

    def close(self) -> None:
        self._tex = self._overlay = None
        self.renderer = None
        if self.window is not None:
            self.window.destroy()
            self.window = None

    def _pattern_texture(self, pat: Pattern) -> Texture:
        key = (id(pat), self.size)
        if self._tex_key != key:
            self._tex = None  # free the old texture before making a new one
            surf = pygame.Surface(self.size)
            pat.draw(surf, 0)
            self._tex = Texture.from_surface(self.renderer, surf)
            self._tex_key = key
        return self._tex

    def _overlay_texture(self, lines: list[str]) -> Texture:
        key = tuple(lines)
        if self._overlay_key != key:
            w, h = self.size
            font = pygame.font.Font(None, max(16, h // 30))
            imgs = [font.render(t, True, (255, 255, 255), (0, 0, 0)) for t in lines]
            surf = pygame.Surface((max(i.get_width() for i in imgs),
                                   sum(i.get_height() + 2 for i in imgs)))
            y = 0
            for img in imgs:
                surf.blit(img, (0, y))
                y += img.get_height() + 2
            self._overlay = Texture.from_surface(self.renderer, surf)
            self._overlay_key = key
        return self._overlay

    def frame(self, pat: Pattern, frame: int, overlay: list[str] | None) -> None:
        r = self.renderer
        if isinstance(pat, MovingBox):
            self._moving_box(pat, frame)
        else:
            r.blit(self._pattern_texture(pat), pygame.Rect(0, 0, *self.size))
        if overlay:
            w, h = self.size
            t = self._overlay_texture(overlay)
            r.blit(t, pygame.Rect(w // 40, h // 40, t.width, t.height))
        r.present()

    def _moving_box(self, pat: MovingBox, frame: int) -> None:
        r = self.renderer
        w, h = self.size
        r.draw_color = (0, 0, 0, 255)
        r.clear()
        size = h // 6
        travel = w - size
        pos = (frame * pat.px) % (2 * travel)
        x = pos if pos < travel else 2 * travel - pos
        r.draw_color = (255, 255, 255, 255)
        r.fill_rect(pygame.Rect(x, h // 2 - size // 2, size, size))
        cell = w // 10
        r.draw_color = (255, 0, 0, 255)
        r.fill_rect(pygame.Rect((frame % 10) * cell, h - h // 20, cell, h // 20))
