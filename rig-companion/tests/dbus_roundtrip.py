"""Device-only regression: pending pairing must not stall the agent's reply.

Run: dbus-run-session -- python3 tests/dbus_roundtrip.py
The isolated session bus and fake peer never access Bluetooth or a radio.
"""
import queue
import subprocess
import sys
import threading
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rigzero.bluetooth import BluetoothLink

DBusGMainLoop(set_as_default=True)


def server():
    bus = dbus.SessionBus(private=True)
    name = dbus.service.BusName("org.rigcompanion.PairFixture", bus)

    class Peer(dbus.service.Object):
        @dbus.service.method("org.rigcompanion.Peer", in_signature="", out_signature="",
                             sender_keyword="sender", async_callbacks=("accept", "reject"))
        def Pair(self, sender, accept, reject):
            agent = dbus.Interface(bus.get_object(sender, "/org/rigcompanion/agent"), "org.bluez.Agent1")
            agent.RequestConfirmation("/org/radio", dbus.UInt32(123456),
                                      reply_handler=accept, error_handler=reject, timeout=4)

    peer = Peer(bus, "/org/radio")
    print("ready", flush=True)
    GLib.MainLoop().run()


def check(mode):
    child = subprocess.Popen([sys.executable, __file__, "server"], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        link = BluetoothLink.__new__(BluetoothLink)
        link.events = queue.Queue()
        link.waiting_confirmation = None
        bus = dbus.SessionBus(private=True)

        class Agent(dbus.service.Object):
            @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="",
                                 async_callbacks=("accept", "reject"))
            def RequestConfirmation(self, device, number, accept, reject):
                link.waiting_confirmation = (accept, reject)
                link.events.put("confirm")

        agent = Agent(bus, "/org/rigcompanion/agent")
        loop = GLib.MainLoop()
        thread = threading.Thread(target=loop.run, daemon=True)
        thread.start()
        peer = dbus.Interface(bus.get_object("org.rigcompanion.PairFixture", "/org/radio"),
                              "org.rigcompanion.Peer")
        result = queue.Queue()

        def work():
            try:
                if mode == "sync":
                    peer.Pair(timeout=3)
                else:
                    link._call(peer.Pair, timeout=3)
                result.put("ok")
            except Exception as error:
                result.put(type(error).__name__)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        assert link.events.get(timeout=5) == "confirm"
        link.confirm(mode != "decline")
        outcome = result.get(timeout=5)
        print(mode, outcome)
        loop.quit()
        worker.join(1)
        thread.join(1)
        agent.remove_from_connection()
        bus.close()
        if mode == "async":
            assert outcome == "ok", outcome
        else:
            assert outcome != "ok", outcome
        return outcome
    finally:
        child.terminate()
        child.wait(timeout=2)


if __name__ == "__main__":
    if sys.argv[-1] == "server":
        server()
    else:
        check(sys.argv[-1] if sys.argv[-1] in ("sync", "decline") else "async")
