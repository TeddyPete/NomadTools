"""Roku TVs and players: External Control Protocol (HTTP, port 8060).

No pairing. On newer Roku OS, Settings > System > Advanced system settings >
Control by mobile apps must be "Enabled" (not "Limited") for power and
input keys.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .base import DisplayError, Driver
from . import wol

FIXED_INPUTS = [("InputHDMI1", "HDMI 1"), ("InputHDMI2", "HDMI 2"), ("InputHDMI3", "HDMI 3"),
                ("InputHDMI4", "HDMI 4"), ("InputTuner", "TV tuner"), ("InputAV1", "AV")]


class Roku(Driver):
    kind = "roku"
    default_port = 8060
    caps = frozenset({"power", "input", "volume", "mute", "info"})

    def _get(self, path: str) -> bytes:
        try:
            with urllib.request.urlopen(f"http://{self.d.host}:{self.port}{path}", timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise DisplayError("Roku blocks control: set Control by mobile apps to Enabled")
            raise DisplayError(f"Roku error HTTP {e.code}")
        except OSError as e:
            raise DisplayError(f"No answer from {self.d.host} ({e.__class__.__name__})")

    def key(self, name: str) -> None:
        req = urllib.request.Request(f"http://{self.d.host}:{self.port}/keypress/{name}", b"", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                r.read()
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise DisplayError("Roku blocks control: set Control by mobile apps to Enabled")
            raise DisplayError(f"Roku error HTTP {e.code}")
        except OSError as e:
            raise DisplayError(f"No answer from {self.d.host} ({e.__class__.__name__})")

    def device_info(self) -> dict:
        root = ET.fromstring(self._get("/query/device-info"))
        return {c.tag: (c.text or "") for c in root}

    def status(self):
        try:
            di = self.device_info()
        except DisplayError as e:
            if "No answer" in str(e):
                return {"power": "off", "input": "", "volume": None, "mute": None}
            raise
        pm = di.get("power-mode", "")
        st = {"power": {"PowerOn": "on", "DisplayOff": "standby", "Ready": "standby",
                        "Headless": "on"}.get(pm, pm.lower() or "unknown"),
              "input": "", "volume": None, "mute": None}
        try:
            root = ET.fromstring(self._get("/query/active-app"))
            app = root.find("app")
            if app is not None:
                st["input"] = app.text or app.get("id", "")
        except (DisplayError, ET.ParseError):
            pass
        return st

    def power(self, on):
        try:
            self.key("PowerOn" if on else "PowerOff")
        except DisplayError:
            if on and self.d.mac:
                wol.wake(self.d.mac, self.d.host)
                return "Wake-on-LAN sent"
            raise
        return "Power on sent" if on else "Power off sent"

    def inputs(self):
        try:
            root = ET.fromstring(self._get("/query/apps"))
            tv = [(a.get("id", ""), a.text or a.get("id", "")) for a in root.findall("app") if a.get("type") == "tvin"]
        except (DisplayError, ET.ParseError):
            tv = []
        if tv:
            return [("launch:" + i, n) for i, n in tv]
        return list(FIXED_INPUTS)

    def set_input(self, input_id):
        if input_id.startswith("launch:"):
            app = input_id[7:]
            req = urllib.request.Request(f"http://{self.d.host}:{self.port}/launch/{app}", b"", method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    r.read()
            except OSError as e:
                raise DisplayError(f"Roku did not switch ({e.__class__.__name__})")
            return f"Input {app}"
        self.key(input_id)
        return dict(FIXED_INPUTS).get(input_id, input_id)

    def volume(self, step):
        for _ in range(abs(step)):
            self.key("VolumeUp" if step > 0 else "VolumeDown")
        return "Volume up" if step > 0 else "Volume down"

    def mute(self, on=None):
        self.key("VolumeMute")
        return "Mute toggled"

    def info(self):
        out = super().info()
        di = self.device_info()
        for label, k in (("Name", "friendly-device-name"), ("Model", "model-name"), ("Model no.", "model-number"),
                         ("Serial", "serial-number"), ("Software", "software-version"), ("Is TV", "is-tv"),
                         ("Wi-Fi MAC", "wifi-mac"), ("Ethernet MAC", "ethernet-mac"), ("Power", "power-mode")):
            if di.get(k):
                out.append((label, di[k]))
        return out


def mac_from_info(di: dict) -> str:
    for k in ("ethernet-mac", "wifi-mac"):
        v = di.get(k, "")
        if re.fullmatch(r"[0-9a-fA-F:]{17}", v) and v != "00:00:00:00:00:00":
            return v.lower()
    return ""
