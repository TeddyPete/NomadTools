"""Regenerate the app icon and store screenshots.
Run from av-tester/:  python3 scripts/make_assets.py"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.getcwd())
import pygame  # noqa: E402

from zeroav.app import render_all  # noqa: E402
from zeroav.patterns import BARS_100  # noqa: E402


def icon(size: int) -> pygame.Surface:
    s = pygame.Surface((size, size))
    s.fill((16, 20, 28))
    m = size // 8
    w = size - 2 * m
    bar_h = int(w * 0.55)
    for i, c in enumerate(BARS_100):
        x0 = m + round(i * w / 7)
        x1 = m + round((i + 1) * w / 7)
        s.fill(c, (x0, m, x1 - x0, bar_h))
    font = pygame.font.Font(None, int(size * 0.36))
    txt = font.render("AV", True, (255, 255, 255))
    s.blit(txt, txt.get_rect(center=(size // 2, m + bar_h + (size - m - bar_h - m) // 2 + m // 3)))
    return s


pygame.init()
pygame.image.save(icon(256), "packaging/icon.png")
pygame.image.save(icon(100), "packaging/icon_100.png")
tmp = tempfile.mkdtemp()
render_all(tmp, (1920, 1080))
os.makedirs("screenshots", exist_ok=True)
for n in range(3):
    shutil.copy(os.path.join(tmp, f"lcd_{n}.png"), f"screenshots/lcd_{n}.png")
shutil.rmtree(tmp)
print("icon and screenshots written")
