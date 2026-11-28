"""Optional KISS transports. The radio worker grants one session owner."""
from __future__ import annotations

import queue
import logging
import socket
import threading
import time

from .protocol import KissDecoder, kiss_encode


class TcpBridge:
    def __init__(self, radio, port=8001):
        self.radio, self.port = radio, port
        self.stop = threading.Event()
        self.server = self.client = None
        self.output = queue.Queue(maxsize=32)
        self.error = ""
        self.thread = threading.Thread(target=self._run, daemon=True, name="rig-tcp-kiss")

    def start(self):
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("0.0.0.0", self.port))
        self.server.listen(1)
        self.server.settimeout(.15)
        self.thread.start()

    def reply(self, data):
        try:
            self.output.put_nowait(data)
        except queue.Full:
            self.error = "TCP receiver is too slow"
            if self.client:
                self.client.shutdown(socket.SHUT_RDWR)

    def _run(self):
        while not self.stop.is_set():
            try:
                self.client, _ = self.server.accept()
                state = self.radio.snapshot()
                if not state["connected"] or state["owner"]:
                    self.client.close()
                    self.client = None
                    continue
                self.client.settimeout(.1)
                decoder = KissDecoder()
                # Start receive on connect; hardware setup commands may QSY later.
                self.radio.submit("remote_open", "tcp", self.reply)
                while not self.stop.is_set():
                    try:
                        while True:
                            self.client.sendall(self.output.get_nowait())
                    except queue.Empty:
                        pass
                    try:
                        data = self.client.recv(1024)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    for command, payload in decoder.feed(data):
                        if not self.radio.submit("remote", "tcp", command, payload, self.reply):
                            raise ConnectionError("Radio command queue full")
            except socket.timeout:
                continue
            except OSError as error:
                if not self.stop.is_set():
                    self.error = str(error)
            finally:
                if self.client:
                    self.client.close()
                    self.client = None
                    self.radio.submit("remote", "tcp", 255, b"", self.reply)
                    while not self.output.empty():
                        self.output.get_nowait()

    def close(self):
        self.stop.set()
        if self.client:
            try:
                self.client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.server:
            self.server.close()
        if self.thread.is_alive():
            self.thread.join(2)


class BleBridge:
    """BlueZ BLE KISS service, enabled explicitly from Link."""
    def __init__(self, radio, link):
        self.radio, self.link = radio, link
        self.enabled = False
        self.status = "BLE bridge off"
        self.output = queue.Queue(maxsize=256)
        self.application = None
        self.peer = None
        self.last_value = b""

    def reply(self, data):
        # Default ATT payload is 20 bytes; it works with all negotiated MTUs.
        for offset in range(0, len(data), 20):
            try:
                self.output.put_nowait(data[offset:offset + 20])
            except queue.Full:
                self.status = "BLE notification queue full"
                self.radio.submit("remote", "ble", 255, b"", self.reply)
                return

    def start(self):
        if not self.link.ready.wait(2) or self.link.error:
            raise RuntimeError(self.link.error or "Bluetooth not ready")
        import dbus
        import dbus.service
        from gi.repository import GLib
        bridge, bus = self, self.link.bus
        # Incoming phone bonds have no outgoing Pair caller to select our agent.
        self.link.manager.RequestDefaultAgent(self.link.agent.object_path)
        service_id = "00000001-ba2a-46c9-ae49-01b0961f68bb"
        root = "/org/rigcompanion/kiss"
        service_path = root + "/service0"
        characteristic_interface = "org.bluez.GattCharacteristic1"
        property_interface = "org.freedesktop.DBus.Properties"

        class Object(dbus.service.Object):
            def __init__(self, path, interface, properties):
                super().__init__(bus, path)
                self.object_path = path
                self.interface, self.properties = interface, properties

            @dbus.service.method(property_interface, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                return self.properties if interface == self.interface else {}

            @dbus.service.method(property_interface, in_signature="ss", out_signature="v")
            def Get(self, interface, key):
                return self.GetAll(interface)[key]

        class Characteristic(Object):
            def __init__(self, suffix, uuid, flags):
                super().__init__(service_path + suffix, characteristic_interface,
                                 {"UUID": uuid, "Service": dbus.ObjectPath(service_path),
                                  "Flags": dbus.Array(flags, signature="s")})
                self.decoder = KissDecoder()
                self.notifying = False

            @dbus.service.method(characteristic_interface, in_signature="aya{sv}", out_signature="")
            def WriteValue(self, value, options):
                logging.warning("BLE KISS: write received (%d bytes)", len(value))
                if not self.object_path.endswith("/tx"):
                    raise dbus.exceptions.DBusException("Read only", name="org.bluez.Error.NotPermitted")
                device = str(options.get("device", ""))
                state = bridge.radio.snapshot()
                if bridge.peer and bridge.peer != device or state["owner"] not in ("", "ble"):
                    raise dbus.exceptions.DBusException("Another client owns the radio", name="org.bluez.Error.InProgress")
                bridge.peer = device
                for command, payload in self.decoder.feed(bytes(value)):
                    if not bridge.radio.submit("remote", "ble", command, payload, bridge.reply):
                        raise dbus.exceptions.DBusException("Radio busy", name="org.bluez.Error.InProgress")

            @dbus.service.method(characteristic_interface, in_signature="a{sv}", out_signature="ay")
            def ReadValue(self, options):
                offset = int(options.get("offset", 0))
                return dbus.Array(bridge.last_value[offset:], signature="y")

            @dbus.service.method(characteristic_interface, in_signature="", out_signature="")
            def StartNotify(self):
                logging.warning("BLE KISS: notification subscription requested")
                if not self.object_path.endswith("/rx"):
                    raise dbus.exceptions.DBusException("Write only", name="org.bluez.Error.NotPermitted")
                state = bridge.radio.snapshot()
                if not state["connected"] or state["owner"] not in ("", "ble"):
                    raise dbus.exceptions.DBusException("Radio unavailable", name="org.bluez.Error.InProgress")
                self.notifying = True
                bridge.radio.submit("remote_open", "ble", bridge.reply)
                bridge.status = "Phone subscribed; starting KISS"
                for opcode, data in ((0x7e, b"\x08\x10"), (0x7b, b"\x01\x00"), (0x28, b"0.1.0")):
                    bridge.reply(kiss_encode(bytes([opcode]) + data, 6))

            @dbus.service.method(characteristic_interface, in_signature="", out_signature="")
            def StopNotify(self):
                logging.warning("BLE KISS: notification subscription ended")
                self.notifying = False
                bridge.tx.decoder = KissDecoder()
                bridge.peer = None
                while not bridge.output.empty():
                    bridge.output.get_nowait()
                bridge.radio.submit("remote", "ble", 255, b"", bridge.reply)
                bridge.status = "BLE ready"

            @dbus.service.signal(property_interface, signature="sa{sv}as")
            def PropertiesChanged(self, interface, changed, invalidated):
                pass

        class Application(dbus.service.Object):
            @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
            def GetManagedObjects(self):
                return {obj.object_path: {obj.interface: obj.properties} for obj in bridge.objects_list}

        class Advertisement(Object):
            @dbus.service.method("org.bluez.LEAdvertisement1", in_signature="", out_signature="")
            def Release(self):
                bridge.status = "BLE advertisement released"

        self.service = Object(service_path, "org.bluez.GattService1", {"UUID": service_id, "Primary": True})
        self.tx = Characteristic("/tx", service_id.replace("00000001-", "00000002-"), ["write", "write-without-response"])
        self.rx = Characteristic("/rx", service_id.replace("00000001-", "00000003-"), ["read", "notify"])
        self.objects_list = [self.service, self.tx, self.rx]
        self.application = Application(bus, root)
        self.application.object_path = root
        self.advertisement = Advertisement(root + "/advertisement", "org.bluez.LEAdvertisement1",
                                           {"Type": "peripheral", "ServiceUUIDs": dbus.Array([service_id], signature="s"),
                                            "LocalName": "B.B. Link", "Discoverable": dbus.Boolean(True)})
        objects = self.link.objects()
        adapter = next((p for p, values in objects.items() if "org.bluez.GattManager1" in values and
                        "org.bluez.LEAdvertisingManager1" in values), None)
        if not adapter:
            self._remove_objects()
            raise RuntimeError("This Bluetooth adapter cannot host BLE KISS")
        self.gatt = dbus.Interface(bus.get_object("org.bluez", adapter), "org.bluez.GattManager1")
        self.advertiser = dbus.Interface(bus.get_object("org.bluez", adapter), "org.bluez.LEAdvertisingManager1")
        self.enabled = True
        self.status = "Registering BLE KISS…"

        def failure(error):
            logging.warning("BLE KISS: registration failed: %s", error)
            self.status = "BLE error: " + str(error)
            self.enabled = False

        def registered():
            def advertised():
                self.status = "BLE ready as B.B. Link"
                logging.warning("BLE KISS: discoverable advertisement ready")
            self.advertiser.RegisterAdvertisement(self.advertisement.object_path, {},
                                                  reply_handler=advertised,
                                                  error_handler=failure)

        self.gatt.RegisterApplication(root, {}, reply_handler=registered, error_handler=failure)

        def disconnected(interface, changed, invalidated, path=None):
            if (interface == "org.bluez.Device1" and bridge.peer == str(path) and
                    "Connected" in changed and not bool(changed["Connected"])):
                bridge.rx.StopNotify()

        self.disconnect_watch = bus.add_signal_receiver(
            disconnected, dbus_interface=property_interface, signal_name="PropertiesChanged",
            path_keyword="path", bus_name="org.bluez")

        def notify():
            if not self.enabled:
                return False
            if self.rx.notifying:
                try:
                    self.last_value = self.output.get_nowait()
                except queue.Empty:
                    return True
                self.rx.PropertiesChanged(characteristic_interface,
                                          {"Value": dbus.Array(self.last_value, signature="y")}, [])
            return True
        GLib.timeout_add(15, notify)

    def _remove_objects(self):
        for obj in getattr(self, "objects_list", []):
            obj.remove_from_connection()
        for attr in ("application", "advertisement"):
            obj = getattr(self, attr, None)
            if obj:
                obj.remove_from_connection()
        self.application = None

    def close(self):
        self.enabled = False
        watch = getattr(self, "disconnect_watch", None)
        if watch:
            watch.remove()
            self.disconnect_watch = None
        if self.application:
            self.radio.submit("remote", "ble", 255, b"", self.reply)
            try:
                self.advertiser.UnregisterAdvertisement(self.advertisement.object_path)
                self.gatt.UnregisterApplication(self.application.object_path)
            except Exception:
                pass
            self._remove_objects()
        self.status = "BLE bridge off"

