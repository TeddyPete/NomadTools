"""Draws the Ask Elmer app icons: the Ask Elmer mark (a speech bubble holding
dit dah dit) on the navy tile, with the app name in amber underneath.

  python3 scripts/make_icon.py "ANTENNA LAB" packaging/icon.png packaging/icon_100.png

Colours from askelmer art/brand: navy #13324B, amber #E8A33D, mist #E8EEF3.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

NAVY, AMBER, MIST = (0x13, 0x32, 0x4B), (0xE8, 0xA3, 0x3D), (0xE8, 0xEE, 0xF3)
# Ask Elmer display font (Barlow Condensed, bundled), else DejaVu Sans Bold
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "elmermorse", "fonts", "BarlowCondensed-SemiBold.ttf")
if not os.path.exists(FONT):
    FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def draw(label: str, size: int = 256) -> pygame.Surface:
    S = 4                       # supersample
    W = size * S
    s = pygame.Surface((W, W), pygame.SRCALPHA)
    pygame.draw.rect(s, NAVY, (0, 0, W, W), border_radius=int(W * 26 / 120))
    # bubble, from icon.svg (viewBox 120), scaled into the top part of the tile
    k = W / 120 * 0.78
    ox, oy = (W - 88 * k) / 2 - 16 * k, W * 0.06 - 24 * k + 10 * S

    def P(x, y):
        return (ox + x * k, oy + y * k)
    body = pygame.Rect(*P(16, 24), 88 * k, 56 * k)
    pygame.draw.rect(s, MIST, body, border_radius=int(16 * k))
    pygame.draw.polygon(s, MIST, [P(52, 79), P(30, 98), P(35, 79)])
    pygame.draw.circle(s, AMBER, P(33, 52), 6.5 * k)
    pygame.draw.rect(s, AMBER, (*P(45, 45.5), 25 * k, 13 * k), border_radius=int(6.5 * k))
    pygame.draw.circle(s, NAVY, P(88, 52), 6.5 * k)
    # app name
    pygame.font.init()
    fs = int(W * 0.21)
    font = pygame.font.Font(FONT if os.path.exists(FONT) else None, fs)
    img = font.render(label, True, AMBER)
    while img.get_width() > W * 0.86 and fs > 10:
        fs -= 4
        font = pygame.font.Font(FONT if os.path.exists(FONT) else None, fs)
        img = font.render(label, True, AMBER)
    s.blit(img, ((W - img.get_width()) // 2, int(W * 0.86) - img.get_height()))
    return pygame.transform.smoothscale(s, (size, size))


def main(argv):
    label, out = argv[0], argv[1]
    pygame.image.save(draw(label, 256), out)
    if len(argv) > 2:
        pygame.image.save(draw(label, 100), argv[2])


if __name__ == "__main__":
    main(sys.argv[1:])
