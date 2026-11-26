"""HDMI test patterns, drawn at the output's native resolution.

Each pattern is a class with draw(surface, frame) -> None. Static patterns
ignore `frame`; animated ones (moving box) use it. Patterns are drawn with
pygame primitives and numpy so they work on any resolution.
"""
from __future__ import annotations

import numpy as np
import pygame

# SMPTE-style 75% bars, top row order: white, yellow, cyan, green, magenta, red, blue
BARS_75 = [(191, 191, 191), (191, 191, 0), (0, 191, 191), (0, 191, 0),
           (191, 0, 191), (191, 0, 0), (0, 0, 191)]
BARS_100 = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
            (255, 0, 255), (255, 0, 0), (0, 0, 255)]


class Pattern:
    name = "pattern"
    category = "misc"
    animated = False

    def draw(self, surf: pygame.Surface, frame: int) -> None:  # pragma: no cover
        raise NotImplementedError


def _cols(width: int, n: int) -> list[tuple[int, int]]:
    """Split width into n columns with integer edges: [(x0, w), ...]."""
    edges = [round(i * width / n) for i in range(n + 1)]
    return [(edges[i], edges[i + 1] - edges[i]) for i in range(n)]


class ColorBars(Pattern):
    category = "bars"

    def __init__(self, level: int = 75):
        self.level = level
        self.name = f"Color bars {level}%"
        self.colors = BARS_75 if level == 75 else BARS_100

    def draw(self, surf, frame):
        w, h = surf.get_size()
        surf.fill((0, 0, 0))
        top = int(h * 0.67)
        mid = int(h * 0.75)
        for (x, cw), c in zip(_cols(w, 7), self.colors):
            surf.fill(c, (x, 0, cw, top))
        # reverse castellations: blue, black, magenta, black, cyan, black, white
        v = 191 if self.level == 75 else 255
        rev = [(0, 0, v), (19, 19, 19), (v, 0, v), (19, 19, 19),
               (0, v, v), (19, 19, 19), (v, v, v)]
        for (x, cw), c in zip(_cols(w, 7), rev):
            surf.fill(c, (x, top, cw, mid - top))
        # bottom: -I, white, +Q, black, PLUGE (-4%, 0, +4%), black
        cols = _cols(w, 7)
        x0, cw = cols[0]
        surf.fill((0, 33, 76), (x0, mid, cw, h - mid))
        x1, cw1 = cols[1]
        surf.fill((255, 255, 255), (x1, mid, cw1, h - mid))
        x2, cw2 = cols[2]
        surf.fill((50, 0, 106), (x2, mid, cw2, h - mid))
        x3, cw3 = cols[3]
        surf.fill((19, 19, 19), (x3, mid, cw3, h - mid))
        x4, cw4 = cols[4]
        third = cw4 // 3
        surf.fill((9, 9, 9), (x4, mid, third, h - mid))          # below black
        surf.fill((19, 19, 19), (x4 + third, mid, third, h - mid))
        surf.fill((29, 29, 29), (x4 + 2 * third, mid, cw4 - 2 * third, h - mid))  # above black
        for x, cwx in cols[5:]:
            surf.fill((19, 19, 19), (x, mid, cwx, h - mid))


class Crosshatch(Pattern):
    category = "geometry"

    def __init__(self, divisions: int = 16):
        self.divisions = divisions
        self.name = f"Crosshatch {divisions}"

    def draw(self, surf, frame):
        w, h = surf.get_size()
        surf.fill((0, 0, 0))
        white = (255, 255, 255)
        step = w / self.divisions
        x = 0.0
        while round(x) < w:
            surf.fill(white, (round(x), 0, 1, h))
            x += step
        rows = max(1, round(h / step))
        for i in range(rows + 1):
            y = min(h - 1, round(i * h / rows))
            surf.fill(white, (0, y, w, 1))
        surf.fill(white, (w - 1, 0, 1, h))
        # centre cross and circle
        surf.fill(white, (w // 2 - 1, 0, 2, h))
        surf.fill(white, (0, h // 2 - 1, w, 2))
        pygame.draw.circle(surf, white, (w // 2, h // 2), h // 2 - 2, 1)


class SafeArea(Pattern):
    name = "Safe area / overscan"
    category = "geometry"

    def draw(self, surf, frame):
        w, h = surf.get_size()
        surf.fill((0, 0, 0))
        # 1 px border on the very edge, then 2.5% steps to 10%
        colors = [(255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255), (255, 255, 255)]
        for i, c in enumerate(colors):
            m = i * 0.025
            r = pygame.Rect(round(w * m), round(h * m), round(w * (1 - 2 * m)), round(h * (1 - 2 * m)))
            pygame.draw.rect(surf, c, r, 1)
        _label(surf, "edge  2.5%  5%  7.5%  10%", (w // 2, h // 2))


class Gradient(Pattern):
    category = "gradients"

    def __init__(self, channel: str = "gray", steps: int = 0):
        self.channel = channel
        self.steps = steps
        self.name = f"Ramp {channel}" + (f" {steps} steps" if steps else "")

    def draw(self, surf, frame):
        w, h = surf.get_size()
        ramp = np.linspace(0, 255, w)
        if self.steps:
            ramp = np.floor(np.linspace(0, self.steps - 1e-9, w)) * (255 / (self.steps - 1))
        ramp = ramp.round().astype(np.uint8)
        arr = np.zeros((w, h, 3), dtype=np.uint8)
        mask = {"gray": (1, 1, 1), "red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1)}[self.channel]
        for i, m in enumerate(mask):
            if m:
                arr[:, :, i] = ramp[:, None]
        pygame.surfarray.blit_array(surf, arr)


class Solid(Pattern):
    category = "solids"

    def __init__(self, name: str, color: tuple[int, int, int]):
        self.name = f"Solid {name}"
        self.color = color

    def draw(self, surf, frame):
        surf.fill(self.color)


class Checkerboard(Pattern):
    category = "sharpness"

    def __init__(self, cell: int = 1):
        self.cell = cell
        self.name = f"Checkerboard {cell}px"

    def draw(self, surf, frame):
        w, h = surf.get_size()
        xs = (np.arange(w) // self.cell)[:, None]
        ys = (np.arange(h) // self.cell)[None, :]
        board = (((xs + ys) % 2) * 255).astype(np.uint8)
        pygame.surfarray.blit_array(surf, np.repeat(board[:, :, None], 3, axis=2))


class MovingBox(Pattern):
    """A box moving a fixed number of pixels per frame. Even motion means no
    judder; stutters or uneven steps show dropped or repeated frames."""
    name = "Moving box (judder)"
    category = "motion"
    animated = True

    def __init__(self, px_per_frame: int = 8):
        self.px = px_per_frame

    def draw(self, surf, frame):
        w, h = surf.get_size()
        surf.fill((0, 0, 0))
        size = h // 6
        travel = w - size
        pos = (frame * self.px) % (2 * travel)
        x = pos if pos < travel else 2 * travel - pos
        surf.fill((255, 255, 255), (x, h // 2 - size // 2, size, size))
        # frame-counter strip: one cell lights per frame, cycling 0..9
        cell = w // 10
        surf.fill((255, 0, 0), ((frame % 10) * cell, h - h // 20, cell, h // 20))


def _label(surf, text, center, size_frac=0.04):
    w, h = surf.get_size()
    font = pygame.font.Font(None, max(14, int(h * size_frac)))
    img = font.render(text, True, (255, 255, 255), (0, 0, 0))
    surf.blit(img, img.get_rect(center=center))


def draw_info_overlay(surf, lines: list[str]) -> None:
    """Resolution / timing overlay in the top-left corner."""
    w, h = surf.get_size()
    font = pygame.font.Font(None, max(16, h // 30))
    y = h // 40
    for line in lines:
        img = font.render(line, True, (255, 255, 255), (0, 0, 0))
        surf.blit(img, (w // 40, y))
        y += img.get_height() + 2


class OverscanRuler(Pattern):
    """Bands 1% wide at every edge, labelled 0-4%. The outermost band you
    can see on a side is how many percent the display crops there."""
    name = "Overscan ruler (%)"
    category = "geometry"

    def draw(self, surf, frame):
        w, h = surf.get_size()
        surf.fill((0, 0, 0))
        font = pygame.font.Font(None, max(14, h // 45))
        colors = [(200, 40, 40), (200, 140, 0), (40, 160, 40), (0, 140, 200), (150, 60, 200)]
        for i, c in enumerate(colors):
            px, py = w * i / 100, h * i / 100
            bw, bh = max(1, round(w / 100)), max(1, round(h / 100))
            x0, y0 = round(px), round(py)
            surf.fill(c, (x0, y0, w - 2 * x0, bh))                 # top
            surf.fill(c, (x0, h - y0 - bh, w - 2 * x0, bh))        # bottom
            surf.fill(c, (x0, y0, bw, h - 2 * y0))                 # left
            surf.fill(c, (w - x0 - bw, y0, bw, h - 2 * y0))        # right
        # numbers in a row just inside the bands, each with a lead line to its band
        for i, c in enumerate(colors):
            n = font.render(f"{i}%", True, (255, 255, 255))
            gx, gy = (i - 2) * w // 16, (i - 2) * h // 11
            bx, by = w * (i + 0.5) / 100, h * (i + 0.5) / 100
            for side in ("top", "bottom", "left", "right"):
                if side in ("top", "bottom"):
                    x = w // 2 + gx
                    y_in = h * 0.08 if side == "top" else h * 0.92
                    y_b = by if side == "top" else h - by
                    pygame.draw.line(surf, (255, 255, 255), (x, y_b), (x, y_in), 1)
                    surf.blit(n, (x - n.get_width() // 2, y_in if side == "top" else y_in - n.get_height()))
                else:
                    y = h // 2 + gy
                    x_in = w * 0.06 if side == "left" else w * 0.94
                    x_b = bx if side == "left" else w - bx
                    pygame.draw.line(surf, (255, 255, 255), (x_b, y), (x_in, y), 1)
                    surf.blit(n, (x_in + 2 if side == "left" else x_in - n.get_width() - 2,
                                  y - n.get_height() // 2))
        pygame.draw.rect(surf, (255, 255, 255), (0, 0, w, h), 1)
        _label(surf, "Outermost band you can see = % cropped on that side (0% = nothing cut)", (w // 2, h // 2))


class PixelMap(Pattern):
    """1-pixel border, corner marks and a pixel ruler every 10 px (numbered
    every 100). If the white edge line shows on all four sides with crisp
    single-pixel ticks, the display maps pixels 1:1 with no scaling."""
    name = "Pixel mapping"
    category = "geometry"

    def draw(self, surf, frame):
        w, h = surf.get_size()
        surf.fill((0, 0, 0))
        font = pygame.font.Font(None, max(14, h // 60))
        white, grey = (255, 255, 255), (150, 150, 150)
        pygame.draw.rect(surf, white, (0, 0, w, h), 1)
        for x in range(0, w, 10):
            ln = h // 30 if x % 100 == 0 else h // 90 if x % 50 == 0 else h // 180
            surf.fill(white, (x, 1, 1, ln))
            surf.fill(white, (x, h - 1 - ln, 1, ln))
            if x % 100 == 0 and x:
                img = font.render(str(x), True, grey)
                surf.blit(img, (x + 2, h // 30))
        for y in range(0, h, 10):
            ln = w // 50 if y % 100 == 0 else w // 150 if y % 50 == 0 else w // 300
            surf.fill(white, (1, y, ln, 1))
            surf.fill(white, (w - 1 - ln, y, ln, 1))
            if y % 100 == 0 and y:
                img = font.render(str(y), True, grey)
                surf.blit(img, (w // 50 + 3, y - img.get_height() // 2))
        c = max(8, h // 20)
        for cx, cy, dx, dy in ((0, 0, 1, 1), (w - 1, 0, -1, 1), (0, h - 1, 1, -1), (w - 1, h - 1, -1, -1)):
            pygame.draw.line(surf, (255, 0, 0), (cx + 3 * dx, cy + 3 * dy), (cx + c * dx, cy + 3 * dy))
            pygame.draw.line(surf, (255, 0, 0), (cx + 3 * dx, cy + 3 * dy), (cx + 3 * dx, cy + c * dy))
        # single-pixel line fields in the centre: vertical lines left, horizontal right
        bw, bh = w // 6, h // 6
        x0, y0 = w // 2 - bw - 10, h // 2 + h // 12
        arr = pygame.surfarray.pixels3d(surf)
        arr[x0:x0 + bw:2, y0:y0 + bh] = 255
        arr[w // 2 + 10:w // 2 + 10 + bw, y0:y0 + bh:2] = 255
        del arr
        _label(surf, f"{w} x {h}: white edge on all 4 sides + even line fields = 1:1 pixels",
               (w // 2, h // 2 - h // 10))


class LinePairs(Pattern):
    """Alternating 1 px, 2 px and 3 px black/white line pairs, vertical and
    horizontal, to show scaling, sharpening and chroma loss."""
    name = "Line pairs 1/2/3 px"
    category = "sharpness"

    def draw(self, surf, frame):
        w, h = surf.get_size()
        surf.fill((0, 0, 0))
        arr = pygame.surfarray.pixels3d(surf)
        for i, n in enumerate((1, 2, 3)):
            x0, x1 = i * w // 3, (i + 1) * w // 3
            cols = np.arange(x0, x1)
            on = cols[((cols - x0) // n) % 2 == 0]
            arr[on, : h // 2] = 255
            rows = np.arange(h // 2, h)
            onr = rows[((rows - h // 2) // n) % 2 == 0]
            arr[x0:x1][:, onr] = 255
        del arr
        for i, n in enumerate((1, 2, 3)):
            _label(surf, f"{n} px", (i * w // 3 + w // 6, h // 2))


def all_patterns() -> list[Pattern]:
    return [
        ColorBars(75), ColorBars(100),
        Crosshatch(16), Crosshatch(32), SafeArea(), OverscanRuler(), PixelMap(),
        Gradient("gray"), Gradient("gray", 16), Gradient("red"), Gradient("green"), Gradient("blue"),
        Solid("white", (255, 255, 255)), Solid("black", (0, 0, 0)), Solid("50% gray", (128, 128, 128)),
        Solid("red", (255, 0, 0)), Solid("green", (0, 255, 0)), Solid("blue", (0, 0, 255)),
        Checkerboard(1), Checkerboard(64), LinePairs(),
        MovingBox(8),
    ]
