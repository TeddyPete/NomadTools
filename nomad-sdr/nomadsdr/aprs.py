"""APRS receive: the FM channel goes to multimon-ng (AFSK1200 decoder), and
every decoded packet is shown here and handed to Rig Companion, so its APRS
list, inbox, weather page and station map fill up from the SDR too.

Rig Companion keeps its packets in ~/.config/rig-companion-zero/station.sqlite3.
When Rig Companion is installed we use its own decoder and store (same
GPL-3.0 repository), so packets look exactly like ones from the TH-D75.
Without it, packets are kept in ~/.local/share/nomad-sdr/aprs.log.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from . import dsp
from .settings import data_dir

APRS_MHZ = 144.390
RIG_LIB = "/usr/share/APPLaunch/lib/rig-companion-zero"
RIG_DIR = Path.home() / ".config" / "rig-companion-zero"
_TNC2 = re.compile(r"^([A-Z0-9-]{1,9})>([A-Z0-9-]{1,9})((?:,[A-Za-z0-9*-]{1,10})*):(.*)$")


def parse_tnc2(line: str):
    m = _TNC2.match(line.strip())
    if not m:
        return None
    return m[1], m[2], m[3].lstrip(","), m[4]


def _ddmm(v: str, hemi: str) -> float | None:
    try:
        deg = int(v[:-5]) if len(v) > 5 else 0
        mins = float(v[-5:].replace(" ", "0"))
    except ValueError:
        return None
    x = deg + mins / 60
    return -x if hemi in "SW" else x


def position(info: str):
    """(lat, lon) from a plain or timestamped uncompressed position, else None.
    Rig Companion's decoder (when installed) handles compressed and Mic-E."""
    body = info
    if body[:1] in "/@" and len(body) > 8:
        body = "!" + body[8:]
    if body[:1] in "!=" and len(body) >= 19:
        lat, lon = body[1:9], body[10:19]
        la = _ddmm(lat[:-1], lat[-1])
        lo = _ddmm(lon[:-1], lon[-1])
        if la is not None and lo is not None and abs(la) <= 90 and abs(lo) <= 180:
            return la, lo
    return None


def distance_km(a, b) -> tuple[float, float]:
    """Great-circle distance (km) and bearing (deg) from a to b."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 +
                                math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return d * 6371.0, (math.degrees(math.atan2(y, x)) + 360) % 360


class RigLink:
    """Writes packets into Rig Companion's store (if it is installed)."""

    def __init__(self):
        self.store = None
        self.inspect = None
        self.error = ""
        if os.path.isdir(os.path.join(RIG_LIB, "rigzero")):
            try:
                if RIG_LIB not in sys.path:
                    sys.path.append(RIG_LIB)
                from rigzero.protocol import inspect_packet   # type: ignore
                from rigzero.storage import Store             # type: ignore
                self.inspect = inspect_packet
                self.store = Store(RIG_DIR)
            except Exception as e:   # noqa: BLE001  Rig Companion is optional
                self.error = f"Rig Companion link: {e}"
                self.store = None

    @property
    def ok(self) -> bool:
        return self.store is not None

    def packet(self, src, dst, path, info) -> dict | None:
        if not self.inspect:
            return None
        p = self.inspect(src, dst, path, info, "RX")
        p["via"] = "Nomad SDR"
        return p

    def record(self, p: dict) -> None:
        if self.store:
            try:
                self.store.record(p)
            except Exception as e:   # noqa: BLE001
                self.error = str(e)

    def close(self) -> None:
        if self.store:
            try:
                self.store.close()
            except Exception:   # noqa: BLE001
                pass
            self.store = None


class Aprs:
    """multimon-ng fed with the FM discriminator output (resampled to 22050)."""

    def __init__(self, to_rig: bool = True):
        self.proc = None
        self.packets: deque = deque(maxlen=200)
        self.count = 0
        self.error = ""
        self.rig = RigLink() if to_rig else None
        self.res = dsp.Resampler(dsp.AF, 22050)
        self.lock = threading.Lock()
        self.last_t = 0.0
        self.log = os.path.join(data_dir(), "aprs.log")

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("multimon-ng"))

    def start(self) -> bool:
        if self.proc:
            return True
        exe = shutil.which("multimon-ng")
        if not exe:
            self.error = "multimon-ng is missing (it comes with the package)"
            return False
        self.proc = subprocess.Popen([exe, "-q", "-t", "raw", "-a", "AFSK1200", "-A", "-"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=False, bufsize=0)
        threading.Thread(target=self._reader, daemon=True).start()
        return True

    def feed(self, flat: np.ndarray) -> None:
        """Called by the radio thread with each block of FM audio."""
        p = self.proc
        if not p:
            return
        x = self.res(flat)
        try:
            p.stdin.write(np.clip(x * 20000, -32767, 32767).astype("<i2").tobytes())
        except (BrokenPipeError, OSError, ValueError):
            self.error = "APRS decoder stopped"
            self.proc = None

    def _reader(self) -> None:
        p = self.proc
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("latin-1").strip()
            if line.startswith("APRS: "):
                self.add_line(line[6:])

    def add_line(self, tnc2: str) -> dict | None:
        t = parse_tnc2(tnc2)
        if not t:
            return None
        src, dst, path, info = t
        p = None
        if self.rig and self.rig.ok:
            try:
                p = self.rig.packet(src, dst, path, info)
            except Exception:   # noqa: BLE001
                p = None
        if p:
            self.rig.record(p)
        else:
            p = {"source": src, "sender": src, "destination": dst, "path": path, "info": info,
                 "kind": "Packet", "decoded": {}}
        pos = position(info)
        dec = p.get("decoded") or {}
        if "lat" in dec:
            pos = (dec["lat"], dec["lon"])
        entry = {"t": time.time(), "src": p.get("sender") or src, "dst": dst, "path": path,
                 "info": info, "kind": p.get("kind", "Packet"), "pos": pos,
                 "text": p.get("text", info), "raw": tnc2}
        with self.lock:
            self.packets.appendleft(entry)
            self.count += 1
            self.last_t = entry["t"]
        try:
            os.makedirs(os.path.dirname(self.log), exist_ok=True)
            with open(self.log, "a") as f:
                f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime(entry["t"])) + tnc2 + "\n")
        except OSError:
            pass
        return entry

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if p:
            try:
                p.stdin.close()
            except OSError:
                pass
            try:
                p.terminate()
                p.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass

    def close(self) -> None:
        self.stop()
        if self.rig:
            self.rig.close()
