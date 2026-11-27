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

GPU memory is tight: the Pi's GPU pool (CMA) is 64 MB and the display
buffers plus GL's own buffers use most of it at 1080p. A second 1080p
texture (8 MB) or a burst of texture create/destroy makes the GPU driver
fail an allocation, and Mesa then crashes the app. So there is at most ONE
full-screen texture, updated in place when the picture changes, and every
other texture is small, created once, and freed before anything else needs
the space.
"""
from __future__ import annotations

import gc
import os

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
        self._slots: dict[str, list] = {}   # name -> [texture, key]
        self.pages = 1
        self.window: Window | None = None
        self.renderer: Renderer | None = None
        self.open(size)

    def open(self, size) -> None:
        self.close()
        mode = size if isinstance(size, sdlmodes.Mode) else None
        if mode:
            size = mode.size
        if self.fullscreen_desktop:
            self.window = Window("Nomad AV Tester", size=size, fullscreen_desktop=True)
        else:
            self.window = Window("Nomad AV Tester", size=size, fullscreen=True)
        # Pick the exact refresh rate before the renderer starts.
        self.mode_set = bool(mode) and sdlmodes.set_mode(self.window.id, self.display, mode)
        # On the Pi desktop (windowed), the GPU driver can crash outright
        # when a second client renders with GL, so use software rendering
        # there. Direct HDMI (kmsdrm) uses the GPU. NOMAD_RENDER=gpu|software
        # overrides.
        want = os.environ.get("NOMAD_RENDER", "software" if self.fullscreen_desktop else "gpu")
        self.renderer = None
        if want != "software":
            try:
                self.renderer = Renderer(self.window, accelerated=1, vsync=True)
                self.accelerated = True
            except Exception:  # no GPU renderer: fall back to software (slow)
                self.renderer = None
        if self.renderer is None:
            self.renderer = Renderer(self.window, accelerated=0, vsync=True)
            self.accelerated = False
        self.size = self.window.size
        self._slots = {}

    def close(self) -> None:
        self.drop()
        self.renderer = None
        gc.collect()
        if self.window is not None:
            self.window.destroy()
            self.window = None

    # ---- texture slots ----
    def drop(self, *names: str) -> None:
        """Free textures (all of them when no names are given)."""
        freed = False
        for n in (names or list(self._slots)):
            slot = self._slots.pop(n, None)
            if slot:
                slot[0] = None
                freed = True
        if freed:
            gc.collect()

    def _put(self, name: str, key, make) -> Texture:
        """Texture in slot `name` showing make() (a Surface), rebuilt only
        when key changes, and updated in place when the size is unchanged."""
        slot = self._slots.get(name)
        if slot and slot[1] == key:
            return slot[0]
        surf = make()
        if slot and slot[0] is not None and (slot[0].width, slot[0].height) == surf.get_size():
            slot[0].update(surf)
            slot[1] = key
            return slot[0]
        self.drop(name)
        tex = Texture.from_surface(self.renderer, surf)
        self._slots[name] = [tex, key]
        return tex

    def _pattern_texture(self, pat: Pattern) -> Texture:
        def make():
            surf = pygame.Surface(self.size)
            pat.draw(surf, 0)
            return surf
        self.drop("small")
        return self._put("full", ("pattern", id(pat), self.size), make)

    def _overlay_texture(self, lines: list[str]) -> Texture:
        """Fixed-size text box so changing text never allocates."""
        w, h = self.size
        slot = self._slots.get("overlay")
        if slot and slot[1] == ("ovl", tuple(lines), self.size):
            return slot[0]
        font = pygame.font.Font(None, max(16, h // 30))
        lh = font.get_linesize() + 2
        box = (w * 3 // 5, lh * 3)

        def make():
            surf = pygame.Surface(box)
            surf.fill((0, 0, 0))
            for i, t in enumerate(lines[:3]):
                surf.blit(font.render(t, True, (255, 255, 255)), (4, i * lh))
            return surf
        return self._put("overlay", ("ovl", tuple(lines), self.size), make)

    def _page_texture(self, title: str, sections: list[tuple[str, list[str]]], page: int) -> Texture:
        key = ("page", title, tuple((t, tuple(b)) for t, b in sections), page, self.size)
        slot = self._slots.get("full")
        if slot and slot[1] == key:
            return slot[0]
        surf, self.pages = layout_text_page(self.size, title, sections, page)
        self.drop("small", "overlay")
        return self._put("full", key, lambda: surf)

    def text_page(self, title: str, sections: list[tuple[str, list[str]]], page: int) -> None:
        self.renderer.blit(self._page_texture(title, sections, page), pygame.Rect(0, 0, *self.size))
        self.renderer.present()

    def surface_page(self, surf: "pygame.Surface", key) -> None:
        """Show a CPU-drawn surface scaled to the full screen. The texture
        is only re-uploaded when key changes."""
        if "full" in self._slots:
            self.drop("full", "overlay")   # make room: the pattern isn't shown now
        tex = self._put("small", ("surf", key), lambda: surf)
        self.renderer.blit(tex, pygame.Rect(0, 0, *self.size))
        self.renderer.present()

    def solid(self, white: bool) -> None:
        """Full-screen white or black frame (lip-sync flashes)."""
        if self._slots:
            self.drop()   # the camera needs GPU memory too
        r = self.renderer
        r.draw_color = (255, 255, 255, 255) if white else (0, 0, 0, 255)
        r.clear()
        r.present()

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


def layout_text_page(size, title: str, sections: list[tuple[str, list[str]]], page: int):
    """A full-screen text page (the EDID view) laid out in columns.
    Returns (surface, number of pages)."""
    w, h = size
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
    pages = max(1, -(-len(cols) // ncol))
    page %= pages
    surf = pygame.Surface(size)
    surf.fill((8, 12, 24))
    t = title + (f"   (page {page + 1}/{pages}, < > to turn)" if pages > 1 else "")
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
    return surf, pages
