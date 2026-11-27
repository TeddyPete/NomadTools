"""Jobs and the items scanned into them.

  ~/.config/nomad-label-scanner/settings.json   app settings, current job
  ~/Nomad-Label-Scans/<Job>/items.json          one job's inventory
  ~/Nomad-Label-Scans/<Job>/photos/*.jpg        label photos
  ~/Nomad-Label-Scans/<Job>/<Job>.csv / .xlsx   exports (made on demand)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field, fields

APP = "nomad-label-scanner"


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP)


def data_root() -> str:
    return os.environ.get("NOMAD_SCAN_ROOT") or os.path.join(os.path.expanduser("~"), "Nomad-Label-Scans")


DEFAULTS = {
    "job": "Job 1",
    "ocr": True,             # read printed text too (slower)
    "photo": True,           # keep a photo of each label
    "rotation": 0,           # 0 or 180
    "zoom": 1,
    "room": "",              # sticky room for the next scans
    "auto_find": False,      # look the MAC up on the network after each scan
}


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        with open(os.path.join(config_dir(), "settings.json")) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s: dict) -> None:
    _write_json(os.path.join(config_dir(), "settings.json"), s)


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass
class Item:
    name: str = ""          # what the tech calls it ("Rack 2 DSP")
    model: str = ""
    serial: str = ""
    mac: str = ""
    vendor: str = ""
    ip: str = ""
    room: str = ""
    notes: str = ""
    online: str = ""        # last network check ("online 2 ms", "not found")
    checked: str = ""       # when that check ran
    time: str = ""          # when scanned
    photo: str = ""         # file in photos/
    codes: list = field(default_factory=list)   # raw barcode contents
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]
        if not self.time:
            self.time = time.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def title(self) -> str:
        return self.name or self.model or self.serial or self.mac or self.ip or "(blank)"

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def safe_name(job: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 ._\-]", "", job or "").strip().strip(".")
    return re.sub(r"\s+", "_", s)[:40] or "Job"


def job_dir(job: str) -> str:
    return os.path.join(data_root(), safe_name(job))


def jobs() -> list[str]:
    """Job names, newest first (by items.json time)."""
    root = data_root()
    out = []
    try:
        for d in os.listdir(root):
            p = os.path.join(root, d, "items.json")
            if os.path.isfile(p):
                out.append((os.path.getmtime(p), _job_title(os.path.join(root, d)) or d.replace("_", " ")))
    except OSError:
        pass
    return [n for _, n in sorted(out, reverse=True)]


def _job_title(d: str) -> str:
    try:
        with open(os.path.join(d, "items.json")) as f:
            return json.load(f).get("job", "")
    except (OSError, ValueError, AttributeError):
        return ""


def load(job: str) -> list[Item]:
    try:
        with open(os.path.join(job_dir(job), "items.json")) as f:
            data = json.load(f)
        return [Item.from_dict(d) for d in data.get("items", [])]
    except (OSError, ValueError):
        return []


def save(job: str, items: list[Item]) -> None:
    _write_json(os.path.join(job_dir(job), "items.json"),
                {"job": job, "app": APP, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "items": [asdict(i) for i in items]})


def create(job: str) -> None:
    if not os.path.isfile(os.path.join(job_dir(job), "items.json")):
        save(job, [])


def rename(old: str, new: str) -> bool:
    a, b = job_dir(old), job_dir(new)
    if a != b and os.path.exists(b):
        return False
    items = load(old)
    if a != b and os.path.isdir(a):
        os.rename(a, b)
        for ext in (".csv", ".xlsx"):
            p = os.path.join(b, safe_name(old) + ext)
            if os.path.exists(p):
                os.unlink(p)
    save(new, items)
    return True


def delete(job: str) -> None:
    d = job_dir(job)
    if os.path.realpath(d).startswith(os.path.realpath(data_root()) + os.sep):
        shutil.rmtree(d, ignore_errors=True)


def photo_path(job: str, name: str) -> str:
    return os.path.join(job_dir(job), "photos", name)
