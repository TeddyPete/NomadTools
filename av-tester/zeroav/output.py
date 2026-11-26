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

from . import sdlmodes
from .patterns import MovingBox, Pattern


class HdmiOutput:
    def __init__(self, size, fullscreen_desktop: bool, display: int = 0):
        """size is (w, h) or an sdlmodes.Mode (exact mode incl. refresh)."""
        self.fullscreen_desktop = fullscreen_desktop
        self.display = display
        self.mode_set = False
        self._page: Texture | None = None
        self._page_key = None
        self.pages = 1
        self.window: Window | None = None
        self.renderer: Renderer | None = None
        self._tex: Texture | None = None
        self._tex_key = None
        self._overlay: Texture | None = None
        self._overlay_key = None
        self.open(size)

    def open(self, size) -> None:
        self.close()
        mode = size if isinstance(size, sdlmodes.Mode) else None
        if mode:
            size = mode.size
        if self.fullscreen_desktop:
            self.window = Window("TNT AV Tester", size=size, fullscreen_desktop=True)
        else:
            self.window = Window("TNT AV Tester", size=size, fullscreen=True)
        # Pick the exact refresh rate before the renderer starts.
        self.mode_set = bool(mode) and sdlmodes.set_mode(self.window.id, self.display, mode)
        try:
            self.renderer = Renderer(self.window, accelerated=1, vsync=True)
            self.accelerated = True
        except Exception:  # no GPU renderer: fall back to software (slow)
            self.renderer = Renderer(self.window, accelerated=-1, vsync=True)
            self.accelerated = False
        self.size = self.window.size
        self._tex = self._overlay = self._page = None
        self._tex_key = self._overlay_key = self._page_key = None

    def close(self) -> None:
        self._tex = self._overlay = self._page = None
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

    def _page_texture(self, title: str, sections: list[tuple[str, list[str]]], page: int) -> Texture:
        """A full-screen text page (the EDID view), laid out in columns.
        Sets self.pages to the page count when it doesn't all fit."""
        key = (title, tuple((t, tuple(b)) for t, b in sections), page, self.size)
        if self._page_key == key:
            return self._page
        self._page = None
        w, h = self.size
        fh = max(14, h // 36)
        font = pygame.font.Font(None, fh)
        head = pygame.font.Font(None, int(fh * 1.25))
        tfont = pygame.font.Font(None, int(fh * 1.8))
        ncol = 3 if w >= 1200 else 2 if w >= 700 else 1
        margin = w // 40
        colw = (w - 2 * margin) // ncol - margin // 2
        top = h // 40 + tfont.get_linesize() + fh // 2
        bottom = h - h // 40 - fh
        # flatten into (kind, text) rows wrapped to the column width
        rows = []
        for t, body in sections:
            rows.append(("head", t))
            for line in body:
                cur = ""
                for word in line.split(" "):
                    trial = f"{cur} {word}" if cur else word
                    if cur and font.size(trial)[0] > colw:
                        rows.append(("text", cur))
                        cur = "    " + word
                    else:
                        cur = trial
                rows.append(("text", cur))
            rows.append(("gap", ""))
        # split rows into columns, then columns into pages
        cols, col, y = [], [], top
        for kind, text in rows:
            lh = head.get_linesize() if kind == "head" else font.get_linesize()
            if kind == "gap":
                lh = fh // 2
            if y + lh > bottom and col:
                cols.append(col)
                col, y = [], top
                if kind == "gap":
                    continue
            col.append((kind, text))
            y += lh
        if col:
            cols.append(col)
        self.pages = max(1, -(-len(cols) // ncol))
        page %= self.pages
        surf = pygame.Surface(self.size)
        surf.fill((8, 12, 24))
        t = title + (f"   (page {page + 1}/{self.pages}, < > to turn)" if self.pages > 1 else "")
        surf.blit(tfont.render(t, True, (255, 255, 255)), (margin, h // 40))
        for c, colrows in enumerate(cols[page * ncol:(page + 1) * ncol]):
            x, y = margin + c * (colw + margin // 2), top
            for kind, text in colrows:
                if kind == "head":
                    surf.blit(head.render(text, True, (255, 210, 90)), (x, y))
                    y += head.get_linesize()
                elif kind == "gap":
                    y += fh // 2
                else:
                    color = (255, 120, 120) if "too fast" in text else (230, 230, 230)
                    surf.blit(font.render(text, True, color), (x, y))
                    y += font.get_linesize()
        surf.blit(font.render("E: back to patterns   S: save report", True, (140, 180, 255)),
                  (margin, h - h // 40 - fh))
        self._page = Texture.from_surface(self.renderer, surf)
        self._page_key = key
        return self._page

    def text_page(self, title: str, sections: list[tuple[str, list[str]]], page: int) -> None:
        self.renderer.blit(self._page_texture(title, sections, page), pygame.Rect(0, 0, *self.size))
        self.renderer.present()

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
