"""Saved captures: list, details, delete, copy to a USB drive."""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass

from . import capture as C


@dataclass
class Saved:
    path: str
    size: int
    mtime: float
    meta: dict

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def label(self) -> str:
        """'11-26 14:03 Dante' for the list."""
        t = self.meta.get("started") or self.mtime
        what = self.meta.get("tag") or self.meta.get("preset") or ""
        part = ""
        if "_part" in self.name:
            part = " p" + self.name.rsplit("_part", 1)[1].split(".")[0]
        return f"{time.strftime('%m-%d %H:%M', time.localtime(t))} {what}{part}".strip()


def nice_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") or n >= 100 else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} GB"


def listing(root: str = None) -> list[Saved]:
    root = root or C.ROOT
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return []
    live = set((C.running() or {}).get("files") or [])
    for n in names:
        p = os.path.join(root, n)
        if not n.endswith(".pcap") or p in live:
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        meta = {}
        try:
            with open(C.meta_path(p)) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            pass
        out.append(Saved(p, st.st_size, st.st_mtime, meta))
    out.sort(key=lambda s: s.mtime, reverse=True)
    return out


def delete(s: Saved) -> None:
    for p in (s.path, C.meta_path(s.path)):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def usb_drives() -> list[str]:
    """Mounted removable drives (USB sticks) we can write to."""
    out = []
    try:
        lines = open("/proc/mounts").read().splitlines()
    except OSError:
        return []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mnt = parts[1].replace("\\040", " ")
        if parts[2] in ("vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "ext4", "ext3") and \
                (mnt.startswith("/media/") or mnt.startswith("/mnt/") or mnt.startswith("/run/media/")):
            if os.access(mnt, os.W_OK):
                out.append(mnt)
    return out


def copy_to(s: Saved, mnt: str) -> str:
    d = os.path.join(mnt, "TNT-Captures")
    os.makedirs(d, exist_ok=True)
    if shutil.disk_usage(mnt).free < s.size + 1_000_000:
        raise RuntimeError("Not enough space on the USB drive.")
    dst = os.path.join(d, s.name)
    shutil.copyfile(s.path, dst)
    if os.path.exists(C.meta_path(s.path)):
        shutil.copyfile(C.meta_path(s.path), dst + ".json")
    os.sync()
    return dst


def total_size(root: str = None) -> int:
    return sum(s.size for s in listing(root))
