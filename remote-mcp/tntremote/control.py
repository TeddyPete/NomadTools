"""Turn the server on/off (systemd user service) and set up the tunnel."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import urllib.request

from . import config as C

RELEASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"


def _systemctl(*args: str) -> tuple[int, str]:
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    try:
        p = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def is_on() -> bool:
    return _systemctl("is-active", "--quiet", C.SERVICE)[0] == 0


def set_on(on: bool) -> str:
    """On = start now and at every boot. Off = stop now and stay off."""
    if on:
        rc, out = _systemctl("enable", "--now", C.SERVICE)
    else:
        rc, out = _systemctl("disable", "--now", C.SERVICE)
    return "" if rc == 0 else (out or "systemctl failed")


def restart() -> str:
    if not is_on():
        return ""
    rc, out = _systemctl("restart", C.SERVICE)
    return "" if rc == 0 else out


def cloudflared_path() -> str:
    if os.access(C.CLOUDFLARED, os.X_OK):
        return C.CLOUDFLARED
    return shutil.which("cloudflared") or ""


def cloudflared_version() -> str:
    b = cloudflared_path()
    if not b:
        return ""
    try:
        out = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=20).stdout
        return out.split("version", 1)[1].split()[0] if "version" in out else out.strip()[:30]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "?"


def install_cloudflared(log=print) -> str:
    """Download Cloudflare's cloudflared into ~/.local/lib/tnt-remote (no root needed)."""
    m = platform.machine()
    arch = {"aarch64": "arm64", "arm64": "arm64", "armv7l": "arm", "armv6l": "arm", "x86_64": "amd64"}.get(m)
    if not arch:
        raise RuntimeError(f"unknown CPU type {m}")
    C.ensure_dirs()
    tmp = C.CLOUDFLARED + ".download"
    log("Downloading cloudflared...")
    with urllib.request.urlopen(RELEASE.format(arch=arch), timeout=60) as r, open(tmp, "wb") as f:
        total = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    if total < 5_000_000:
        os.unlink(tmp)
        raise RuntimeError("download looks incomplete")
    os.chmod(tmp, 0o755)
    os.replace(tmp, C.CLOUDFLARED)
    v = cloudflared_version()
    log(f"cloudflared {v} installed")
    return v
