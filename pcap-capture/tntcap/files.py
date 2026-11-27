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


def recover(root: str) -> None:
    """Ring-buffer files left as name.pcapN by a power cut or crash: give
    them a .pcap name (oldest first) so they show up and open in Wireshark."""
    import re
    try:
        names = os.listdir(root)
    except OSError:
        return
    groups: dict = {}
    for n in names:
        m = re.fullmatch(r"(.+)\.pcap(\d+)", n)
        if m:
            groups.setdefault(m.group(1), []).append(os.path.join(root, n))
    for base, paths in groups.items():
        paths.sort(key=lambda p: (os.path.getmtime(p), p))
        for i, p in enumerate(paths, 1):
            dst = os.path.join(root, f"{base}_part{i:02d}.pcap")
            if not os.path.exists(dst):
                try:
                    os.replace(p, dst)
                except OSError:
                    pass


def listing(root: str = None, include_live: bool = False) -> list[Saved]:
    root = root or C.ROOT
    out = []
    live = set((C.running() or {}).get("files") or [])
    if not live:
        recover(root)
    try:
        names = os.listdir(root)
    except OSError:
        return []
    for n in names:
        p = os.path.join(root, n)
        if not n.endswith(".pcap") or (p in live and not include_live):
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
        if p in live:
            meta = dict(meta, recording=True)
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


def copy_all(mnt: str, progress=None) -> tuple[int, int, int]:
    """Copy every saved capture not already on the stick (same name and size).
    Returns (copied, skipped, bytes)."""
    d = os.path.join(mnt, "TNT-Captures")
    os.makedirs(d, exist_ok=True)
    todo = []
    skipped = 0
    for s in listing():
        dst = os.path.join(d, s.name)
        if os.path.exists(dst) and os.path.getsize(dst) == s.size:
            skipped += 1
        else:
            todo.append(s)
    need = sum(s.size for s in todo)
    if shutil.disk_usage(mnt).free < need + 1_000_000:
        raise RuntimeError(f"Not enough space on the USB stick ({nice_size(need)} needed).")
    done = 0
    for i, s in enumerate(todo, 1):
        if progress:
            progress(f"{i}/{len(todo)} {s.label()}")
        copy_to(s, mnt)
        done += s.size
    os.sync()
    return len(todo), skipped, done


def not_on_stick(mnt: str) -> list[Saved]:
    d = os.path.join(mnt, "TNT-Captures")
    out = []
    for s in listing():
        dst = os.path.join(d, s.name)
        if not (os.path.exists(dst) and os.path.getsize(dst) == s.size):
            out.append(s)
    return out
