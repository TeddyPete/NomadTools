"""Sony Bravia professional / consumer TVs: IP control REST API on port 80.

On the TV: Network > Home network > IP control > Authentication "Normal and
Pre-Shared Key", and set the key. Power on works over the API when
"Remote start" is on, else Wake-on-LAN.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import DisplayError, Driver
from . import wol


class Sony(Driver):
    kind = "sony"
    default_port = 80
    caps = frozenset({"power", "input", "volume", "mute", "avmute", "picture", "info", "remote"})

    def rpc(self, service: str, method: str, params=None, version: str = "1.0"):
        body = json.dumps({"method": method, "id": 1, "params": [params] if params is not None else [],
                           "version": version}).encode()
        req = urllib.request.Request(f"http://{self.d.host}:{self.port}/sony/{service}", body,
                                     {"Content-Type": "application/json"})
        if self.d.secret:
            req.add_header("X-Auth-PSK", self.d.secret)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise DisplayError("Wrong or missing pre-shared key")
            raise DisplayError(f"TV error HTTP {e.code}")
        except (OSError, ValueError) as e:
            raise DisplayError(f"No answer from {self.d.host} ({e.__class__.__name__})")
        if "error" in data:
            code, msg = (data["error"] + [""])[:2]
            if code in (401, 403, 40005):
                raise DisplayError("Wrong or missing pre-shared key" if code != 40005 else "TV is off")
            raise DisplayError(f"TV said: {msg or code}"[:60])
        res = data.get("result") or []
        return res[0] if res else {}

    def status(self):
        try:
            p = self.rpc("system", "getPowerStatus").get("status", "")
        except DisplayError as e:
            if "No answer" in str(e):
                return {"power": "off", "input": "", "volume": None, "mute": None}
            raise
        st = {"power": "on" if p == "active" else (p or "unknown"), "input": "", "volume": None, "mute": None}
        if st["power"] != "on":
            return st
        try:
            vols = self.rpc("audio", "getVolumeInformation")
            for v in vols if isinstance(vols, list) else []:
                if v.get("target") in ("speaker", ""):
                    st["volume"], st["mute"] = v.get("volume"), v.get("mute")
                    break
        except DisplayError:
            pass
        try:
            uri = self.rpc("avContent", "getPlayingContentInfo").get("uri", "")
            st["input"] = uri_label(uri)
        except DisplayError:
            pass
        return st

    def power(self, on):
        try:
            self.rpc("system", "setPowerStatus", {"status": bool(on)})
            return "Power on sent" if on else "Power off sent"
        except DisplayError:
            if on and self.d.mac:
                wol.wake(self.d.mac, self.d.host)
                return "Wake-on-LAN sent"
            raise

    def inputs(self):
        lst = self.rpc("avContent", "getCurrentExternalInputsStatus")
        out = []
        for i in lst if isinstance(lst, list) else []:
            label = i.get("label") or i.get("title") or uri_label(i.get("uri", ""))
            if i.get("label") and i.get("title"):
                label = f"{i['title']} ({i['label']})"
            out.append((i.get("uri", ""), label))
        return out

    def set_input(self, input_id):
        self.rpc("avContent", "setPlayContent", {"uri": input_id})
        return f"Input {uri_label(input_id)}"

    def volume(self, step):
        self.rpc("audio", "setAudioVolume", {"target": "speaker", "volume": f"{step:+d}"})
        return "Volume up" if step > 0 else "Volume down"

    def mute(self, on=None):
        if on is None:
            on = not self.status().get("mute")
        self.rpc("audio", "setAudioMute", {"status": bool(on)})
        return "Muted" if on else "Unmuted"

    def avmute(self, on=None):
        if on is None:
            cur = self.rpc("system", "getPowerSavingMode").get("mode", "")
            on = cur != "pictureOff"
        self.rpc("system", "setPowerSavingMode", {"mode": "pictureOff" if on else "off"})
        return "Picture off" if on else "Picture on"

    def picture_modes(self):
        res = self.rpc("video", "getPictureQualitySettings", {"target": "pictureMode"})
        for s in res if isinstance(res, list) else []:
            if s.get("target") == "pictureMode":
                return [c.get("value") for c in s.get("candidate") or [] if c.get("value")], s.get("currentValue", "")
        raise DisplayError("TV has no picture modes over IP")

    def set_picture(self, mode):
        self.rpc("video", "setPictureQualitySettings", {"settings": [{"target": "pictureMode", "value": mode}]})
        return f"Picture mode {mode}"

    REMOTE = {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "ok": "Confirm", "back": "Return",
              "home": "Home", "menu": "ActionMenu", "exit": "Exit", "info": "Display", "source": "Input"}
    FALLBACK = {"ActionMenu": "Options", "Confirm": "DpadCenter"}
    _codes: dict = {}

    def ircc_codes(self) -> dict:
        key = self.d.host
        if key not in Sony._codes:
            res = self.rpc("system", "getRemoteControllerInfo")
            lst = res[1] if isinstance(res, list) and len(res) > 1 else []
            Sony._codes[key] = {c.get("name"): c.get("value") for c in lst if isinstance(c, dict)}
        return Sony._codes[key]

    def remote(self, button):
        codes = self.ircc_codes()
        name = self.REMOTE[button]
        code = codes.get(name) or codes.get(self.FALLBACK.get(name, ""))
        if not code:
            raise DisplayError(f"TV has no {name} button over IP")
        body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                '<u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1"><IRCCCode>'
                f'{code}</IRCCCode></u:X_SendIRCC></s:Body></s:Envelope>').encode()
        req = urllib.request.Request(f"http://{self.d.host}:{self.port}/sony/IRCC", body, {
            "Content-Type": 'text/xml; charset=UTF-8',
            "SOAPACTION": '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"'})
        if self.d.secret:
            req.add_header("X-Auth-PSK", self.d.secret)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                r.read()
        except urllib.error.HTTPError as e:
            raise DisplayError("Wrong or missing pre-shared key" if e.code in (401, 403) else f"TV error HTTP {e.code}")
        except OSError as e:
            raise DisplayError(f"No answer from {self.d.host} ({e.__class__.__name__})")
        return button

    def info(self):
        out = super().info()
        try:
            si = self.rpc("system", "getSystemInformation")
            for label, k in (("Model", "model"), ("Name", "name"), ("Serial", "serial"), ("MAC", "macAddr"),
                             ("Software", "generation")):
                if si.get(k):
                    out.append((label, str(si[k])))
        except DisplayError as e:
            out.append(("Info", str(e)))
        return out


def uri_label(uri: str) -> str:
    if not uri.startswith("extInput:"):
        return uri.split(":")[0] if uri else ""
    kind, _, q = uri[9:].partition("?")
    port = q.split("port=")[-1].split("&")[0] if "port=" in q else ""
    return f"{kind.upper()} {port}".strip()
