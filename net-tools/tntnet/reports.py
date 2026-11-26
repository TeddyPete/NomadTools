"""Saved per-site reports: ~/TNT-Net-Reports/<site>/<date-time>-<tool>.txt"""
from __future__ import annotations

import os
import re
import socket
import time

ROOT = os.path.expanduser("~/TNT-Net-Reports")


def clean(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().replace(" ", "_")
    return name[:60] or "No-site"


def site_dir(cfg) -> str:
    return os.path.join(ROOT, clean(cfg.get("site") or "No-site"))


def save(cfg, tool: str, text: str) -> str:
    d = site_dir(cfg)
    os.makedirs(d, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(d, f"{stamp}-{clean(tool)}.txt")
    with open(path, "w") as f:
        f.write(f"TNT AV Net Tools report: {tool}\n")
        f.write(f"Site: {cfg.get('site') or '(not set)'}\n")
        f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
        f.write(f"Device: {socket.gethostname()}\n")
        f.write("TheTechNomad.com\n\n")
        f.write(text.rstrip() + "\n")
    return path


def sites() -> list[str]:
    try:
        return sorted(d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d)))
    except OSError:
        return []


def files(site: str) -> list[str]:
    d = os.path.join(ROOT, site)
    try:
        return sorted((f for f in os.listdir(d) if not f.startswith(".")), reverse=True)
    except OSError:
        return []
