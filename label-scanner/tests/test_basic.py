"""Offline tests: run from label-scanner/ with  python3 -m unittest discover tests"""
import io
import os
import shutil
import tempfile
import unittest
import zipfile

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["NOMAD_SCAN_ROOT"] = tempfile.mkdtemp()
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from nomadscan import decode, export, parse, store  # noqa: E402


class Parse(unittest.TestCase):
    def test_mac_spellings(self):
        for t in ("MAC 00:10:7F:12:34:56", "00-10-7f-12-34-56", "HW 00.10.7F.12.34.56",
                  "0010.7f12.3456", "MAC ADDR 00:1O:7F:I2:34:56", "Ethernet: 00107F123456"):
            self.assertEqual(parse.extract([], t).mac, "00:10:7F:12:34:56", t)

    def test_ip_not_from_mac(self):
        self.assertEqual(parse.extract([], "00.05.a6.11.22.33").ip, "")
        self.assertEqual(parse.extract([], "IP: 192.168.1.10").ip, "192.168.1.10")

    def test_label_words(self):
        f = parse.extract([], "MODEL NO. TSW-1070-B-S\nSERIAL NO. 1904ABC1234\nPart No. 60-1234-01")
        self.assertEqual((f.model, f.serial), ("TSW-1070-B-S", "1904ABC1234"))
        self.assertIn(("model", "60-1234-01"), f.others)

    def test_barcodes(self):
        f = parse.extract([("CODE128", "1904ABC1234"), ("CODE128", "00107F123456")], "")
        self.assertEqual((f.serial, f.mac), ("1904ABC1234", "00:10:7F:12:34:56"))
        f = parse.extract([("QRCODE", "MAC:00107f123456;SN:XYZ999")])
        self.assertEqual((f.serial, f.mac), ("XYZ999", "00:10:7F:12:34:56"))
        f = parse.extract([("CODE128", "S/N 55AA1")])
        self.assertEqual(f.serial, "55AA1")


class Exports(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(store.data_root(), ignore_errors=True)
        store.save("Hotel Ballroom", [store.Item("DSP", "Tesira", "00123", "00:90:5E:11:22:33", codes=["A&B<1>"])])
        store.save("Rack: 2/3", [])

    def test_csv(self):
        data = export.csv_bytes(store.load("Hotel Ballroom")).decode("utf-8-sig")
        self.assertIn("00123", data)
        self.assertTrue(data.startswith("#,Device,Model,Serial,MAC"))

    def test_xlsx_one_sheet_per_job(self):
        p = export.export_all()
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            wb = z.read("xl/workbook.xml").decode()
            s1 = z.read("xl/worksheets/sheet2.xml").decode()
        self.assertIn("xl/worksheets/sheet2.xml", names)
        self.assertIn('name="Hotel Ballroom"', wb)
        self.assertIn('name="Rack 23"', wb)          # sheet names can't hold : or /
        self.assertIn("A&amp;B&lt;1&gt;", s1)
        try:
            import openpyxl
        except ImportError:
            return
        wb = openpyxl.load_workbook(io.BytesIO(open(p, "rb").read()))
        ws = wb["Hotel Ballroom"]
        self.assertEqual(ws["D2"].value, "00123")    # serial stays text, keeps the zeros

    def test_rename_delete(self):
        self.assertTrue(store.rename("Hotel Ballroom", "Hotel B"))
        self.assertEqual(store.load("Hotel B")[0].serial, "00123")
        store.delete("Hotel B")
        self.assertNotIn("Hotel B", store.jobs())


@unittest.skipUnless(decode.have_zbar() and decode.have_ocr(), "needs zbar + tesseract")
class ReadLabel(unittest.TestCase):
    def test_synthetic_label(self):
        import numpy as np
        from nomadscan.demo import label_image
        gray = np.asarray(label_image().convert("L"))
        codes = decode.barcodes(gray)
        f = parse.extract(codes, decode.ocr(gray))
        self.assertEqual(f.serial, "1904ABC1234")
        self.assertEqual(f.mac, "00:10:7F:3A:9C:21")
        self.assertEqual(f.model, "DM-NVX-360")


if __name__ == "__main__":
    unittest.main()
