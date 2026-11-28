import json
from io import BytesIO
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from rigzero.mapview import StationMap, TileCache, point
    from rigzero.display import Display
    from rigzero.app import App
    from rigzero.storage import Store
    from rigzero.protocol import inspect_packet
    HAS_DISPLAY = True
except ImportError:
    HAS_DISPLAY = False


@unittest.skipUnless(HAS_DISPLAY, "Run display/map tests on the CardputerZero")
class StationMapTest(unittest.TestCase):
    def test_cache_honors_headers_and_offline_data(self):
        from PIL import Image
        out = BytesIO()
        Image.new("RGB", (256, 256), "#eeeeee").save(out, format="PNG")

        class Response:
            headers = {"Cache-Control": "max-age=604800", "ETag": "fixture"}
            code = 200
            def __enter__(self):return self
            def __exit__(self, *_):pass
            def read(self, size):return out.getvalue()[:size]

        with tempfile.TemporaryDirectory() as folder:
            cache = TileCache(Path(folder), enabled=False)
            with patch("rigzero.mapview.urlopen", return_value=Response()) as request:
                cache._fetch((8, 64, 92))
                self.assertEqual(request.call_count, 1)
                self.assertTrue(request.call_args.args[0].full_url.startswith("https://tile.openstreetmap.org/"))
                self.assertIn("RigCompanionZero", request.call_args.args[0].get_header("User-agent"))
                cache._fetch((8, 64, 92))
                self.assertEqual(request.call_count, 1)
            with patch("rigzero.mapview.urlopen", side_effect=OSError("offline")):
                cache._fetch((8, 64, 92))
                self.assertTrue(cache.path((8, 64, 92)).exists())
            meta = json.loads(cache.path((8, 64, 92)).with_suffix(".json").read_text())
            self.assertGreater(meta["expires"], 0)
            cache.close()

    def test_navigation_details_and_map_do_not_change_radio(self):
        class Radio:
            def snapshot(self):return {"kiss": True, "fresh": False, "connected": True, "owner": "local", "error": ""}
            def submit(self, *args):raise AssertionError("Map must not control or transmit through the radio")

        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "store")
            map_view = StationMap(Path(folder) / "tiles", network=False)
            display = Display(headless=True)
            app = App(store, Radio(), display)
            app.map_view = map_view
            try:
                for source, lon in (("WEST", 179.9), ("EAST", -179.9)):
                    packet = inspect_packet(source, "APRS", "", ">fixture")
                    packet["decoded"] = {"lat": 45, "lon": lon}
                    store.record(packet)
                stations = store.stations()
                map_view.fit(stations)
                self.assertGreater(abs(map_view.center[1]), 179)
                map_view.choose(stations, stations[0])
                app.page = 1
                app.handle("text", "m")
                app.draw()
                self.assertTrue(app.map_active)
                zoom = map_view.zoom
                app.handle("text", "6")
                self.assertEqual(map_view.zoom, min(18, zoom + 1))
                app.handle("right")
                app.handle("tab")
                app.handle("enter")
                self.assertFalse(app.map_active)
                app.draw()
                self.assertIn("45.00000", app.detail["details"])
                app.handle("text", "t")
                self.assertTrue(app.raw_detail)
                app.draw()
                app.handle("text", "6")
                self.assertEqual(len(store.rows("saved")), 1)
                app.handle("text", "7")
                self.assertEqual(app.editor, "compose")
                self.assertIn(app.compose["to"], ("EAST", "WEST"))
                app.editor = None
                app.handle("left")
                self.assertIsNone(app.detail)
                app.page, app.selected = 1, 0
                app.handle("right")
                self.assertIsNotNone(app.detail)
                app.handle("text", "8")
                self.assertTrue(app.raw_detail)
                app.handle("text", "5")
                self.assertTrue(app.map_active)
                app.handle("esc")
                self.assertFalse(app.map_active)
                app.handle("text", "z")
                self.assertIsNone(app.detail)
                app.handle("left")
                self.assertEqual(app.page, 0)
                self.assertTrue(all(abs(v) < 1e10 for v in point(90, 180, 18)))
            finally:
                app.close()
                store.close()
                display.close()


if __name__ == "__main__":
    unittest.main()
