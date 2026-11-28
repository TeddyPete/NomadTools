"""Incoming BLE pairing must reach this app when the radio is already paired."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import dbus.service
    from gi.repository import GLib
    from rigzero.bridges import BleBridge
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False


@unittest.skipUnless(HAS_DBUS, "Run BlueZ regression on the CardputerZero")
class IncomingPhonePairTest(unittest.TestCase):
    def test_ble_start_claims_pairing_before_advertising(self):
        class Object:
            def __init__(self, bus, path):pass
            def remove_from_connection(self):pass

        ready = threading.Event()
        ready.set()
        bus, manager = Mock(), Mock()
        link = SimpleNamespace(ready=ready, error="", bus=bus, manager=manager,
                               agent=SimpleNamespace(object_path="/test/agent"),
                               objects=lambda: {"/test/hci0": {"org.bluez.GattManager1": {},
                                                               "org.bluez.LEAdvertisingManager1": {}}})
        radio = SimpleNamespace(snapshot=lambda: {"connected": True, "owner": ""}, submit=Mock())
        bridge = BleBridge(radio, link)
        gatt, advertiser = Mock(), Mock()

        def register_application(path, options, reply_handler, error_handler):
            manager.RequestDefaultAgent.assert_called_once_with("/test/agent")
            values = bridge.application.GetManagedObjects()
            tx = values["/org/rigcompanion/kiss/service0/tx"]["org.bluez.GattCharacteristic1"]
            rx = values["/org/rigcompanion/kiss/service0/rx"]["org.bluez.GattCharacteristic1"]
            self.assertEqual(set(tx["Flags"]), {"write", "write-without-response"})
            self.assertEqual(set(rx["Flags"]), {"read", "notify"})
            reply_handler()

        def register_advertisement(path, options, reply_handler, error_handler):
            props = bridge.advertisement.GetAll("org.bluez.LEAdvertisement1")
            self.assertTrue(props["Discoverable"])
            self.assertEqual(props["ServiceUUIDs"], ["00000001-ba2a-46c9-ae49-01b0961f68bb"])
            reply_handler()

        gatt.RegisterApplication.side_effect = register_application
        advertiser.RegisterAdvertisement.side_effect = register_advertisement
        with patch("dbus.service.Object", Object), patch("dbus.Interface", side_effect=lambda obj, name: gatt if name == "org.bluez.GattManager1" else advertiser), patch.object(GLib, "timeout_add"):
            try:
                bridge.start()
                self.assertEqual(bridge.status, "BLE ready as B.B. Link")
                self.assertTrue(bridge.enabled)
            finally:
                bridge.close()


if __name__ == "__main__":
    unittest.main()

