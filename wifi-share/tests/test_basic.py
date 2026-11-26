"""Offline tests: run from wifi-share/ with  python3 -m unittest discover tests"""
import http.server
import os
import tempfile
import threading
import unittest
import urllib.parse

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp()

from tntshare import keys, net, portal  # noqa: E402
from tntshare import settings as S  # noqa: E402


class Terse(unittest.TestCase):
    def test_split(self):
        self.assertEqual(net.split_terse(r"*:My\:Net:80:WPA2:6"), ["*", "My:Net", "80", "WPA2", "6"])
        self.assertEqual(net.split_terse(r"a\\b:"), ["a\\b", ""])


class Settings(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(S.mask_to_prefix("255.255.255.0"), 24)
        self.assertEqual(S.mask_to_prefix("/16"), 16)
        self.assertIsNone(S.mask_to_prefix("255.0.255.0"))
        self.assertIsNone(S.check_host("192.168.50.1", "24"))
        self.assertIsNotNone(S.check_host("192.168.50.0", "24"))
        self.assertIsNotNone(S.check_host("192.168.50.300", "24"))

    def test_defaults(self):
        c = S.load()
        self.assertTrue(c["hs_ssid"].startswith("TNT-Share-"))
        self.assertEqual(len(c["hs_password"]), 10)
        self.assertIsNone(S.check_hotspot(c["hs_ssid"], c["hs_password"]))


class Keys(unittest.TestCase):
    def test_shift_caps(self):
        kb = keys.Keyboard(devices=["/nonexistent"])
        self.assertEqual(kb._feed(30, 1).char, "a")
        kb._feed(42, 1)
        self.assertEqual(kb._feed(30, 1).char, "A")
        self.assertEqual(kb._feed(3, 1).char, "@")
        kb._feed(42, 0)
        kb._feed(58, 1)
        self.assertEqual(kb._feed(30, 1).char, "A")
        self.assertEqual(kb._feed(28, 1).name, "enter")
        self.assertIsNone(kb._feed(30, 0))
        self.assertEqual(kb._feed(1, 1).name, "esc")
        self.assertIsNone(kb._feed(1, 2))       # Esc auto-repeat ignored
        self.assertEqual(kb._feed(103, 2).name, "up")  # arrows repeat
        # Sym layer codes (CardputerZero) -> printed symbols; Fn/Sym keys alone give nothing
        self.assertIsNone(kb._feed(383, 1))
        self.assertIsNone(kb._feed(389, 1))
        kb._feed(58, 1)  # caps off again
        self.assertEqual("".join(kb._feed(c, 1).char for c in (2, 91, 71, 92, 70)), "1.-/_")


PORTAL = """<html><head><title>Guest</title><meta charset=utf-8></head><body>
<form id=search action="/search"><input name=q><input type=submit value=Search></form>
<form method="post" action="/login">
<input type="hidden" name="token" value="abc">
<label for="em">Email</label><input id="em" type="email" name="email" required>
<select name="plan"><option value="free" selected>Free 1h</option><option value="paid">Paid</option></select>
<input type="checkbox" name="tos" value="yes" required> I agree to the terms
<input type="checkbox" name="news"> Send me offers
<button type="submit" name="act" value="go">Connect</button></form>
<a href="/terms">Terms</a></body></html>"""

posted = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/start"):
            self.send_response(302)
            self.send_header("Location", "/portal")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Set-Cookie", "sid=42; Path=/")
        self.end_headers()
        self.wfile.write(PORTAL.encode())

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        posted.update(urllib.parse.parse_qs(self.rfile.read(n).decode()))
        posted["cookie"] = self.headers.get("Cookie")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><title>Welcome</title><body>You are online</body></html>")


class Portal(unittest.TestCase):
    def test_parse_and_submit(self):
        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        s = portal.Session()
        page = s.fetch(base + "/start")
        self.assertEqual(page.title, "Guest")
        f = page.best_form()
        self.assertTrue(f.action.endswith("/login"))
        email = next(x for x in f.fields if x.name == "email")
        self.assertEqual(email.label, "Email")
        self.assertTrue(email.required)
        tos = next(x for x in f.fields if x.name == "tos")
        tos.checked = True
        email.value = "ted@example.com"
        res = s.submit(f)
        self.assertEqual(res.title, "Welcome")
        self.assertEqual(posted["email"], ["ted@example.com"])
        self.assertEqual(posted["tos"], ["yes"])
        self.assertNotIn("news", posted)
        self.assertEqual(posted["plan"], ["free"])
        self.assertEqual(posted["act"], ["go"])
        self.assertEqual(posted["token"], ["abc"])
        self.assertIn("sid=42", posted["cookie"])
        srv.shutdown()

    def test_js_redirect(self):
        self.assertEqual(portal._redirect_in('<script>window.location="/x?a=1"</script>', "http://h/"), "http://h/x?a=1")
        self.assertEqual(portal._redirect_in('<meta http-equiv="refresh" content="0; url=http://p/l">', "http://h/"), "http://p/l")

    def test_needs_browser(self):
        p = portal.parse("<html><body><div id=app></div><script>boot()</script></body></html>", "http://h/")
        self.assertTrue(p.needs_browser)


class UiFlow(unittest.TestCase):
    def test_form_edit_and_save(self):
        from tntshare import app as A
        from tntshare.keys import Key
        from tntshare.demo import fake_app
        app = fake_app()
        saved = {}
        app.stack = []
        A.edit_hotspot(app)
        form = app.stack[-1]
        # first row is SSID: edit it
        app.stack[-1].key(Key("enter"))
        ti = app.stack[-1]
        for _ in range(30):
            ti.key(Key("backspace"))
        for ch in "RackNet":
            ti.key(Key(ch, ch))
        ti.key(Key("enter"))
        self.assertIs(app.stack[-1], form)
        self.assertEqual(form.values["hs_ssid"], "RackNet")
        form.key(Key("s", "s"))  # S saves only on non-text rows; we're on the SSID row
        self.assertIs(app.stack[-1], form)
        for _ in range(4):
            form.key(Key("down"))
        form.key(Key("enter"))  # [ Save ]
        self.assertEqual(app.cfg["hs_ssid"], "RackNet")
        for s in app.stack:
            s.rows()


class Nav(unittest.TestCase):
    def test_standard_keys(self):
        from tntshare import app as A
        from tntshare.keys import Key
        from tntshare.demo import fake_app
        from tntshare.ui import TextInput, nav_key
        app = fake_app()
        app.status["mode"] = None
        home = A.Home(app)
        app.stack = [home]

        def press(k):
            top = app.stack[-1]
            top.key(k if top.text_entry else nav_key(k))
        press(Key("x", "x"))          # plain X = down
        self.assertEqual(home.sel, 1)
        press(Key("up"))
        self.assertEqual(home.sel, 0)
        press(Key("c", "c"))          # plain C = right = open Status
        self.assertIsInstance(app.stack[-1], A.Status)
        press(Key("z", "z"))          # plain Z = left = back
        self.assertIs(app.stack[-1], home)
        press(Key("left"))            # left on the main page does nothing
        self.assertIs(app.stack[-1], home)
        # in a text field letters type
        got = []
        app.push(TextInput(app, "t", "p", "", got.append))
        for ch in "fxzc":
            press(Key(ch, ch))
        press(Key("left"))
        press(Key("1", "1"))
        press(Key("enter"))
        self.assertEqual(got, ["fxz1c"])
        press(Key("esc"))             # ESC on the main page quits when not sharing
        self.assertTrue(app.quit)


if __name__ == "__main__":
    unittest.main()
