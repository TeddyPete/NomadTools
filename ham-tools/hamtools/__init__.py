"""Ask Elmer Ham Tools for the M5Stack CardputerZero.

The app's name lives here only, so a rename touches one file (plus the packaging).
"""
from __future__ import annotations

import os
import shutil

__version__ = "0.3.2"
APP_NAME = "Ask Elmer Ham Tools"
PKG = "askelmer-ham-tools"
# Packages this app replaces; their settings are carried over on first run.
OLD_PKGS = ("askelmer-shack-tools", "askelmer-antenna-lab")


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, PKG)


def migrate() -> None:
    """First run after the upgrade: copy the old apps' settings and caches (old folders are left alone)."""
    new = config_dir()
    if os.path.isdir(new):
        return
    base = os.path.dirname(new)
    try:
        os.makedirs(new, exist_ok=True)
        shack = os.path.join(base, "askelmer-shack-tools")
        if os.path.isdir(shack):
            for name in os.listdir(shack):
                src = os.path.join(shack, name)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(new, name))
        lab = os.path.join(base, "askelmer-antenna-lab", "state.json")
        if os.path.isfile(lab):
            shutil.copy2(lab, os.path.join(new, "antenna.json"))
    except OSError:
        pass
