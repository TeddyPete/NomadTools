"""Samsung Tizen TVs (2016 and later): remote keys over WebSocket.

wss://tv:8002 (2018+, token) or ws://tv:8001 (2016-17). The first time, the
TV asks on screen to allow "Nomad Display"; it returns a token we save.
Status and model come from http://tv:8001/api/v2/. Power on is
Wake-on-LAN, so the TV's MAC is needed for that.
"""
from __future__ import annotations

import base64
import json
import urllib.request

from .base import DisplayError, Driver
from .wsock import WebSocket
from . import wol

NAME = base64.b64encode(b"Nomad Display").decode()
INPUT_KEYS = [("KEY_HDMI1", "HDMI 1"), ("KEY_HDMI2", "HDMI 2"), ("KEY_HDMI3", "HDMI 3"),
              ("KEY_HDMI4", "HDMI 4"), ("KEY_TV", "TV tuner"), ("KEY_SOURCE", "Source menu")]


class Samsung(Driver):
    kind = "samsung"
    default_port = 8002
    needs_pairing = True
    caps = frozenset({"power", "input", "volume", "mute", "info", "remote"})

    def api(self) -> dict:
        try:
            with urllib.request.urlopen(f"http://{self.d.host}:8001/api/v2/", timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except (OSError, ValueError) as e:
            raise DisplayError(f"No answer from {self.d.host} ({e.__class__.__name__})")

    def _connect(self, wait: float | None = None) -> WebSocket:
        tls = self.port == 8002
        path = f"/api/v2/channels/samsung.remote.control?name={NAME}"
        if tls and self.d.secret:
            path += f"&token={self.d.secret}"
        ws = WebSocket(self.d.host, self.port, path, tls=tls, timeout=self.timeout)
        ws.settimeout(wait or self.timeout + 2)
        try:
            while True:
                r = ws.recv()
                ev = r.get("event", "")
                if ev == "ms.channel.connect":
                    tok = (r.get("data") or {}).get("token")
                    if tok:
                        self.d.secret = str(tok)
                    break
                if ev == "ms.channel.unauthorized":
                    raise DisplayError("TV said no: allow Nomad Display on the TV")
                if ev == "ms.channel.timeOut":
                    raise DisplayError("Nobody answered the TV's prompt")
        except DisplayError:
            ws.close()
            raise
        ws.settimeout(self.timeout)
        return ws

    def keys(self, *keys: str) -> None:
        ws = self._connect()
        try:
            for k in keys:
                ws.send({"method": "ms.remote.control", "params": {
                    "Cmd": "Click", "DataOfCmd": k, "Option": "false", "TypeOfRemote": "SendRemoteKey"}})
        finally:
            ws.close()

    def pair(self):
        ws = self._connect(wait=40)
        ws.close()
        return "Paired" if self.d.secret else "Connected"

    def status(self):
        try:
            dev = self.api().get("device") or {}
        except DisplayError:
            return {"power": "off", "input": "", "volume": None, "mute": None}
        ps = dev.get("PowerState", "on")
        return {"power": "on" if ps == "on" else ps, "input": "", "volume": None, "mute": None}

    def power(self, on):
        st = self.status()["power"]
        if on:
            if st == "on":
                return "Already on"
            if st == "standby":
                self.keys("KEY_POWER")       # network standby: the key wakes it
                return "Power on sent"
            if not self.d.mac:
                raise DisplayError("Power on needs the TV's MAC (Wake-on-LAN)")
            wol.wake(self.d.mac, self.d.host)
            return "Wake-on-LAN sent"
        if st != "on":
            return "Already off"
        self.keys("KEY_POWER")
        return "Power off sent"

    def inputs(self):
        return list(INPUT_KEYS)

    def set_input(self, input_id):
        self.keys(input_id)
        return dict(INPUT_KEYS).get(input_id, input_id)

    def volume(self, step):
        self.keys(*(["KEY_VOLUP" if step > 0 else "KEY_VOLDOWN"] * abs(step)))
        return "Volume up" if step > 0 else "Volume down"

    def mute(self, on=None):
        self.keys("KEY_MUTE")       # Samsung only has a toggle
        return "Mute toggled"

    REMOTE = {"up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT", "ok": "KEY_ENTER",
              "back": "KEY_RETURN", "home": "KEY_HOME", "menu": "KEY_MENU", "exit": "KEY_EXIT",
              "info": "KEY_INFO", "source": "KEY_SOURCE"}

    def remote(self, button):
        self.keys(self.REMOTE[button])
        return button

    MENUS = [("hotel", "Hotel / hospitality menu (experimental)", "Mute, 1, 1, 9, OK")]
    SEQ = {"hotel": ["KEY_MUTE", "KEY_1", "KEY_1", "KEY_9", "KEY_ENTER"]}

    def service_menus(self):
        return list(self.MENUS)

    def open_service_menu(self, menu_id):
        import time
        ws = self._connect()
        try:
            for k in self.SEQ[menu_id]:
                ws.send({"method": "ms.remote.control", "params": {
                    "Cmd": "Click", "DataOfCmd": k, "Option": "false", "TypeOfRemote": "SendRemoteKey"}})
                time.sleep(0.4)
        finally:
            ws.close()
        return "Keys sent (Mute 1 1 9 OK). Mute again if no menu showed"

    def info(self):
        out = super().info()
        a = self.api()
        dev = a.get("device") or {}
        for label, k in (("Name", "name"), ("Model", "modelName"), ("OS", "OS"), ("Firmware", "firmwareVersion"),
                         ("Wi-Fi MAC", "wifiMac"), ("Network", "networkType"), ("Power", "PowerState")):
            if dev.get(k):
                out.append((label, str(dev[k])))
        return out
