"""Regenerate the app icon and store screenshots.
Run from net-tools/:  python3 scripts/make_assets.py"""
import math
import os
import shutil
import subprocess
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402


def icon(size: int) -> pygame.Surface:
    s = pygame.Surface((size, size))
    s.fill((150, 30, 20))
    c = size / 2
    r = size * 0.27
    nodes = [(c + r * math.cos(a), size * 0.40 + r * 0.8 * math.sin(a))
             for a in [i * 2 * math.pi / 5 - math.pi / 2 for i in range(5)]]
    hub = (c, size * 0.40)
    for n in nodes:
        pygame.draw.line(s, (255, 214, 110), hub, n, max(2, size // 40))
    for n in nodes:
        pygame.draw.circle(s, (255, 255, 255), n, size * 0.06)
    pygame.draw.circle(s, (255, 214, 110), hub, size * 0.09)
    font = pygame.font.Font(None, int(size * 0.30))
    txt = font.render("TNT NET", True, (255, 255, 255))
    s.blit(txt, txt.get_rect(center=(c, size * 0.84)))
    return s


pygame.font.init()
pygame.image.save(icon(256), "packaging/icon.png")
pygame.image.save(icon(100), "packaging/icon_100.png")
tmp = tempfile.mkdtemp()
subprocess.run([sys.executable, "-m", "tntnet.app", "--shots", tmp], check=True)
os.makedirs("screenshots", exist_ok=True)
for n in range(3):
    shutil.copy(os.path.join(tmp, f"lcd_{n}.png"), f"screenshots/lcd_{n}.png")
shutil.rmtree(tmp)
print("icon and screenshots written")
