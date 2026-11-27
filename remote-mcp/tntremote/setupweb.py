"""One-time setup page on the local network, for pasting the ngrok authtoken.

The token is about 50 characters, too long to type on the small keyboard, so
the ngrok setup screen shows a QR code (and short text) for
http://<device ip>:<port>/<key>, e.g. 192.168.1.10:8776/k7q2. The phone (on the
same Wi-Fi or LAN) opens it, pastes the token and saves.

  * Runs inside the LCD app only while that screen is open, then stops.
  * The random 4-character key in the path is shown only on the device screen
    (about a million choices); any other path gets 404, and 20 wrong requests
    shut the page down, so guessing it is hopeless.
  * It never shows the saved token back.
"""
from __future__ import annotations

import html
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import brand, config as C

PORT = brand.SETUP_PORT
KEY_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i: easy to read and type

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{app} setup</title><style>
body{{margin:0;font-family:system-ui,sans-serif;background:#0b0e14;color:#eee}}
header{{background:#127834;padding:14px 18px;font-size:20px;font-weight:700}}
main{{padding:18px;max-width:480px;margin:auto}} a{{color:#8fc1ff}}
textarea{{font-size:16px;width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:2px solid #1e5ac8;background:#141a26;color:#fff}}
button{{margin-top:14px;width:100%;padding:14px;font-size:18px;font-weight:700;border:0;border-radius:8px;background:#1e5ac8;color:#fff}}
.err{{background:#5a0808;padding:10px;border-radius:6px}} .ok{{background:#0f4d22;padding:10px;border-radius:6px}}
small{{color:#8899aa}}</style></head>
<body><header>{app} &middot; ngrok setup</header><main>{body}</main></body></html>"""

FORM = """<p>1. Open <a href="https://dashboard.ngrok.com/get-started/your-authtoken" target="_blank" rel="noopener">your ngrok authtoken page</a>
(sign in or sign up free first) and tap <b>Copy</b>.</p>
<p>2. Paste it here and tap Save. ngrok lists 4 steps; only <b>Add your authtoken</b> matters.
Pasting the whole <code>ngrok config add-authtoken ...</code> line is fine.</p>{msg}
<form method="post" autocomplete="off"><textarea name="token" rows="3" placeholder="paste authtoken" autocapitalize="off" spellcheck="false"></textarea>
<button type="submit">Save</button></form>
<p><small>The token stays on the CardputerZero (only the pi user can read it).</small></p>"""


class SetupWeb:
    def __init__(self, on_saved=None):
        self.key = "".join(secrets.choice(KEY_CHARS) for _ in range(4))
        self.on_saved = on_saved
        self.saved = False
        self.bad = 0
        self.httpd: ThreadingHTTPServer | None = None
        self.error = ""

    def url(self, ip: str) -> str:
        return f"http://{self.short(ip)}"

    def short(self, host: str) -> str:
        """What to type in the phone's browser (it adds http:// itself)."""
        return f"{host}:{PORT}/{self.key}"

    def start(self) -> bool:
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code: int, body: str):
                data = PAGE.format(app=html.escape(brand.APP_NAME), body=body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
                self.end_headers()
                self.wfile.write(data)

            def allowed(self) -> bool:
                # forgiving: phones capitalise the first letter or add a slash
                if self.path.split("?")[0].strip("/").lower() == owner.key:
                    return True
                owner.bad += 1
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                if owner.bad >= 20:
                    threading.Thread(target=owner.stop, daemon=True).start()
                return False

            def do_GET(self):
                if self.allowed():
                    self.reply(200, '<p class="ok">Saved. Look at the device screen.</p>' if owner.saved else FORM.format(msg=""))

            def do_POST(self):
                if not self.allowed():
                    return
                n = min(int(self.headers.get("Content-Length") or 0), 4096)
                tok = (parse_qs(self.rfile.read(n).decode(errors="replace")).get("token") or [""])[0].strip()
                try:
                    C.set_ngrok_token(tok)
                except ValueError as e:
                    return self.reply(400, FORM.format(msg=f'<p class="err">{html.escape(str(e))}</p>'))
                owner.saved = True
                if owner.on_saved:
                    owner.on_saved()
                self.reply(200, '<p class="ok">Saved! Look at the CardputerZero screen: it shows your connector '
                                'address in a moment. You can close this page.</p>')

        try:
            self.httpd = ThreadingHTTPServer(("0.0.0.0", PORT), H)
        except OSError as e:
            self.error = str(e)
            return False
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True).start()
        return True

    def stop(self) -> None:
        h, self.httpd = self.httpd, None
        if h:
            h.shutdown()
            h.server_close()
