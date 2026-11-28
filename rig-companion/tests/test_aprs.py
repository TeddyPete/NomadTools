import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rigzero.aprs import decode, describe
from rigzero.protocol import inspect_packet, decode_ax25, address
from rigzero.storage import Store


class AprsReportsTest(unittest.TestCase):
    def test_position_mice_and_third_party(self):
        p = inspect_packet("KC9NVV-3", "APNX02", "", "!4515.10N/09238.77W#PHG5450 W2, Osceola")
        self.assertAlmostEqual(p["decoded"]["lat"], 45.2516667, places=5)
        self.assertAlmostEqual(p["decoded"]["lon"], -92.6461667, places=5)
        detail = describe(p)["details"]
        self.assertIn("25 W", detail)
        self.assertIn("160 ft", detail)
        self.assertIn("omnidirectional", detail)
        third = inspect_packet("IGATE", "APRS", "", "}INNER-7>APRS:!4515.10N/09238.77W#Test")
        self.assertEqual(third["sender"], "INNER-7")
        self.assertIn("lat", third["decoded"])
        mice = decode("TEST", "SUSUR1", '`CF"l#![/`"3z}_ ')
        self.assertAlmostEqual(mice["lat"], 35.5868333, places=5)
        self.assertAlmostEqual(mice["lon"], 139.701, places=5)
        raw = address("APRS") + address("TEST", last=True) + b"\x03\xf0`\xa0abcde[/"
        self.assertEqual(decode_ax25(raw)[3].encode("latin-1"), raw[16:])
        self.assertNotIn("lat", decode("TEST", "APRS", "!4599.99N/09238.77W#bad minutes"))

    def test_labels_calibration_replay_and_map_stations(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            try:
                position = inspect_packet("N0TEST-7", "APRS", "", "!4503.79N/09309.32W-Test")
                store.record(position)
                store.record(inspect_packet("N0TEST-7", "APRS", "", "T#016,122,075,999,451,328,00000000"))
                raw = store.rows()[0]
                self.assertEqual(raw["kind"], "Telemetry")
                self.assertIn("122 raw", raw["details"])
                self.assertEqual(len(store.stations()), 1)
                for text in ("PARM.Battery,Temperature", "UNIT.V,C", "EQNS.0,0.1,0,0,1,-40"):
                    store.record(inspect_packet("N0TEST-7", "APRS", "", ":N0TEST-7 :" + text))
                self.assertEqual(store.rows("inbox"), [])
                telemetry = next(p for p in store.rows() if p["kind"] == "Telemetry")
                self.assertIn("Battery: 12.2 V", telemetry["details"])
                self.assertIn("Temperature: 35 C", telemetry["details"])
                self.assertIn("999 raw", telemetry["details"])
                store.save(telemetry["id"])
                stamp = telemetry["time"]
                store.close()
                store = Store(Path(folder))
                self.assertEqual(store.rows("saved")[0]["time"], stamp)
                self.assertIn("12.2 V", store.rows("saved")[0]["details"])
                # Upgrade an old stored position without losing its ID or timestamp.
                old = dict(position)
                old.pop("decoded")
                store.db.execute("UPDATE packets SET body=? WHERE id=1", (json.dumps(old),))
                store.set("report_format", 0)
                store.close()
                store = Store(Path(folder))
                mapped = store.stations()[0]
                self.assertEqual((mapped["id"], mapped["time"]), (1, position["time"]))
            finally:
                store.close()

    def test_object_removal_and_bad_packets(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            try:
                for state in ("*", "_"):
                    store.record(inspect_packet("N0TEST", "APRS", "", f";{'LOCAL':9}{state}271530z4503.79N/09309.32W-Test"))
                self.assertEqual(store.stations(), [])
            finally:
                store.close()
        rng = random.Random(8)
        for _ in range(600):
            body = rng.choice(["!", "'", "`", "T#", ";", ")", ":"]) + "".join(chr(rng.randrange(256)) for _ in range(rng.randrange(80)))
            packet = inspect_packet("N0TEST", "APRS", "", body)
            describe(packet)
            if "lat" in packet["decoded"]:
                self.assertTrue(-90 <= packet["decoded"]["lat"] <= 90)


if __name__ == "__main__":
    unittest.main()
