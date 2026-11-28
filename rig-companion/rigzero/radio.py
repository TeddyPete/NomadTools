"""One worker owns the radio stream, including CAT/native-APRS/KISS handoff."""
from __future__ import annotations

import copy
import queue
import re
import socket
import threading
import time
from decimal import Decimal, InvalidOperation

from .protocol import (KissDecoder, MODES, STEPS, decode_ax25, decode_tnc2, fo_frequency,
                       inspect_packet, kiss_encode, message_frame)


class Radio:
    def __init__(self, store, link=None):
        self.store, self.link = store, link
        self.connection = None
        self.actions = queue.Queue(maxsize=32)
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.state = {"connected": False, "identity": False, "status": "Choose your TH-D75 under Link",
                      "active": 0, "dual": -1, "volume": -1, "kiss": False, "owner": "",
                      "rx": 0, "tx": 0, "invalid": 0, "last_rx": "", "error": "",
                      "bands": [{"hz": 0, "mode": -1, "power": -1, "channel": -1,
                                 "squelch": -1, "meter": -1, "busy": -1} for _ in range(2)]}
        self.line = bytearray()
        self.discard = False
        self.lines = []
        self.decoder = KissDecoder()
        self.identified_at = 0.0
        self.pending_kiss = False
        self.remote_reply = None
        self.next_poll = 0.0
        self.poll_index = 0
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="rig-radio", daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.state)
        result["fresh"] = result["identity"] and time.monotonic() - self.identified_at < 6
        return result

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def submit(self, action, *args):
        try:
            self.actions.put_nowait((action, args))
            return True
        except queue.Full:
            self.update(error="Radio command queue full")
            return False

    def _receive(self):
        try:
            data = self.connection.recv(4096)
        except (socket.timeout, BlockingIOError):
            return
        if not data:
            raise ConnectionError("Bluetooth radio disconnected")
        if self.state["kiss"]:
            before = self.decoder.invalid
            for command, payload in self.decoder.feed(data):
                if command == 0:
                    frame = decode_ax25(payload)
                    if frame:
                        self.record(frame)
                    else:
                        self.state["invalid"] += 1
                    if self.remote_reply:
                        self.remote_reply(kiss_encode(payload))
            self.state["invalid"] += self.decoder.invalid - before
            return
        for byte in data:
            if byte in (10, 13):
                if self.line and not self.discard:
                    self._line(self.line.decode("ascii", "replace"))
                self.line.clear()
                self.discard = False
            elif byte < 32 or byte > 127 or len(self.line) >= 1024:
                self.discard = True
            elif not self.discard:
                self.line.append(byte)

    def record(self, frame, direction="RX"):
        packet = inspect_packet(*frame, direction=direction)
        self.store.record(packet)
        self.state["rx" if direction == "RX" else "tx"] += 1
        self.state["last_rx"] = packet["source"] + "  " + packet["kind"]

    def _line(self, line):
        frame = decode_tnc2(line)
        if frame:
            self.record(frame)
            return
        self.lines.append(line)
        self.lines = self.lines[-32:]
        if line == "ID TH-D75":
            self.state["identity"] = True
            self.identified_at = time.monotonic()
        match = re.fullmatch(r"(FQ|MD|PC|VM|SQ|SM|BY) ([01]),([0-9]+)", line)
        if match:
            field = {"FQ": "hz", "MD": "mode", "PC": "power", "VM": "channel",
                     "SQ": "squelch", "SM": "meter", "BY": "busy"}[match[1]]
            self.state["bands"][int(match[2])][field] = int(match[3])
        for code, key in (("BC", "active"), ("DL", "dual"), ("AG", "volume")):
            if re.fullmatch(code + r" [0-9]+", line):
                self.state[key] = int(line.split()[1])

    def cat(self, command, expected=None, timeout=1.8):
        if self.state["kiss"]:
            raise RuntimeError("Stop KISS before changing radio controls")
        if not self.connection:
            raise RuntimeError("Connect the TH-D75 first")
        if not re.fullmatch(r"[ -~]{2,239}", command):
            raise ValueError("Invalid CAT command")
        self.lines.clear()
        self.connection.sendall((command + "\r").encode("ascii"))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self._receive()
            for line in self.lines:
                if line in ("?", "N"):
                    raise RuntimeError(f"Radio rejected {command.split()[0]}")
                if expected and expected(line):
                    return line
            if expected is None:
                return ""
        raise TimeoutError(f"No readback for {command.split()[0]}")

    def query(self, command):
        return self.cat(command, lambda line: line == command or line.startswith(command + ",") or
                        (re.fullmatch(r"MR [01]", command) and re.fullmatch(r"MR [0-9]{3}", line)) or
                        (" " not in command and line.startswith(command + " ")))

    def identify(self):
        for attempt in range(3):
            try:
                return self.cat("ID", lambda line: line == "ID TH-D75")
            except RuntimeError:
                if attempt == 2:
                    raise

    def require_control(self):
        if not self.state["connected"] or not self.state["identity"]:
            raise RuntimeError("Radio identity is not confirmed")
        if self.store.get("recovery", None):
            raise RuntimeError("Restore the previous KISS session first")
        self.identify()

    def change(self, field, amount=1):
        self.require_control()
        band = self.state["active"]
        if field == "band":
            target = 1 - band
            self.cat(f"BC {target}")
            if self.query("BC") != f"BC {target}":
                raise RuntimeError("Band selection did not confirm")
            return
        mapping = {"mode": ("MD", 8), "power": ("PC", 4), "channel": ("VM", 2),
                   "squelch": ("SQ", 6), "dual": ("DL", 2), "volume": ("AG", 201)}
        code, count = mapping[field]
        query = code if field in ("dual", "volume") else f"{code} {band}"
        current = int(re.split(r"[, ]", self.query(query))[-1])
        if field == "volume":
            candidates = [max(0, min(200, current + amount))]
        elif field == "mode":
            candidates = [(current + i) % count for i in range(1, count + 1)]
        else:
            candidates = [(current + amount) % count]
        for value in candidates:
            separator = " " if field in ("dual", "volume") else ","
            try:
                self.cat(query + separator + str(value))
                actual = int(re.split(r"[, ]", self.query(query))[-1])
            except RuntimeError:
                if field == "mode":
                    continue
                raise
            if actual == value:
                return
        raise RuntimeError("Radio did not confirm this setting")

    def tune(self, mhz):
        self.require_control()
        try:
            decimal = Decimal(mhz) * 1000000
            if decimal != decimal.to_integral_value():
                raise ValueError("Frequency has more than six decimal places")
            frequency = int(decimal)
        except (InvalidOperation, OverflowError):
            raise ValueError("Enter a frequency in MHz") from None
        band = self.state["active"]
        if self.query(f"VM {band}") != f"VM {band},0":
            raise RuntimeError("Select VFO mode before frequency entry")
        record = self.query(f"FO {band}")
        self.cat(fo_frequency(record, band, frequency))
        if self.query(f"FQ {band}") != f"FQ {band},{frequency:010d}":
            raise RuntimeError("Frequency did not confirm")

    def step(self, direction):
        self.require_control()
        band = self.state["active"]
        mode = self.query(f"VM {band}")
        if mode == f"VM {band},1":
            readback = self.query(f"MR {band}")
            channel = int(re.split(r"[, ]", readback)[-1])
            for i in range(1, 1001):
                number = (channel + direction * i) % 1000
                try:
                    self.query(f"ME {number:03d}")
                except RuntimeError:
                    continue
                self.cat(f"MR {band},{number:03d}")
                if int(re.split(r"[, ]", self.query(f"MR {band}"))[-1]) == number:
                    self.query(f"FQ {band}")
                    return
            raise RuntimeError("No populated memory channel found")
        if mode != f"VM {band},0":
            raise RuntimeError("Select VFO or memory mode")
        current = int(self.query(f"FQ {band}").split(",")[1])
        record = self.query(f"FO {band}")
        code = record.split(",")[3]
        index = ord(code) - ord("A") + 10 if code in ("A", "B") else int(code)
        self.tune(str(Decimal(current + direction * STEPS[index]) / 1000000))

    def start_kiss(self, owner="local", frequency=None, speed=None):
        if self.state["kiss"]:
            if self.state["owner"] != owner:
                raise RuntimeError("Another session owns KISS")
            if frequency:
                self.end_kiss()
            else:
                return
        self.require_control()
        band = self.state["active"]
        tn = self.query("TN")
        if not re.fullmatch(r"TN [01],[01]", tn):
            raise RuntimeError("End the radio's existing data session first")
        snapshot = {"tn": tn, "band": band, "fo": self.query(f"FO {band}"),
                    "vm": self.query(f"VM {band}"), "rate": self.query("AS")}
        self.store.set("recovery", snapshot)
        self.pending_kiss = True
        try:
            if frequency:
                self.cat(f"VM {band},0")
                if self.query(f"VM {band}") != f"VM {band},0":
                    raise RuntimeError("VFO setup did not confirm")
                record = fo_frequency(snapshot["fo"], band, frequency).split(",")
                record[5] = "0"
                self.cat(",".join(record))
                if self.query(f"FQ {band}") != f"FQ {band},{frequency:010d}":
                    raise RuntimeError("Station frequency did not confirm")
                if self.query(f"MD {band}") != f"MD {band},0":
                    raise RuntimeError("Packet FM did not confirm")
            if speed is not None:
                if speed not in (0, 1):
                    raise ValueError("Invalid packet speed")
                self.cat(f"AS {speed}")
                if self.query("AS") != f"AS {speed}":
                    raise RuntimeError("Packet speed did not confirm")
            # Persist before TN, since a disconnect can happen after the write.
            self.cat(f"TN 2,{band}", lambda line: line == f"TN 2,{band}")
            self.state.update(kiss=True, owner=owner, status="KISS active; radio controls paused", error="")
            self.decoder = KissDecoder()
            self.pending_kiss = False
            self.line.clear()
        except Exception:
            self.restore()
            raise

    def restore(self):
        snapshot = self.store.get("recovery", None)
        if not snapshot:
            return
        self.state["kiss"] = False
        self.connection.sendall(b"\xc0\xff\xc0")
        self.line.clear()
        self.discard = False
        time.sleep(.15)
        self.identify()
        band = snapshot["band"]
        self.cat(snapshot["rate"])
        if self.query("AS") != snapshot["rate"]:
            raise RuntimeError("Packet speed restoration did not confirm")
        if self.query(f"FO {band}") != snapshot["fo"]:
            # FO writes require VFO mode; a local monitor may have stayed in MR.
            self.cat(f"VM {band},0")
            if self.query(f"VM {band}") != f"VM {band},0":
                raise RuntimeError("VFO mode restoration did not confirm")
            self.cat(snapshot["fo"])
            if self.query(f"FO {band}") != snapshot["fo"]:
                raise RuntimeError("VFO restoration did not confirm")
        self.cat(snapshot["vm"])
        if self.query(f"VM {band}") != snapshot["vm"]:
            raise RuntimeError("Memory mode restoration did not confirm")
        self.cat(snapshot["tn"], lambda line: line == snapshot["tn"])
        if self.query("TN") != snapshot["tn"]:
            raise RuntimeError("APRS mode restoration did not confirm")
        self.store.set("recovery", None)
        self.pending_kiss = False
        self.state.update(kiss=False, owner="", status="Radio settings restored", error="")

    def end_kiss(self):
        if self.state["kiss"] or self.store.get("recovery", None):
            self.restore()

    def send_message(self, recipient, text):
        source = self.store.get("callsign")
        frame = message_frame(source, recipient.upper(), text, self.store.get("path", ""))
        if not self.state["kiss"] or self.state["owner"] != "local":
            raise RuntimeError("Start local KISS before sending")
        if not self.state["identity"]:
            raise RuntimeError("Radio is unavailable")
        self.connection.sendall(kiss_encode(frame))
        self.record(decode_ax25(frame), "TX")
        self.state["status"] = "Packet sent to radio; delivery unconfirmed"

    def _connect(self, device):
        self.state["status"] = "Connecting to TH-D75…"
        self.connection = self.link.connect(device)
        self.state.update(connected=True, identity=False, kiss=False, owner="")
        self.line.clear()
        self.discard = False
        if self.store.get("recovery", None):
            self.restore()
        self.identify()
        self.store.set("device", device)
        self.state.update(status="TH-D75 connected", error="")

    def _poll(self):
        commands = ["ID", "BC", "FQ 0", "FQ 1", "MD 0", "MD 1", "PC 0", "PC 1",
                    "VM 0", "VM 1", "DL", "AG", "SQ 0", "SQ 1", "SM 0", "SM 1", "BY 0", "BY 1"]
        self.query(commands[self.poll_index % len(commands)])
        self.poll_index += 1
        self.next_poll = time.monotonic() + .08

    def _run(self):
        next_connect = time.monotonic() + 1
        while not self.stop_event.is_set():
            try:
                action, args = self.actions.get(timeout=.03)
            except queue.Empty:
                action, args = None, ()
            try:
                if action == "connect":
                    if self.connection:
                        self.end_kiss()
                        self.link.disconnect()
                    self._connect(*args)
                elif action:
                    self.state["error"] = ""
                    {"change": self.change, "tune": self.tune, "step": self.step,
                     "start_kiss": self.start_kiss, "end_kiss": self.end_kiss,
                         "send": self.send_message, "remote": self._remote,
                         "remote_open": self._remote_open}[action](*args)
                elif self.connection:
                    self._receive()
                    if not self.state["kiss"] and time.monotonic() >= self.next_poll:
                        if not self.store.get("recovery", None):
                            self._poll()
                elif self.link and time.monotonic() >= next_connect:
                    next_connect = time.monotonic() + 8
                    device = self.store.get("device", None)
                    if device:
                        devices = self.link.devices()
                        match = next((d for d in devices if d["address"] == device["address"]), None)
                        if match:
                            self._connect(match)
            except (OSError, ConnectionError) as error:
                self._lost(str(error))
            except Exception as error:
                self.update(error=str(error), status=str(error))
        try:
            if self.connection:
                self.end_kiss()
        except Exception as error:
            self.update(error=f"Restore pending on reconnect: {error}")
        if self.link:
            self.link.disconnect()
        self.closed = True

    def _lost(self, reason):
        if self.link:
            self.link.disconnect()
        self.connection = None
        self.update(connected=False, identity=False, kiss=False, owner="", status="Radio disconnected", error=reason)

    def _remote(self, owner, command, payload, reply):
        if self.state["owner"] and self.state["owner"] != owner:
            raise RuntimeError("Another KISS session owns the radio")
        self.remote_reply = reply
        if command == 6 and payload:
            op = payload[0]
            if op in (0x7b, 0x7e, 0x28):
                values = {0x7b: b"\x01\x00", 0x7e: b"\x08\x10", 0x28: b"0.1.0"}
                reply(kiss_encode(bytes([op]) + values[op], 6))
            elif op == 0xf4 and len(payload) == 2 and payload[1] <= 1:
                self.store.set("remote_rate", payload[1])
            elif op == 0xea and len(payload) == 5:
                frequency = int.from_bytes(payload[1:], "big")
                if not (136000000 <= frequency <= 174000000 or 216000000 <= frequency <= 260000000 or 400000000 <= frequency <= 470000000):
                    raise ValueError("Unsupported packet station frequency")
                self.start_kiss(owner, frequency, self.store.get("remote_rate", 0))
            elif op == 0xeb:
                self.end_kiss()
            return
        if command == 255:
            self.end_kiss()
            self.remote_reply = None
            return
        if command not in range(6):
            return
        if not self.state["kiss"]:
            self.start_kiss(owner)
        if command == 0 and payload:
            if decode_ax25(payload) is None:
                raise ValueError("Invalid AX.25 transmit frame")
            self.connection.sendall(kiss_encode(payload))
            self.record(decode_ax25(payload), "TX")
        elif command in range(1, 6) and len(payload) == 1:
            self.connection.sendall(kiss_encode(payload, command))

    def _remote_open(self, owner, reply):
        self.start_kiss(owner)
        self.remote_reply = reply

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=16)
        if not self.closed:
            raise RuntimeError("Waiting for radio restoration. Exit again after it completes.")

