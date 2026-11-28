"""Render example screens without connecting to or transmitting through a radio."""
from pathlib import Path
import tempfile

from .display import Display
from .protocol import inspect_packet
from .storage import Store


def render_previews(folder: Path):
    from .app import App
    from .radio import Radio
    with tempfile.TemporaryDirectory(prefix="rig-zero-preview-") as temp:
        store = Store(Path(temp))
        store.set("callsign", "N0CALL-7")
        store.record(inspect_packet("N0WX-1", "APRS", "WIDE1-1", "_11061542c315s012g023t041r003h74b10182"))
        store.record(inspect_packet("N0TEST-5", "APRS", "", ":N0CALL-7 :Hello from the trail"))
        store.record(inspect_packet("N0TEST-9", "APRS", "WIDE1-1", "!4503.79N/09309.32W-Portable station"))
        store.record(inspect_packet("N0TEST-3", "APRS", "WIDE1-1", "!4515.10N/09238.77W#PHG5450 Test digipeater"))
        store.record(inspect_packet("N0TEST-9", "APRS", "", "T#016,122,075,099,045,128,00000000"))
        radio = Radio(store)
        radio.update(identity=True, connected=True, status="TH-D75 connected")
        import time
        radio.identified_at = time.monotonic()
        radio.state["bands"] = [{"hz": 144390000, "mode": 0, "power": 2, "channel": 0,
                                 "squelch": 1, "meter": 6, "busy": 1},
                                {"hz": 14074000, "mode": 4, "power": 1, "channel": 0,
                                 "squelch": 1, "meter": 2, "busy": 0}]
        radio.state["volume"] = 36
        screen = Display(headless=True)
        app = App(store, radio, screen)
        folder.mkdir(parents=True, exist_ok=True)
        for page, name in enumerate(("radio", "traffic", "inbox", "weather", "link")):
            app.page = page
            app.draw()
            screen.save(folder / (name + ".png"))
        app.page = 1
        app.detail = next(p for p in store.rows() if p["kind"] == "Telemetry")
        app.draw()
        screen.save(folder / "telemetry.png")
        app.detail = next(p for p in store.rows() if p["kind"] == "Position")
        app.draw()
        screen.save(folder / "position.png")
        from .mapview import StationMap
        app.map_view = StationMap(folder / "map-preview-cache", network=False)
        app.map_active = True
        app.detail = None
        app.draw()
        screen.save(folder / "map-offline.png")
        app.map_active = False
        app.detail = store.rows("inbox")[0]
        app.scroll = 0
        app.draw()
        screen.save(folder / "message.png")
        app.open_compose("N0TEST-5")
        app.compose["text"] = "Thanks! Good copy here."
        app.draw()
        screen.save(folder / "compose.png")
        app.editor = None
        app.detail = None
        radio.update(identity=False, connected=False)
        app.page = 0
        app.draw()
        screen.save(folder / "disconnected.png")
        app.close()
        radio.close()
        store.close()

