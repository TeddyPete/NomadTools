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
    def test_form_edit_in_place_and_save(self):
        from tntshare import app as A
        from tntshare.keys import Key
        from tntshare.demo import fake_app
        from tntshare.ui import nav_key
        app = fake_app()
        app.stack = []
        A.edit_hotspot(app)
        form = app.stack[-1]

        def press(k):
            top = app.stack[-1]
            top.key(k if top.text_entry else nav_key(k))
        press(Key("enter"))                 # OK on SSID: edit right there (red)
        self.assertIs(app.stack[-1], form)
        self.assertTrue(form.text_entry)
        self.assertEqual(form.form.view()[0].state, "editing")
        for _ in range(30):
            press(Key("backspace"))
        for ch in "fixed":                  # f and x type while editing
            press(Key(ch, ch))
        press(Key("enter"))                 # OK saves the field, back to moving
        self.assertFalse(form.text_entry)
        self.assertEqual(form.values["hs_ssid"], "fixed")
        press(Key("right"))                 # Right also starts editing
        press(Key("z", "z"))
        press(Key("esc"))                   # ESC cancels the edit only
        self.assertIs(app.stack[-1], form)
        self.assertEqual(form.values["hs_ssid"], "fixed")
        press(Key("x", "x"))                # plain X moves down
        self.assertEqual(form.form.current.key, "hs_password")
        press(Key("x", "x"))
        press(Key("enter"))                 # choice field: OK cycles 6 -> 11
        self.assertEqual(form.values["hs_channel"], "11")
        press(Key("x", "x"))
        press(Key("enter"))                 # ip field: letters are ignored
        press(Key("a", "a"))
        press(Key("esc"))
        press(Key("x", "x"))
        press(Key("enter"))                 # [ Save ]
        self.assertEqual(app.cfg["hs_ssid"], "fixed")
        self.assertEqual(app.cfg["hs_channel"], "11")
        for s in app.stack:
            s.rows()

    def test_esc_with_changes_asks(self):
        from tntshare import app as A
        from tntshare.keys import Key
        from tntshare.demo import fake_app
        from tntshare.ui import Confirm
        app = fake_app()
        app.stack = [A.Home(app)]
        A.edit_ethernet(app)
        form = app.stack[-1]
        form.key(Key("down"))  # DHCP server row (after header and IP/mask)
        while form.form.current.kind != "bool":
            form.key(Key("down"))
        form.key(Key("enter"))
        form.key(Key("esc"))
        self.assertIsInstance(app.stack[-1], Confirm)
        app.stack[-1].key(Key("esc"))       # discard
        self.assertIsInstance(app.stack[-1], A.Home)


class Nav(unittest.TestCase):
    def test_standard_keys(self):
        from tntshare import app as A
        from tntshare.keys import Key
        from tntshare.demo import fake_app
        from tntshare.ui import Prompt, nav_key
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
        app.push(Prompt(app, "t", "p", "", got.append))
        for ch in "fxzc":
            press(Key(ch, ch))
        press(Key("left"))
        press(Key("1", "1"))
        press(Key("enter"))
        self.assertEqual(got, ["fxz1c"])
        self.assertIs(app.stack[-1], home)
        press(Key("esc"))             # ESC on the main page quits when not sharing
        self.assertTrue(app.quit)


if __name__ == "__main__":
    unittest.main()


class PowerFeatures(unittest.TestCase):
    def _helper(self):
        import importlib.machinery
        import importlib.util
        path = os.path.join(os.path.dirname(__file__), "..", "packaging", "net-helper")
        loader = importlib.machinery.SourceFileLoader("nethelper", path)
        spec = importlib.util.spec_from_loader("nethelper", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def cfg(self):
        c = S.load()
        c["devices"] = {"00:05:A6:1C:22:10": dict(name="DSP rack 1", reserve=True, ip="192.168.50.12",
                                                   down="10 Mb/s", up="Off", block=False),
                        "a4:83:e7:11:22:33": dict(block=True),
                        "bad": dict(block=True)}
        c["forwards"] = [dict(name="web", proto="TCP", port="8080", ip="192.168.50.12", to_port="80"),
                         dict(name="x", proto="tcp", port="99999", ip="192.168.50.12", to_port="80")]
        c["dns_names"] = [dict(name="dsp1.av", ip="192.168.50.12"), dict(name="bad name", ip="1.2.3.4")]
        c["limit_all_down"] = "50 Mb/s"
        return c

    def test_policy(self):
        p = net.build_policy(self.cfg())
        self.assertEqual(p["block"], ["a4:83:e7:11:22:33"])
        self.assertEqual(p["reservations"], [dict(mac="00:05:a6:1c:22:10", ip="192.168.50.12", name="DSP-rack-1")])
        self.assertEqual(p["limits"], [dict(ip="192.168.50.12", down_kbytes=1250, up_kbytes=0)])
        self.assertEqual(p["forwards"], [dict(proto="tcp", port=8080, ip="192.168.50.12", to_port=80)])
        self.assertEqual(p["dns"], [dict(name="dsp1.av", ip="192.168.50.12")])
        self.assertEqual(p["all_down_kbytes"], 6250)
        self.assertTrue(p["nat"])
        self.assertEqual(net._mbit("Off"), 0)

    def test_helper_rules_are_checked(self):
        h = self._helper()
        p = net.build_policy(self.cfg())
        p["forwards"].append(dict(proto="tcp", port=80, ip="1.2.3.4; flush ruleset", to_port=80))
        p["block"].append('00:11:22:33:44:55" accept; #')
        t, text = h.ruleset("eth0.20", p)
        self.assertEqual(t, "tnt_share_eth0_20")
        self.assertIn('iifname "eth0.20" ether saddr @blocked drop', text)
        self.assertIn("tcp dport 8080 dnat to 192.168.50.12:80", text)
        self.assertIn("ip daddr 192.168.50.12 limit rate over 1250 kbytes/second", text)
        self.assertIn("masquerade", text)
        self.assertNotIn("flush", text)
        self.assertNotIn("accept; #", text)
        d = h.dnsmasq_text(p)
        self.assertIn("dhcp-host=00:05:a6:1c:22:10,192.168.50.12,DSP-rack-1", d)
        self.assertIn("host-record=dsp1.av,192.168.50.12", d)
        _, bridge = h.ruleset("tntbr0", {"nat": False})
        self.assertNotIn("masquerade", bridge)
        self.assertEqual(h.main(["x", "start", "eth0; rm -rf /"]), 2)

    def test_wg_parse(self):
        good = "[Interface]\nPrivateKey = a\nAddress = 10.0.0.2/32\n[Peer]\nPublicKey = b\nEndpoint = vpn:51820\nAllowedIPs = 0.0.0.0/0\n"
        self.assertIsNone(net.wg_parse(good))
        self.assertIsNotNone(net.wg_parse("hello"))
        net.wg_save(good)
        self.assertEqual(net.wg_info()["endpoint"], "vpn:51820")
        self.assertEqual(oct(os.stat(S.WG_CONF).st_mode & 0o777), "0o600")

    def test_lldp_parse(self):
        out = ("NEIGHBOR[0].DEVICE:eth0\nNEIGHBOR[0].CHASSIS-ID:00\\:11\nNEIGHBOR[0].PORT-ID:12\n"
               "NEIGHBOR[0].PORT-DESCRIPTION:Stage left\nNEIGHBOR[0].SYSTEM-NAME:M4250\n"
               "NEIGHBOR[0].IEEE-802-1-PVID:20\n")
        old = net.nm
        net.nm = lambda *a, **k: (0, out, "")
        try:
            n = net.lldp("eth0")
        finally:
            net.nm = old
        self.assertEqual((n[0]["switch"], n[0]["port"], n[0]["vlan"]), ("M4250", "Stage left", "20"))

    def test_device_edit_and_block(self):
        from tntshare import extras as X
        from tntshare.demo import fake_app
        from tntshare.keys import Key
        app = fake_app()
        app.status["mode"] = None
        dev = X.Devices(app)
        app.stack = [dev]
        dev.sel = dev.macs.index("00:05:a6:1c:22:10")
        app.dispatch(Key("4", "4"))                  # key 4 = Block
        self.assertTrue(app.cfg["devices"]["00:05:a6:1c:22:10"]["block"])
        X.edit_device(app, "00:60:74:aa:01:02", dict(ip="192.168.50.15"))
        form = app.stack[-1]
        form.form.select("down")
        form.key(Key("enter"))                     # Off -> 1 Mb/s
        form.form.select("__save")
        form.key(Key("enter"))
        d = app.cfg["devices"]["00:60:74:aa:01:02"]
        self.assertEqual((d["reserve"], d["ip"], d["down"]), (True, "192.168.50.15", "1 Mb/s"))

    def test_wizard(self):
        from tntshare import extras as X
        from tntshare.demo import fake_app
        from tntshare.keys import Key
        app = fake_app()
        app.status["mode"] = None
        app.cfg["setup_done"] = False
        w = X.Wizard(app)
        app.stack = [w]
        w.key(Key("enter"))                        # Wi-Fi to Ethernet
        self.assertEqual(w.step, "wifi")
        w.key(Key("enter"))                        # use Hotel Guest
        self.assertEqual(w.step, "gear")
        w.key(Key("down"))
        w.key(Key("enter"))                        # static IPs
        self.assertEqual(w.step, "addr")
        self.assertFalse(app.cfg["share_dhcp"])
        w.key(Key("esc"))                          # back to the gear question
        self.assertEqual(w.step, "gear")
        w.key(Key("enter"))                        # DHCP
        self.assertEqual(w.step, "done")
        w.key(Key("down"))
        w.key(Key("enter"))                        # finish, start later
        self.assertTrue(app.cfg["setup_done"])
        self.assertNotIn(w, app.stack)
        for s in app.stack:
            s.rows()
