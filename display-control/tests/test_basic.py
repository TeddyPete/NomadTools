"""Offline tests with fake displays: run from display-control/ with
    python3 -m unittest discover tests"""
import base64
import hashlib
import http.server
import json
import os
import socket
import socketserver
import struct
import tempfile
import threading
import unittest

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()

from tntdisp import ops, store, wol  # noqa: E402
from tntdisp.base import Display, DisplayError  # noqa: E402
from tntdisp.lgwebos import LGWebOS, app_label  # noqa: E402
from tntdisp.pjlink import PJLink  # noqa: E402
from tntdisp.roku import Roku  # noqa: E402
from tntdisp.sony import Sony, uri_label  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---- fake PJLink projector ------------------------------------------------

class FakeProjector:
    def __init__(self, password="", pclass="2"):
        self.password, self.pclass = password, pclass
        self.state = {"POWR": "1", "INPT": "31", "AVMT": "30"}
        self.log = []
        self.port = free_port()
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", self.port))
        self.srv.listen(5)
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(c,), daemon=True).start()

    def serve(self, c):
        rnd = "498e4a67"
        c.sendall(f"PJLINK 1 {rnd}\r".encode() if self.password else b"PJLINK 0\r")
        first = True
        buf = b""
        while True:
            try:
                d = c.recv(256)
            except OSError:
                return
            if not d:
                return
            buf += d
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                t = line.decode()
                if self.password and first:
                    want = hashlib.md5((rnd + self.password).encode()).hexdigest()
                    if t[:32] != want:
                        c.sendall(b"PJLINK ERRA\r")
                        c.close()
                        return
                    t = t[32:]
                first = False
                self.log.append(t)
                c.sendall((self.reply(t) + "\r").encode())

    def reply(self, t):
        head, arg = t[:6], t[7:]
        cmd = t[2:6]
        if arg == "?" or arg.startswith("?"):
            v = {"POWR": self.state["POWR"], "INPT": self.state["INPT"], "AVMT": self.state["AVMT"],
                 "ERST": "000000", "NAME": "Ballroom", "INF1": "EPSON", "INF2": "EB-L1505U", "INFO": "x",
                 "CLSS": self.pclass, "LAMP": "1234 1", "INST": "11 31 32", "SNUM": "X123", "SVER": "1.0",
                 "FILT": "200", "IRES": "1920x1080", "RRES": "1920x1200",
                 "INNM": {"11": "Computer", "31": "HDMI1", "32": "HDBaseT"}.get(arg[1:], "ERR2")}.get(cmd, "ERR1")
            return f"{head}={v}"
        if cmd in self.state:
            self.state[cmd] = arg
            return f"{head}=OK"
        if cmd == "SVOL":
            return f"{head}=OK" if self.pclass == "2" else f"{head}=ERR1"
        return f"{head}=ERR1"


class PJLinkTest(unittest.TestCase):
    def test_no_password(self):
        fp = FakeProjector()
        p = PJLink(Display("P", "pjlink", "127.0.0.1", fp.port))
        st = p.status()
        self.assertEqual(st["power"], "on")
        self.assertEqual(st["input"], "Digital 1")
        self.assertIn("Power off", p.power(False))
        self.assertEqual(fp.state["POWR"], "0")
        ins = p.inputs()
        self.assertEqual(ins[1], ("31", "HDMI1 (Digital 1)"))
        p.set_input("32")
        self.assertEqual(fp.state["INPT"], "32")
        self.assertEqual(p.mute(), "Audio muted")
        self.assertEqual(fp.state["AVMT"], "21")
        self.assertEqual(p.avmute(True), "Picture and sound muted")
        self.assertEqual(fp.state["AVMT"], "31")
        self.assertEqual(p.mute(), "Audio unmuted")   # 31 counts as audio muted
        info = dict(p.info())
        self.assertEqual(info["Model"], "EB-L1505U")
        self.assertEqual(info["Lamp hours"], "1234 h")
        self.assertEqual(p.volume(2), "Volume up")

    def test_password(self):
        fp = FakeProjector(password="secret", pclass="1")
        good = PJLink(Display("P", "pjlink", "127.0.0.1", fp.port, secret="secret"))
        self.assertEqual(good.status()["power"], "on")
        bad = PJLink(Display("P", "pjlink", "127.0.0.1", fp.port, secret="nope"))
        with self.assertRaises(DisplayError) as e:
            bad.status()
        self.assertIn("password", str(e.exception))
        with self.assertRaises(DisplayError):
            good.volume(1)          # class 1 has no volume

    def test_no_answer(self):
        p = PJLink(Display("P", "pjlink", "127.0.0.1", free_port()), timeout=1)
        with self.assertRaises(DisplayError):
            p.status()


# ---- fake HTTP displays (Sony, Roku) --------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def reply(self, code, body, ctype="application/json"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        Handler.calls.append(("GET", self.path))
        if self.path == "/query/device-info":
            self.reply(200, "<device-info><friendly-device-name>Green room</friendly-device-name>"
                            "<power-mode>DisplayOff</power-mode><is-tv>true</is-tv>"
                            "<wifi-mac>d8:31:34:00:00:01</wifi-mac></device-info>", "text/xml")
        elif self.path == "/query/active-app":
            self.reply(200, '<active-app><app id="tvinput.hdmi2">HDMI 2</app></active-app>', "text/xml")
        elif self.path == "/query/apps":
            self.reply(200, '<apps><app id="tvinput.hdmi1" type="tvin">HDMI 1</app>'
                            '<app id="12" type="appl">Netflix</app></apps>', "text/xml")
        else:
            self.reply(404, "")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        Handler.calls.append(("POST", self.path, body, self.headers.get("X-Auth-PSK")))
        if self.path.startswith("/sony/"):
            if self.headers.get("X-Auth-PSK") != "1234":
                return self.reply(403, "")
            m = json.loads(body)["method"]
            res = {"getPowerStatus": [{"status": "active"}],
                   "getVolumeInformation": [[{"target": "speaker", "volume": 12, "mute": False}]],
                   "getPlayingContentInfo": [{"uri": "extInput:hdmi?port=2"}],
                   "getCurrentExternalInputsStatus": [[{"uri": "extInput:hdmi?port=1", "title": "HDMI 1", "label": "PC"}]],
                   "getPictureQualitySettings": [[{"target": "pictureMode", "currentValue": "standard",
                                                   "candidate": [{"value": "vivid"}, {"value": "standard"}]}]],
                   }.get(m, [])
            return self.reply(200, json.dumps({"result": res, "id": 1}))
        self.reply(200, "")


class Http:
    def __init__(self):
        self.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


class SonyRoku(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = Http()

    def test_sony(self):
        s = Sony(Display("S", "sony", "127.0.0.1", self.h.port, secret="1234"))
        st = s.status()
        self.assertEqual((st["power"], st["volume"], st["input"]), ("on", 12, "HDMI 2"))
        self.assertEqual(s.inputs(), [("extInput:hdmi?port=1", "HDMI 1 (PC)")])
        self.assertEqual(s.picture_modes(), (["vivid", "standard"], "standard"))
        s.volume(-2)
        self.assertIn(b'"-2"', Handler.calls[-1][2])
        bad = Sony(Display("S", "sony", "127.0.0.1", self.h.port, secret="x"))
        with self.assertRaises(DisplayError):
            bad.status()
        self.assertEqual(uri_label("extInput:component?port=1"), "COMPONENT 1")

    def test_roku(self):
        r = Roku(Display("R", "roku", "127.0.0.1", self.h.port))
        st = r.status()
        self.assertEqual((st["power"], st["input"]), ("standby", "HDMI 2"))
        self.assertEqual(r.inputs(), [("launch:tvinput.hdmi1", "HDMI 1")])
        r.power(True)
        self.assertEqual(Handler.calls[-1][1], "/keypress/PowerOn")
        r.set_input("launch:tvinput.hdmi1")
        self.assertEqual(Handler.calls[-1][1], "/launch/tvinput.hdmi1")


# ---- fake LG webOS (plain WebSocket on port 3000 style) --------------------

def ws_server(handler):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)

    def loop():
        while True:
            c, _ = srv.accept()
            threading.Thread(target=serve, args=(c,), daemon=True).start()

    def serve(c):
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += c.recv(1024)
        key = [l.split(b": ")[1] for l in buf.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
        acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  b"Sec-WebSocket-Accept: " + acc + b"\r\n\r\n")

        def recv():
            h = c.recv(2)
            if len(h) < 2:
                return None
            n = h[1] & 127
            if n == 126:
                n = struct.unpack(">H", c.recv(2))[0]
            m = c.recv(4)
            d = b""
            while len(d) < n:
                d += c.recv(n - len(d))
            return json.loads(bytes(b ^ m[i % 4] for i, b in enumerate(d)))

        def send(o):
            d = json.dumps(o).encode()
            h = bytes([0x81]) + (bytes([len(d)]) if len(d) < 126 else bytes([126]) + struct.pack(">H", len(d)))
            c.sendall(h + d)
        try:
            while True:
                m = recv()
                if m is None:
                    return
                for r in handler(m):
                    send(r)
        except OSError:
            pass
    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1]


class LGTest(unittest.TestCase):
    def test_flow(self):
        seen = []

        def tv(m):
            seen.append(m)
            if m["type"] == "register":
                if m["payload"].get("client-key") == "goodkey":
                    return [{"type": "registered", "id": m["id"], "payload": {"client-key": "goodkey"}}]
                return [{"type": "response", "id": m["id"], "payload": {"pairingType": "PROMPT"}}]
            uri = m["uri"]
            pl = {"returnValue": True}
            if uri.endswith("getVolume"):
                pl.update(volumeStatus={"volume": 9, "muteStatus": False})
            if uri.endswith("getPowerState"):
                pl.update(state="Active")
            if uri.endswith("getForegroundAppInfo"):
                pl.update(appId="com.webos.app.hdmi2")
            if uri.endswith("getExternalInputList"):
                pl.update(devices=[{"id": "HDMI_1", "label": "HDMI 1"}, {"id": "HDMI_2", "label": "Laptop"}])
            return [{"type": "event", "id": "other", "payload": {}}, {"type": "response", "id": m["id"], "payload": pl}]
        port = ws_server(tv)
        d = Display("TV", "lg", "127.0.0.1", 3000, secret="goodkey")
        lg = LGWebOS(d)
        lg.d.port = port
        import tntdisp.lgwebos as M
        orig = M.WebSocket.__init__

        def plain(self, host, p, path="/", tls=False, timeout=5.0):
            orig(self, host, p, path, False, timeout)
        M.WebSocket.__init__ = plain
        try:
            st = lg.status()
            self.assertEqual((st["power"], st["volume"], st["input"]), ("on", 9, "HDMI 2"))
            self.assertEqual(lg.inputs()[1], ("HDMI_2", "Laptop"))
            self.assertEqual(lg.mute(), "Muted")
            self.assertEqual(seen[-1]["payload"], {"mute": True})
            self.assertEqual(lg.message("hi"), "Message shown")
            lg.d.secret = "bad"
            with self.assertRaises(DisplayError):
                lg.status()
            lg.d.secret = ""
            with self.assertRaises(DisplayError):
                lg.volume(1)
        finally:
            M.WebSocket.__init__ = orig
        self.assertEqual(app_label("com.webos.app.livetv"), "Live TV")


class Misc(unittest.TestCase):
    def test_store(self):
        ds = [Display("Lobby", "lg", "10.0.0.5", room="Lobby"), Display("Proj", "pjlink", "10.0.0.6", secret="pw")]
        store.save(ds)
        back = store.load()
        self.assertEqual([d.name for d in back], ["Lobby", "Proj"])
        self.assertTrue(all(d.id for d in back))
        self.assertEqual(oct(os.stat(store.CONF).st_mode & 0o777), "0o600")
        self.assertEqual(store.find(back, "pro").host, "10.0.0.6")
        self.assertEqual(store.rooms(back), ["Lobby"])

    def test_wol(self):
        self.assertEqual(wol.norm_mac("3034DB6EBC84"), "30:34:db:6e:bc:84")
        self.assertIsNone(wol.norm_mac("zz"))
        with self.assertRaises(ValueError):
            wol.wake("nope")

    def test_group(self):
        fp = FakeProjector()
        ds = [Display("A", "pjlink", "127.0.0.1", fp.port, id="a"),
              Display("B", "pjlink", "127.0.0.1", free_port(), id="b"),
              Display("C", "roku", "127.0.0.1", free_port(), id="c")]
        for d in ds:
            d.timeout = 1
        res = ops.group(ds, "mute", "on")
        self.assertEqual([ok for _, ok, _ in res], [True, False, False])
        self.assertIn("toggle-only", res[2][2])
        self.assertEqual(ops.summary(res), "1 of 3 OK")

    def test_screens(self):
        from tntdisp.demo import render_screens
        files = render_screens(tempfile.mkdtemp())
        self.assertEqual(len(files), 6)


if __name__ == "__main__":
    unittest.main()
