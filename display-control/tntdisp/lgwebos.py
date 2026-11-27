"""LG webOS TVs (2014 and later). Secure WebSocket on 3001 (3000 plain).

The TV asks once on screen to allow this device; it then hands out a
client key that we save. The key is tied to the permission list (MANIFEST)
below, which is the same one Ted's ~/lgtv.py paired with, so keep it
unchanged or every TV asks again.

Power on is Wake-on-LAN (the TV's network stack is asleep when it is off;
"Turn on via Wi-Fi / Mobile TV On" must be on in the TV's settings).
"""
from __future__ import annotations

import os

from .base import DisplayError, Driver
from .wsock import WebSocket
from . import wol

MANIFEST = {"manifestVersion": 1, "appVersion": "1.1", "signed": {"appId": "com.tnt.remote", "vendorId": "tnt",
  "created": "20261127", "permissions": ["CONTROL_AUDIO", "CONTROL_POWER", "CONTROL_INPUT_TV", "CONTROL_INPUT_MEDIA_PLAYBACK", "LAUNCH", "READ_INSTALLED_APPS", "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST", "READ_TV_CHANNEL_LIST", "CONTROL_DISPLAY", "READ_RUNNING_APPS", "CONTROL_MOUSE_AND_KEYBOARD", "WRITE_NOTIFICATION_TOAST", "READ_POWER_STATE"],
  "serial": "tnt1"}, "permissions": ["LAUNCH", "CONTROL_AUDIO", "CONTROL_POWER", "CONTROL_INPUT_TV", "CONTROL_INPUT_MEDIA_PLAYBACK", "READ_INSTALLED_APPS", "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST", "READ_TV_CHANNEL_LIST", "CONTROL_DISPLAY", "READ_RUNNING_APPS", "WRITE_NOTIFICATION_TOAST", "READ_POWER_STATE"], "signatures": []}

# The proof-of-concept pairing on Ted's device; offered when adding an LG TV
# so an already paired TV doesn't ask again.
LEGACY_KEY = os.path.expanduser("~/.lgtv_key")


def legacy_key() -> str:
    try:
        return open(LEGACY_KEY).read().strip()
    except OSError:
        return ""


class LGWebOS(Driver):
    kind = "lg"
    default_port = 3001
    needs_pairing = True
    caps = frozenset({"power", "input", "volume", "mute", "avmute", "message", "info"})

    def _connect(self, allow_prompt: bool = False, wait: float = 60.0) -> WebSocket:
        tls = self.port != 3000
        ws = WebSocket(self.d.host, self.port, "/", tls=tls, timeout=self.timeout)
        key = self.d.secret
        if not key and not allow_prompt:
            ws.close()
            raise DisplayError("Not paired yet: open the TV and choose Pair")
        p = {"forcePairing": False, "pairingType": "PROMPT", "manifest": MANIFEST}
        if key:
            p["client-key"] = key
        ws.send({"type": "register", "id": "reg0", "payload": p})
        ws.settimeout(wait if allow_prompt else self.timeout + 2)
        try:
            while True:
                r = ws.recv()
                t = r.get("type")
                if t == "registered":
                    new = (r.get("payload") or {}).get("client-key")
                    if new:
                        self.d.secret = new
                    break
                if t == "response" and (r.get("payload") or {}).get("pairingType") == "PROMPT" and not allow_prompt:
                    raise DisplayError("TV wants pairing again: choose Pair")
                if t == "error":
                    raise DisplayError(f"TV refused: {r.get('error', '')[:40]}")
        except DisplayError:
            ws.close()
            raise
        ws.settimeout(self.timeout)
        self._n = 0
        return ws

    def call(self, uri: str, payload: dict | None = None, ws: WebSocket | None = None) -> dict:
        own = ws is None
        ws = ws or self._connect()
        try:
            self._n = getattr(self, "_n", 0) + 1
            rid = f"c{self._n}"
            msg = {"type": "request", "id": rid, "uri": uri}
            if payload is not None:
                msg["payload"] = payload
            ws.send(msg)
            while True:
                r = ws.recv()
                if r.get("id") != rid:
                    continue
                if r.get("type") == "error":
                    raise DisplayError(str(r.get("error", "error"))[:60])
                pl = r.get("payload") or {}
                if pl.get("returnValue") is False:
                    raise DisplayError(str(pl.get("errorText") or "TV said no")[:60])
                return pl
        finally:
            if own:
                ws.close()

    def pair(self):
        ws = self._connect(allow_prompt=True)
        ws.close()
        return "Paired"

    def status(self):
        st = {"power": "unknown", "input": "", "volume": None, "mute": None}
        try:
            ws = self._connect()
        except DisplayError as e:
            if "No answer" in str(e):
                st["power"] = "off"
                return st
            raise
        try:
            try:
                ps = self.call("ssap://com.webos.service.tvpower/power/getPowerState", ws=ws).get("state", "")
                st["power"] = {"Active": "on", "Screen Off": "screen off", "Active Standby": "standby"}.get(ps, ps.lower() or "on")
            except DisplayError:
                st["power"] = "on"
            try:
                v = self.call("ssap://audio/getVolume", ws=ws)
                vs = v.get("volumeStatus") or v
                st["volume"] = vs.get("volume")
                st["mute"] = vs.get("muteStatus", vs.get("muted"))
            except DisplayError:
                pass
            try:
                app = self.call("ssap://com.webos.applicationManager/getForegroundAppInfo", ws=ws).get("appId", "")
                st["input"] = app_label(app)
            except DisplayError:
                pass
        finally:
            ws.close()
        return st

    def power(self, on):
        if on:
            if not self.d.mac:
                raise DisplayError("Power on needs the TV's MAC (Wake-on-LAN)")
            wol.wake(self.d.mac, self.d.host)
            return "Wake-on-LAN sent"
        self.call("ssap://system/turnOff")
        return "TV turning off"

    def inputs(self):
        devs = self.call("ssap://tv/getExternalInputList").get("devices") or []
        return [(d.get("id", ""), d.get("label") or d.get("id", "")) for d in devs if d.get("id")]

    def set_input(self, input_id):
        self.call("ssap://tv/switchInput", {"inputId": input_id})
        return f"Input {input_id.replace('_', ' ')}"

    def volume(self, step):
        ws = self._connect()
        try:
            for _ in range(abs(step)):
                self.call("ssap://audio/volumeUp" if step > 0 else "ssap://audio/volumeDown", ws=ws)
            v = self.call("ssap://audio/getVolume", ws=ws)
        finally:
            ws.close()
        vol = (v.get("volumeStatus") or v).get("volume")
        return f"Volume {vol}" if vol is not None else ("Volume up" if step > 0 else "Volume down")

    def mute(self, on=None):
        ws = self._connect()
        try:
            if on is None:
                v = self.call("ssap://audio/getVolume", ws=ws)
                vs = v.get("volumeStatus") or v
                on = not vs.get("muteStatus", vs.get("muted", False))
            self.call("ssap://audio/setMute", {"mute": bool(on)}, ws=ws)
        finally:
            ws.close()
        return "Muted" if on else "Unmuted"

    def avmute(self, on=None):
        # Screen off keeps the TV on with the panel dark (webOS 4.5+).
        if on is None:
            try:
                ps = self.call("ssap://com.webos.service.tvpower/power/getPowerState").get("state", "")
                on = ps != "Screen Off"
            except DisplayError:
                on = True
        uri = "turnOffScreen" if on else "turnOnScreen"
        self.call(f"ssap://com.webos.service.tvpower/power/{uri}", {"standbyMode": "active"})
        return "Screen off (TV still on)" if on else "Screen back on"

    def message(self, text):
        self.call("ssap://system.notifications/createToast", {"message": text[:60]})
        return "Message shown"

    def info(self):
        out = super().info()
        ws = self._connect()
        try:
            for uri, keys in (("ssap://system/getSystemInfo", ("modelName", "receiverType")),
                              ("ssap://com.webos.service.update/getCurrentSWInformation",
                               ("product_name", "major_ver", "minor_ver", "device_id"))):
                try:
                    pl = self.call(uri, ws=ws)
                except DisplayError:
                    continue
                for k in keys:
                    if pl.get(k):
                        out.append((k.replace("_", " ").replace("modelName", "Model").capitalize(), str(pl[k])))
        finally:
            ws.close()
        if self.d.mac:
            out.append(("MAC", self.d.mac))
        return out


def app_label(app_id: str) -> str:
    a = app_id.lower()
    for pre, name in (("com.webos.app.hdmi", "HDMI "), ("com.webos.app.livetv", "Live TV"),
                      ("com.webos.app.externalinput.av", "AV "), ("com.webos.app.externalinput.component", "Component ")):
        if a.startswith(pre):
            return (name + a[len(pre):]).strip()
    return app_id.split(".")[-1] if app_id else ""
