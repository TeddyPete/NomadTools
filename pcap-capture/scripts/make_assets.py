"""Regenerate the app icon and store screenshots.
Run from pcap-capture/:  python3 scripts/make_assets.py"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp()
os.environ["NOMAD_CAPTURE_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.getcwd())
import pygame  # noqa: E402

from nomadcap.demo import render_screens  # noqa: E402


def icon(size: int) -> pygame.Surface:
    s = pygame.Surface((size, size))
    s.fill((16, 20, 28))
    u = size / 100
    # packets flowing along a wire into a record dot
    pygame.draw.rect(s, (90, 100, 120), (int(8 * u), int(62 * u), int(64 * u), max(2, int(3 * u))))
    colors = [(30, 90, 200), (18, 160, 70), (30, 90, 200), (18, 160, 70)]
    heights = [22, 34, 16, 28]
    for i, (c, h) in enumerate(zip(colors, heights)):
        x = int((10 + i * 15) * u)
        pygame.draw.rect(s, c, (x, int((62 - h) * u), int(11 * u), int(h * u)), border_radius=max(1, int(2 * u)))
    pygame.draw.circle(s, (220, 40, 40), (int(80 * u), int(58 * u)), int(13 * u))
    pygame.draw.circle(s, (255, 255, 255), (int(80 * u), int(58 * u)), int(13 * u), max(1, int(2 * u)))
    font = pygame.font.Font(None, int(size * 0.26))
    txt = font.render("Nomad", True, (255, 255, 255))
    s.blit(txt, txt.get_rect(center=(size // 2, int(size * 0.15))))
    font2 = pygame.font.Font(None, int(size * 0.22))
    txt = font2.render("PCAP", True, (110, 220, 120))
    s.blit(txt, txt.get_rect(center=(size // 2, int(size * 0.85))))
    return s


pygame.init()
# icon: branding/nomad_icons.py (Nomad 3D style), not drawn here
tmp = tempfile.mkdtemp()
render_screens(tmp)
os.makedirs("screenshots", exist_ok=True)
for n in range(8):
    shutil.copy(os.path.join(tmp, f"lcd_{n}.png"), f"screenshots/lcd_{n}.png")
shutil.rmtree(tmp)
print("icon and screenshots written")
