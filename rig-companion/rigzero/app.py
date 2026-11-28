"""Keyboard interface for the 320×170 CardputerZero screen."""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import queue
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .bluetooth import BluetoothLink
from .about import draw_about
from .bridges import BleBridge, TcpBridge
from .display import ACCENT, ALERT, BG, DIM, INK, LINE, PANEL, SELECT, SELECT_DIM, Display, Keyboard
from .protocol import MODES, POWERS, valid_call
from .radio import Radio
from .storage import Store

PAGES = ("Radio", "APRS", "Inbox", "Weather", "Link")


class App:
    def __init__(self, store, radio, display, link=None):
        self.store, self.radio, self.display, self.link = store, radio, display, link
        self.page = 0
        self.selected = 0
        self.detail = None
        self.scroll = 0
        self.saved = False
        self.editor = None
        self.compose = {"to": "", "text": ""}
        self.field = "to"
        self.edit_value = ""
        self.notice = ""
        self.notice_until = 0
        self.pair_code = None
        self.devices = []
        self.scan_active = False
        self.scan_until = 0
        self.link_selected = 0
        self.tcp = None
        self.ble = BleBridge(radio, link) if link else None
        self.running = True
        self.dirty = True
        self.last_render = 0
        self.last_key = ""
        self.map_active = False
        self.map_view = None
        self.raw_detail = False

    def tell(self, message):
        self.notice = str(message)
        self.notice_until = time.monotonic() + 5
        self.dirty = True

    def rows(self):
        return self.store.rows("saved" if self.saved and self.page == 1 else
                               "inbox" if self.page == 2 else "weather" if self.page == 3 else "traffic")

    def background(self, fn):
        def work():
            try:
                fn()
            except Exception as error:
                self.tell(error)
            finally:
                self.dirty = True
        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        if self.link:
            while True:
                try:
                    kind, value = self.link.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "pair":
                    self.pair_code = value
                elif kind == "pair_cancel":
                    self.pair_code = None
                elif kind == "error":
                    self.tell(value)
                self.dirty = True
            if self.scan_active and time.monotonic() > self.scan_until:
                self.scan_active = False
                def finish_scan():
                    self.devices = self.link.devices()
                    adapter = getattr(self.link, "scanning_adapter", None)
                    if adapter:
                        adapter.StopDiscovery()
                        self.link.scanning_adapter = None
                self.background(finish_scan)

    def open_compose(self, recipient=""):
        self.editor = "compose"
        if recipient:
            if self.compose["to"] != recipient:
                self.compose["text"] = ""
            self.compose["to"] = recipient
            self.field = "text"
        else:
            self.field = "to"
        if not valid_call(self.store.get("callsign")):
            self.tell("Set your callsign under Link before sending")

    def start_scan(self):
        if not self.link:
            self.tell("Bluetooth is unavailable in this preview")
            return
        self.scan_active = True
        self.scan_until = time.monotonic() + 8
        self.devices = []
        self.background(self.link.scan)

    def reply(self):
        if self.detail:
            sender = self.detail.get("sender", self.detail["source"])
            if valid_call(sender):
                self.open_compose(sender)
            else:
                self.tell("This packet has no valid APRS source callsign")

    def kiss(self, state):
        if state["kiss"]:
            self.radio.submit("end_kiss")
        elif self.store.get("recovery", None):
            self.radio.submit("end_kiss")
        elif state["connected"]:
            self.radio.submit("start_kiss")
        else:
            self.tell("Connect the TH-D75 first")

    def open_map(self, packet=None):
        if self.map_view is None:
            from .mapview import StationMap
            cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
            self.map_view = StationMap(cache / "rig-companion-zero" / "tiles")
        self.map_view.choose(self.store.stations(), packet)
        self.map_active = True

    def map_key(self, name, char):
        stations = self.store.stations()
        key = char.lower()
        if name == "esc" or key == "4":
            self.map_active = False
            self.map_view.cache.pause()
        elif key in ("5", "-", "6", "+", "="):
            self.map_view.zoom = max(2, min(18, self.map_view.zoom + (-1 if key in ("5", "-") else 1)))
        elif key == "7" or name == "tab":
            self.map_view.next(stations)
        elif key == "8" or name == "enter":
            packet = self.map_view.selected_packet(stations)
            if packet:
                self.detail, self.scroll, self.raw_detail = packet, 0, False
                self.map_active = False
                self.map_view.cache.pause()
        elif key == "r":
            self.map_view.choose(stations, self.map_view.selected_packet(stations))
        elif key == "a":
            self.map_view.fit(stations)
        elif key == "i":
            self.editor = "map_credits"
            self.map_view.cache.pause()
        else:
            name = {"f": "up", "x": "down", "z": "left", "c": "right"}.get(key, name)
            if name in ("left", "right", "up", "down"):
                self.map_view.pan(-1 if name == "left" else 1 if name == "right" else 0,
                                  -1 if name == "up" else 1 if name == "down" else 0)

    def handle(self, name, char=""):
        self.dirty = True
        state = self.radio.snapshot()
        if self.pair_code:
            if char.lower() == "y" or name == "enter":
                self.link.confirm(True)
                self.pair_code = None
            elif char.lower() == "n" or name == "esc":
                self.link.confirm(False)
                self.pair_code = None
            return
        if self.editor:
            self.edit(name, char, state)
            return
        if self.map_active:
            self.map_key(name, char)
            return
        if name == "esc":
            if self.detail:
                self.detail = None
            elif self.page:
                self.page = 0
            else:
                self.editor = "quit"
            return
        if self.detail:
            key = char.lower()
            name = {"f": "up", "x": "down", "z": "left", "c": "right"}.get(key, name)
            if key == "4" or name == "left":
                self.detail = None
            elif key in ("5", "m"):
                self.open_map(self.detail)
            elif key in ("8", "t"):
                self.raw_detail = not self.raw_detail
                self.scroll = 0
            elif key in ("6", "s"):
                if self.detail.get("view") == "inbox":
                    self.tell("Message already saved in Inbox")
                else:
                    self.store.save(self.detail["id"])
                    self.tell("Packet saved")
            elif key in ("7", "r"):
                self.reply()
            elif name == "up":
                self.scroll = max(0, self.scroll - 1)
            elif name == "down":
                self.scroll = min(self.max_scroll, self.scroll + 1)
            return
        if char in "45678" and char:
            self.page = int(char) - 4
            self.selected = 0
            self.saved = False
            return
        navigation = {"f": "up", "x": "down", "z": "left", "c": "right"}
        name = navigation.get(char.lower(), name)
        if char == "?":
            self.editor = "help"
        elif self.page == 0:
            actions = {"m": ("change", "mode"), "p": ("change", "power"), "v": ("change", "channel"),
                       "d": ("change", "dual"), "s": ("change", "squelch"),
                       "j": ("change", "volume", -5), "k": ("change", "volume", 5)}
            if name == "enter":
                self.editor, self.edit_value = "frequency", ""
            elif name == "tab":
                self.radio.submit("change", "band")
            elif name in ("up", "down") or char in ("+", "-"):
                self.radio.submit("step", 1 if name == "up" or char == "+" else -1)
            elif char.lower() in actions:
                self.radio.submit(*actions[char.lower()])
        elif self.page in (1, 2, 3):
            rows = self.rows()
            if name in ("up", "down"):
                self.selected = max(0, min(len(rows) - 1, self.selected + (1 if name == "down" else -1)))
            elif name == "left":
                self.page = 0
                self.saved = False
            elif name in ("enter", "right") and rows:
                self.detail = rows[min(self.selected, len(rows) - 1)]
                self.scroll = 0
                self.raw_detail = False
            elif char.lower() == "m":
                self.open_map(rows[min(self.selected, len(rows) - 1)] if rows else None)
            elif char.lower() == "n":
                self.open_compose()
            elif char.lower() == "s" and self.page == 1:
                self.saved = not self.saved
                self.selected = 0
            elif char.lower() == "k":
                self.kiss(state)
        else:
            options = self.link_options()
            if name in ("up", "down"):
                self.link_selected = max(0, min(len(options) - 1, self.link_selected + (1 if name == "down" else -1)))
            elif name == "left":
                self.page = 0
            elif name in ("enter", "right"):
                _, action = options[self.link_selected]
                self.link_action(action, state)

    def link_options(self):
        options = [("Find TH-D75 / pair", "scan"), ("Callsign  " + (self.store.get("callsign") or "Set yours"), "callsign"),
                   ("APRS path  " + (self.store.get("path") or "Direct"), "path"),
                   ("KISS  start / end / restore", "kiss"),
                   ("BLE phone bridge  " + ("On" if self.ble and self.ble.enabled else "Off"), "ble"),
                   ("TCP KISS / 8001  " + ("On" if self.tcp else "Off"), "tcp"),
                   ("Map data licences", "map_credits"),
                   ("About Rig Companion", "about")]
        for index, device in enumerate(self.devices):
            options.insert(index + 1, (device["name"] + (" · paired" if device["paired"] else " · pair"), index))
        return options

    def link_action(self, action, state):
        if isinstance(action, int):
            self.radio.submit("connect", self.devices[action])
        elif action == "scan":
            self.start_scan()
        elif action == "callsign":
            self.editor, self.edit_value = "callsign", self.store.get("callsign")
        elif action == "path":
            path = "" if self.store.get("path") else "WIDE1-1,WIDE2-1"
            self.store.set("path", path)
        elif action == "kiss":
            self.kiss(state)
        elif action in ("map_credits", "about"):
            self.editor = action
        elif action == "tcp":
            if self.tcp:
                self.tcp.close()
                self.tcp = None
            else:
                self.tcp = TcpBridge(self.radio)
                try:
                    self.tcp.start()
                except Exception:
                    self.tcp.close()
                    self.tcp = None
                    raise
                self.tell("TCP KISS on port 8001; trusted LAN only")
        elif action == "ble":
            if not self.ble:
                self.tell("Bluetooth bridge unavailable")
            elif self.ble.enabled or self.ble.application:
                self.ble.close()
            else:
                self.ble.start()

    def edit(self, name, char, state):
        if name == "esc":
            self.editor = None
            return
        if self.editor in ("help", "map_credits", "about"):
            if name in ("enter", "left") or (self.editor == "about" and char.lower() == "z"):
                self.editor = None
            elif self.editor == "help" and char.lower() == "a":
                self.editor = "about"
            return
        if self.editor == "quit":
            if name == "enter" or char.lower() == "y":
                self.running = False
            return
        if self.editor == "confirm_send":
            if name == "enter" or char.lower() == "y":
                self.radio.submit("send", self.compose["to"], self.compose["text"])
                self.editor = None
            return
        if self.editor == "compose":
            if name == "tab":
                self.field = "text" if self.field == "to" else "to"
            elif name == "enter":
                if self.field == "to":
                    self.field = "text"
                elif not valid_call(self.store.get("callsign")):
                    self.tell("Set your callsign under Link")
                elif not valid_call(self.compose["to"]) or not self.compose["text"]:
                    self.tell("Enter a recipient and message")
                elif not state["kiss"]:
                    self.radio.submit("start_kiss")
                    self.tell("Starting KISS. Press Enter again when ready.")
                elif state["owner"] != "local":
                    self.tell("Phone or TCP session owns the radio")
                else:
                    self.editor = "confirm_send"
            elif name == "backspace":
                self.compose[self.field] = self.compose[self.field][:-1]
            elif char:
                limit = 9 if self.field == "to" else 67
                if len(self.compose[self.field]) < limit:
                    self.compose[self.field] += char.upper() if self.field == "to" else char
            return
        if name == "backspace":
            self.edit_value = self.edit_value[:-1]
        elif name == "enter":
            if self.editor == "callsign":
                if not valid_call(self.edit_value):
                    self.tell("Use callsign with SSID 0–15")
                    return
                self.store.set("callsign", self.edit_value)
            else:
                self.radio.submit("tune", self.edit_value)
            self.editor = None
        elif char and len(self.edit_value) < (9 if self.editor == "callsign" else 12):
            self.edit_value += char.upper()

    def draw(self):
        state = self.radio.snapshot()
        d = self.display
        status = "KISS" if state["kiss"] else "CAT" if state["fresh"] else "Offline"
        if not state["kiss"] and state["connected"] and self.store.get("recovery", None):
            status = "Restore"
        if self.pair_code:
            d.header("Confirm pairing")
            d.text(self.pair_code, 106, 40, ACCENT, 23)
            target = getattr(self.link, "pair_target", "TH-D75")
            d.wrap(f"Compare this number with the {target}.\nEnter / Y accepts. Esc / N declines.", y=81, height=60)
            return
        if self.editor:
            self.draw_editor(state)
            return
        if self.map_active:
            stations = self.store.stations()
            d.header("APRS Map", f"{len(stations)} stations")
            d.text("© OpenStreetMap", 116, 6, DIM, 12)
            self.map_view.render(d, stations)
            d.footer(labels=["Back", "Zoom -", "Zoom +", "Next", "Open"])
            return
        if self.detail:
            packet = self.detail
            d.header(packet.get("sender", packet["source"]), packet["kind"])
            d.text(packet["time"].replace("T", " ").replace("+00:00", " UTC"), 10, 29, DIM, 12)
            d.text("To " + (packet["recipient"] or packet["destination"]), 10, 45, ACCENT, 12, 185)
            d.text("Raw view" if self.raw_detail else "Readable", 240, 45, DIM, 12, 74)
            if self.raw_detail:
                raw = packet["source"] + ">" + packet["destination"] + ("," + packet["path"] if packet["path"] else "") + ":" + packet["info"]
                text = "".join(c if 32 <= ord(c) < 127 else f"\\x{ord(c):02x}" for c in raw)
            else:
                text = packet.get("details", packet["text"])
            self.max_scroll = max(0, d.wrap(text, y=64, height=76, offset=self.scroll) - 4)
            d.footer(labels=["Back", "Map", "Save", "Reply", "Read" if self.raw_detail else "Raw"])
            if time.monotonic() < self.notice_until:
                d.rect(0, 129, 320, 17, BG)
                d.text(self.notice, 9, 130, ALERT, 12, 302)
            return
        d.header("Rig Companion" if self.page == 0 else PAGES[self.page], status)
        if self.page == 0:
            self.draw_radio(state)
        elif self.page in (1, 2):
            self.draw_list()
        elif self.page == 3:
            self.draw_weather()
        else:
            self.draw_link(state)
        d.footer(self.page)
        if time.monotonic() < self.notice_until:
            d.rect(0, 130, 320, 16, BG)
            d.text(self.notice, 9, 131, ALERT, 12, 302)

    def draw_radio(self, state):
        d = self.display
        for index, band in enumerate(state["bands"]):
            y = 31 + index * 39
            selected = state["active"] == index
            d.rect(8, y, 304, 36, SELECT if selected else PANEL, 4)
            d.text("A" if index == 0 else "B", 15, y + 5, INK if selected else DIM, 17)
            hz = band["hz"]
            d.text(f"{hz / 1000000:.6f}" if hz else "---.------", 37, y + 1,
                   INK if state["connected"] else DIM, 23)
            mode = MODES[band["mode"]] if 0 <= band["mode"] < len(MODES) else "--"
            channel = {0: "VFO", 1: "MR", 2: "CALL"}.get(band["channel"], "--")
            d.text(mode + " " + channel, 224, y + 2, SELECT_DIM if selected else DIM, 12, 83)
            d.text(f"SM {band['meter']}" if band["meter"] >= 0 else "SM --", 224, y + 18, INK if selected else ACCENT, 12)
        band = state["bands"][state["active"]]
        power = POWERS[band["power"]] if 0 <= band["power"] < len(POWERS) else "--"
        d.text(f"Vol {state['volume'] if state['volume'] >= 0 else '--'}   SQL {band['squelch'] if band['squelch'] >= 0 else '--'}   {power}", 10, 111, DIM, 12, 300)
        text = state["error"] or ("Enter tune · Tab A/B · ? controls" if state["connected"] else
                                  "Last readback · 8 Link to reconnect" if any(b["hz"] for b in state["bands"]) else
                                  "8 Link · Find TH-D75 to pair")
        d.text(text, 10, 130, ALERT if state["error"] else DIM, 12, 302)

    def draw_list(self):
        d = self.display
        rows = self.rows()
        self.selected = max(0, min(self.selected, len(rows) - 1))
        if not rows:
            d.text("No saved messages yet" if self.page == 2 else "No saved packets" if self.saved else "Waiting for packets", 10, 51, INK, 17)
            d.wrap("Native APRS needs Menu 590 Raw Packets and Menu 982 Bluetooth. K starts KISS.", y=78, height=49, color=DIM)
        else:
            start = max(0, self.selected - 2)
            for i, packet in enumerate(rows[start:start + 3]):
                y = 30 + i * 32
                chosen = start + i == self.selected
                if chosen:
                    d.rect(7, y, 306, 31, SELECT, 3)
                d.text(packet.get("sender", packet["source"]), 12, y, INK if chosen else ACCENT, 14, 125)
                d.text(packet["kind"], 145, y + 2, SELECT_DIM if chosen else DIM, 12, 90)
                d.text(packet["time"][11:19], 249, y + 2, SELECT_DIM if chosen else DIM, 12)
                d.text(packet.get("summary", packet["text"]), 12, y + 16, INK, 12, 294)
        d.text("→ open · ← back · M map · N write" + (" · S " + ("live" if self.saved else "saved") if self.page == 1 else " · K KISS"),
               10, 130, DIM, 12, 302)

    def draw_weather(self):
        d = self.display
        rows = self.rows()
        if not rows:
            d.text("Waiting for weather reports", 10, 50, INK, 17)
            d.wrap("Reports appear when received through native APRS or KISS. K starts KISS.", y=79, height=49, color=DIM)
            return
        self.selected = max(0, min(self.selected, len(rows) - 1))
        packet = rows[self.selected]
        wx = packet["weather"]
        d.text(packet["source"], 10, 30, ACCENT, 14, 150)
        d.text(packet["time"][11:19] + " UTC", 221, 32, DIM, 12)
        d.rect(8, 51, 112, 70, "#193b3b", 5)
        d.text(f"{wx['temp']:g} F" if "temp" in wx else "-- F", 17, 55, ACCENT, 23)
        d.text(f"Humidity {wx['humidity']:g}%" if "humidity" in wx else "Humidity --", 17, 94, INK, 12)
        import pygame
        center = (155, 77)
        pygame.draw.circle(d.surface, LINE, center, 20, 1)
        bearing = wx.get("bearing")
        if bearing is not None:
            angle = math.radians(bearing)
            endpoint = (155 + int(17 * math.sin(angle)), 77 - int(17 * math.cos(angle)))
            pygame.draw.line(d.surface, ACCENT, center, endpoint, 2)
        d.text(f"Wind {wx['wind']:g} mph" if "wind" in wx else "Wind --", 188, 55, INK, 14, 124)
        d.text(f"Gust {wx['gust']:g} mph" if "gust" in wx else "Gust --", 188, 76, DIM, 12, 124)
        d.text(f"{wx['pressure']:.1f} hPa" if "pressure" in wx else "Pressure --", 132, 104, INK, 12)
        d.text(f"{wx['rain']:.2f} in" if "rain" in wx else "Rain --", 242, 104, INK, 12)
        d.text("Up/down reports · → packet · ← back", 10, 130, DIM, 12)

    def draw_link(self, state):
        d = self.display
        options = self.link_options()
        self.link_selected = min(self.link_selected, len(options) - 1)
        start = max(0, self.link_selected - 3)
        for index, (label, _) in enumerate(options[start:start + 4]):
            y = 29 + index * 23
            if start + index == self.link_selected:
                d.rect(7, y, 306, 22, SELECT, 3)
            d.text(label, 12, y + 2, INK, 14, 295)
        status = "Searching… Open Menu 934" if self.scan_active else state["error"] or "→ select · ← back · F/X move"
        if self.ble and self.ble.enabled:
            status = self.ble.status
        if self.tcp and self.tcp.error:
            status = self.tcp.error
        d.text(status, 10, 130, ALERT if state["error"] else DIM, 12, 302)

    def draw_editor(self, state):
        d = self.display
        if self.editor == "compose":
            d.header("APRS message", "KISS" if state["kiss"] else "Native")
            d.text("From " + (self.store.get("callsign") or "Set under Link"), 10, 30, DIM, 12, 300)
            d.rect(8, 49, 304, 24, PANEL, 3)
            d.text("To " + self.compose["to"] + ("_" if self.field == "to" else ""), 13, 52, ACCENT if self.field == "to" else INK, 14)
            d.wrap(self.compose["text"] + ("_" if self.field == "text" else ""), y=80, height=51)
            d.text("Tab next · Enter send · Esc back", 10, 149, DIM, 12)
        elif self.editor == "confirm_send":
            d.header("Send APRS message?")
            d.text("To " + self.compose["to"], 10, 36, ACCENT, 17)
            hz = state["bands"][state["active"]]["hz"]
            d.text(f"{hz / 1000000:.6f} MHz" if hz else "Frequency readback unavailable", 10, 64, INK, 14)
            d.wrap("Confirm the radio is on your intended APRS channel. Enter sends one packet. Esc cancels.", y=88, height=63)
        elif self.editor == "map_credits":
            d.header("Map data licences")
            d.wrap("© OpenStreetMap contributors\nOpen Database License (ODbL)\nopenstreetmap.org/copyright", y=39, height=85)
            d.text("Enter or Esc returns", 10, 149, DIM, 12)
        elif self.editor == "about":
            draw_about(d, ACCENT, INK, DIM)
        elif self.editor == "help":
            d.header("Radio controls")
            for i, text in enumerate(("Up/down tune or memory · Tab A/B", "Enter frequency · V VFO / MR", "M mode · P power · D dual", "S squelch · J/K volume", "4–8 pages · Esc back · hold Esc exit", "A about · Enter or Esc closes")):
                d.text(text, 10, 31 + i * 21, INK, 12)
        elif self.editor == "quit":
            d.header("Exit Rig Companion?")
            d.wrap("The app restores an active KISS session before exiting. Enter confirms. Esc returns.", y=49, height=85)
        else:
            d.header("Your APRS callsign" if self.editor == "callsign" else "Frequency / MHz")
            d.rect(8, 48, 304, 35, PANEL, 4)
            d.text(self.edit_value + "_", 15, 53, ACCENT, 23, 290)
            d.wrap("Include your SSID, for example N0CALL-7." if self.editor == "callsign" else "The selected band must be in VFO mode.", y=97, height=35, color=DIM)
            d.text("Enter save · Esc cancel", 10, 149, DIM, 12)
        if time.monotonic() < self.notice_until:
            d.rect(0, 130, 320, 16, BG)
            d.text(self.notice, 9, 131, ALERT, 12, 302)

    def close(self):
        if self.map_view:
            self.map_view.close()
        if self.tcp:
            self.tcp.close()
        if self.ble:
            self.ble.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", metavar="FOLDER")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--seconds", type=float, default=0)
    args = parser.parse_args()
    folder = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "rig-companion-zero"
    if args.preview:
        from .preview import render_previews
        render_previews(Path(args.preview))
        return
    if args.status:
        store = Store(folder)
        print(json.dumps({"callsign_set": bool(store.get("callsign")), "paired_radio": bool(store.get("device")),
                          "restore_pending": bool(store.get("recovery", None)), "messages": len(store.rows("inbox", 500))}))
        store.close()
        return
    folder.mkdir(parents=True, exist_ok=True)
    lock = open(folder / "running.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Rig Companion is already running")
    store = Store(folder)
    link = BluetoothLink()
    radio = Radio(store, link)
    display = Display()
    keyboard = Keyboard()
    app = App(store, radio, display, link)
    signal.signal(signal.SIGTERM, lambda *_: setattr(app, "running", False))
    signal.signal(signal.SIGINT, lambda *_: setattr(app, "running", False))
    started = time.monotonic()
    try:
        if not keyboard.fds:
            app.tell("No keyboard input is available")
        while app.running:
            for name, char in keyboard.poll(.05):
                if name == "exit":       # Esc held: leave the app (key spec)
                    app.running = False
                    break
                try:
                    app.handle(name, char)
                except Exception as error:
                    app.tell(error)
            app.tick()
            if app.dirty or time.monotonic() - app.last_render >= .5:
                app.draw()
                display.flush()
                app.last_render = time.monotonic()
                app.dirty = False
            if args.seconds and time.monotonic() - started >= args.seconds:
                app.running = False
    finally:
        app.close()
        radio.close()
        link.close()
        keyboard.close()
        display.close()
        store.close()
        lock.close()


if __name__ == "__main__":
    main()

