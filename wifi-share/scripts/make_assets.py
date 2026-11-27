"""Regenerate the app icon and store screenshots.
Run from wifi-share/:  python3 scripts/make_assets.py"""
import math
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.getcwd())
import pygame  # noqa: E402

from tntshare.demo import render_screens  # noqa: E402


def icon(size: int) -> pygame.Surface:
    s = pygame.Surface((size, size))
    s.fill((16, 20, 28))
    cx, cy = size // 2, int(size * 0.60)
    orange = (235, 90, 40)
    for i, r in enumerate((0.16, 0.29, 0.42)):
        rad = int(size * r)
        thick = max(2, size // 16)
        pts_out, pts_in = [], []
        for k in range(41):
            a = math.radians(45 + 90 * k / 40)
            pts_out.append((cx + rad * math.cos(a), cy - rad * math.sin(a)))
            pts_in.append((cx + (rad - thick) * math.cos(a), cy - (rad - thick) * math.sin(a)))
        pygame.draw.polygon(s, orange, pts_out + pts_in[::-1])
    pygame.draw.circle(s, orange, (cx, cy), max(3, size // 18))
    # Ethernet jack below
    w, h = int(size * 0.36), int(size * 0.18)
    jack = pygame.Rect(cx - w // 2, int(size * 0.70), w, h)
    pygame.draw.rect(s, (220, 220, 220), jack, max(2, size // 40))
    tab = pygame.Rect(cx - w // 6, jack.bottom - max(2, size // 40), w // 3, h // 3)
    pygame.draw.rect(s, (220, 220, 220), tab)
    font = pygame.font.Font(None, int(size * 0.26))
    txt = font.render("TNT", True, (255, 255, 255))
    s.blit(txt, txt.get_rect(center=(cx, int(size * 0.13))))
    return s


pygame.init()
pygame.image.save(icon(256), "packaging/icon.png")
pygame.image.save(icon(100), "packaging/icon_100.png")
tmp = tempfile.mkdtemp()
render_screens(tmp)
os.makedirs("screenshots", exist_ok=True)
for n in range(4):
    shutil.copy(os.path.join(tmp, f"lcd_{n}.png"), f"screenshots/lcd_{n}.png")
shutil.rmtree(tmp)
print("icon and screenshots written")
