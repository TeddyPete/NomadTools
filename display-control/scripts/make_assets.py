"""Regenerate the store screenshots (icon: branding/make_icons.py style).
Run from display-control/:  python3 scripts/make_assets.py"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.getcwd())

from tntdisp.demo import render_screens  # noqa: E402

tmp = tempfile.mkdtemp()
render_screens(tmp)
os.makedirs("screenshots", exist_ok=True)
for n in range(5):
    shutil.copy(os.path.join(tmp, f"lcd_{n}.png"), f"screenshots/lcd_{n}.png")
shutil.rmtree(tmp)
print("screenshots written")
