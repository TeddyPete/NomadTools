"""Small line icons in the Ask Elmer style, drawn with pygame (no image files),
so they stay crisp at any size: the home menu and the number-key bar.

draw(surf, name, cx, cy, size, color)
"""
from __future__ import annotations

import math

import pygame


def _w(size):
    return max(1, round(size / 9))


def draw(surf, name: str, cx: float, cy: float, size: int, color) -> None:
    fn = ICONS.get(name)
    if fn:
        fn(surf, cx, cy, size / 2, color, _w(size))


def _line(s, c, pts, w):
    pygame.draw.lines(s, c, False, [(round(x), round(y)) for x, y in pts], w)


def gear(s, x, y, r, c, w):
    pts = []
    for i in range(16):
        a = math.radians(i * 22.5)
        rr = r * (0.95 if i % 2 == 0 else 0.7)
        pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
    pygame.draw.polygon(s, c, [(round(a), round(b)) for a, b in pts], w)
    pygame.draw.circle(s, c, (round(x), round(y)), max(2, round(r * 0.28)), w)


def bubble(s, x, y, r, c, w):
    pygame.draw.rect(s, c, (round(x - r), round(y - r * 0.7), round(2 * r), round(r * 1.25)), w,
                     border_radius=max(2, round(r * 0.35)))
    pygame.draw.polygon(s, c, [(x - r * 0.35, y + r * 0.55), (x - r * 0.7, y + r), (x - r * 0.05, y + r * 0.55)])
    for k in (-0.5, 0.05, 0.5):
        pygame.draw.circle(s, c, (round(x + k * r), round(y - r * 0.08)), max(1, round(r * 0.12)))


def history(s, x, y, r, c, w):
    pygame.draw.arc(s, c, (x - r * 0.85, y - r * 0.85, r * 1.7, r * 1.7), math.radians(-200), math.radians(110), w)
    _line(s, c, [(x, y - r * 0.5), (x, y), (x + r * 0.4, y + r * 0.25)], w)
    pygame.draw.polygon(s, c, [(x - r * 0.95, y - r * 0.55), (x - r * 0.55, y - r * 0.15), (x - r, y - r * 0.05)])


def band(s, x, y, r, c, w):
    # a band bar with segments and a marker
    pygame.draw.rect(s, c, (round(x - r), round(y - r * 0.25), round(2 * r), max(2, round(r * 0.5))), 1)
    pygame.draw.rect(s, c, (round(x - r * 0.4), round(y - r * 0.25), round(r * 0.9), max(2, round(r * 0.5))))
    pygame.draw.polygon(s, c, [(x + r * 0.2, y - r * 0.4), (x - r * 0.1, y - r * 0.95), (x + r * 0.5, y - r * 0.95)])
    _line(s, c, [(x + r * 0.2, y - r * 0.4), (x + r * 0.2, y + r * 0.8)], 1)


def rf(s, x, y, r, c, w):
    # a sine wave over a resistor zigzag
    pts = [(x - r + 2 * r * i / 16, y - r * 0.45 - r * 0.4 * math.sin(i / 16 * 2 * math.pi)) for i in range(17)]
    _line(s, c, pts, w)
    z = [(x - r, y + r * 0.55), (x - r * 0.6, y + r * 0.55)]
    for i in range(5):
        z.append((x - r * 0.5 + i * r * 0.22, y + r * (0.25 if i % 2 == 0 else 0.85)))
    z += [(x + r * 0.6, y + r * 0.55), (x + r, y + r * 0.55)]
    _line(s, c, z, w)


def where(s, x, y, r, c, w):
    # a map pin
    cy = y - r * 0.3
    pygame.draw.circle(s, c, (round(x), round(cy)), round(r * 0.6), w)
    pygame.draw.polygon(s, c, [(x - r * 0.5, cy + r * 0.3), (x + r * 0.5, cy + r * 0.3), (x, y + r)])
    pygame.draw.circle(s, c, (round(x), round(cy)), max(1, round(r * 0.2)))


def sun(s, x, y, r, c, w):
    pygame.draw.circle(s, c, (round(x), round(y)), round(r * 0.42), w)
    for i in range(8):
        a = math.radians(i * 45)
        _line(s, c, [(x + r * 0.62 * math.cos(a), y + r * 0.62 * math.sin(a)),
                     (x + r * 0.95 * math.cos(a), y + r * 0.95 * math.sin(a))], w)


def sat(s, x, y, r, c, w):
    # a body and two solar panels along a diagonal
    k = 0.7071
    pygame.draw.polygon(s, c, [(x - r * 0.28, y), (x, y - r * 0.28), (x + r * 0.28, y), (x, y + r * 0.28)])
    for d in (-1, 1):
        cx, cy = x + d * r * 0.66, y - d * r * 0.66
        a_, b_ = r * 0.32, r * 0.2
        pts = []
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pts.append((cx + su * a_ * k + sv * b_ * k, cy - su * a_ * k + sv * b_ * k))
        pygame.draw.polygon(s, c, pts, w)


def park(s, x, y, r, c, w):
    # a pine tree on a hill
    pygame.draw.polygon(s, c, [(x, y - r), (x - r * 0.55, y + r * 0.35), (x + r * 0.55, y + r * 0.35)])
    _line(s, c, [(x, y + r * 0.35), (x, y + r * 0.8)], w)
    _line(s, c, [(x - r, y + r * 0.85), (x + r, y + r * 0.85)], 1)


def clock(s, x, y, r, c, w):
    pygame.draw.circle(s, c, (round(x), round(y)), round(r * 0.9), w)
    _line(s, c, [(x, y - r * 0.6), (x, y), (x + r * 0.45, y + r * 0.2)], w)


def book(s, x, y, r, c, w):
    for d in (-1, 1):
        pygame.draw.polygon(s, c, [(x, y - r * 0.55), (x + d * r * 0.95, y - r * 0.8), (x + d * r * 0.95, y + r * 0.6),
                                   (x, y + r * 0.85)], w)
    _line(s, c, [(x, y - r * 0.55), (x, y + r * 0.85)], 1)


def refresh(s, x, y, r, c, w):
    pygame.draw.arc(s, c, (x - r * 0.75, y - r * 0.75, r * 1.5, r * 1.5), math.radians(40), math.radians(320), w)
    a = math.radians(40)
    tip = (x + r * 0.75 * math.cos(a), y - r * 0.75 * math.sin(a))
    pygame.draw.polygon(s, c, [tip, (tip[0] - r * 0.5, tip[1] - r * 0.05), (tip[0] + r * 0.05, tip[1] + r * 0.5)])


def plus(s, x, y, r, c, w):
    _line(s, c, [(x - r * 0.75, y), (x + r * 0.75, y)], w + 1)
    _line(s, c, [(x, y - r * 0.75), (x, y + r * 0.75)], w + 1)


def minus(s, x, y, r, c, w):
    _line(s, c, [(x - r * 0.75, y), (x + r * 0.75, y)], w + 1)


def back(s, x, y, r, c, w):
    _line(s, c, [(x + r * 0.5, y - r * 0.8), (x - r * 0.3, y), (x + r * 0.5, y + r * 0.8)], w + 1)


def search(s, x, y, r, c, w):
    pygame.draw.circle(s, c, (round(x - r * 0.2), round(y - r * 0.2)), round(r * 0.55), w)
    _line(s, c, [(x + r * 0.2, y + r * 0.2), (x + r * 0.85, y + r * 0.85)], w + 1)


def gps(s, x, y, r, c, w):
    pygame.draw.circle(s, c, (round(x), round(y)), round(r * 0.55), w)
    pygame.draw.circle(s, c, (round(x), round(y)), max(1, round(r * 0.15)))
    for a, b in (((0, -1), (0, -0.55)), ((0, 1), (0, 0.55)), ((-1, 0), (-0.55, 0)), ((1, 0), (0.55, 0))):
        _line(s, c, [(x + r * a[0], y + r * a[1]), (x + r * b[0], y + r * b[1])], w)


def bell(s, x, y, r, c, w):
    pygame.draw.polygon(s, c, [(x - r * 0.7, y + r * 0.5), (x - r * 0.5, y - r * 0.4), (x, y - r * 0.8),
                               (x + r * 0.5, y - r * 0.4), (x + r * 0.7, y + r * 0.5)], w)
    pygame.draw.circle(s, c, (round(x), round(y + r * 0.75)), max(1, round(r * 0.18)))


def mountain(s, x, y, r, c, w):
    pygame.draw.polygon(s, c, [(x - r, y + r * 0.7), (x - r * 0.2, y - r * 0.7), (x + r * 0.2, y - r * 0.1),
                               (x + r * 0.45, y - r * 0.4), (x + r, y + r * 0.7)], w)


def chart(s, x, y, r, c, w):
    _line(s, c, [(x - r, y - r), (x - r, y + r * 0.8), (x + r, y + r * 0.8)], 1)
    pts = [(x - r * 0.9 + r * 1.8 * i / 10, y + r * 0.4 - r * 0.9 * math.sin(i / 10 * math.pi)) for i in range(11)]
    _line(s, c, pts, w)


ICONS = {"band": band, "rf": rf, "where": where, "sun": sun, "sat": sat, "park": park, "clock": clock,
         "ref": book, "gear": gear, "about": bubble, "refresh": refresh, "plus": plus, "minus": minus,
         "back": back, "search": search, "gps": gps, "bell": bell, "mountain": mountain, "chart": chart,
         "history": history}
