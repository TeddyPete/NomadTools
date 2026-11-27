"""Getting a WireGuard config onto the device without typing it.

1. Web page: the app shows a QR code; open it on a phone or laptop on the
   same network, pick the .conf file (or paste it) and send. The page only
   runs while that screen is open, and the address has a random token.
2. USB stick: any *.conf with [Interface] and [Peer] on a mounted stick.
"""
from __future__ import annotations

import glob
import html
import os
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import net

PORT = 8090

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nomad WiFi Share - WireGuard</title>
<style>body{{font-family:sans-serif;max-width:640px;margin:1em auto;padding:0 1em;background:#0b0e14;color:#eee}}
h1{{color:#5c5;font-size:1.3em}}textarea{{width:100%;height:14em;font-family:monospace}}
button{{font-size:1.1em;padding:.5em 1.2em;background:#1e5ac8;color:#fff;border:0;border-radius:6px}}
.msg{{padding:.6em;border-radius:6px;background:#203020}}.bad{{background:#402020}}</style></head><body>
<h1>Nomad WiFi Share: WireGuard VPN</h1>{msg}
<p>Pick your WireGuard <b>.conf</b> file or paste it below, then press Send.
It is stored on the CardputerZero only (readable by its user only).</p>
<form method="post"><input type="file" accept=".conf,text/plain" id="f"><br><br>
<textarea name="conf" id="t" placeholder="[Interface]&#10;PrivateKey = ...&#10;Address = ...&#10;&#10;[Peer]&#10;PublicKey = ...&#10;Endpoint = ...&#10;AllowedIPs = 0.0.0.0/0"></textarea><br><br>
<button>Send</button></form>
<script>document.getElementById('f').onchange=e=>{{const r=new FileReader();r.onload=()=>{{document.getElementById('t').value=r.result}};r.readAsText(e.target.files[0])}}</script>
<p style="color:#888">TheTechNomad.com</p></body></html>"""


class Upload:
    def __init__(self):
        self.token = secrets.token_urlsafe(6)
        self.srv: ThreadingHTTPServer | None = None
        self.port = PORT
        self.received = ""      # message for the LCD once a config arrived
        self.error = ""

    def start(self) -> bool:
        up = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _ok_path(self):
                return urllib.parse.urlparse(self.path).path.rstrip("/") == "/" + up.token

            def _page(self, msg="", bad=False):
                m = f'<p class="msg{" bad" if bad else ""}">{html.escape(msg)}</p>' if msg else ""
                data = PAGE.format(msg=m).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if not self._ok_path():
                    return self.send_error(404)
                self._page()

            def do_POST(self):
                if not self._ok_path():
                    return self.send_error(404)
                n = min(int(self.headers.get("Content-Length") or 0), 20000)
                form = urllib.parse.parse_qs(self.rfile.read(n).decode(errors="replace"))
                text = (form.get("conf") or [""])[0]
                try:
                    net.wg_save(text)
                except net.NetError as e:
                    return self._page(str(e), bad=True)
                up.received = "WireGuard config received"
                self._page("Saved. Turn the VPN on from the CardputerZero.")

        for port in (PORT, PORT + 1, PORT + 2):
            try:
                self.srv = ThreadingHTTPServer(("0.0.0.0", port), H)
                self.port = port
                break
            except OSError as e:
                self.error = str(e)
        if not self.srv:
            return False
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return True

    def url(self, ip: str) -> str:
        return f"http://{ip}:{self.port}/{self.token}"

    def stop(self) -> None:
        if self.srv:
            srv, self.srv = self.srv, None
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()


def usb_configs() -> list[str]:
    """WireGuard configs on mounted USB sticks."""
    out = []
    for pat in ("/media/*/*/*.conf", "/media/*/*.conf", "/run/media/*/*/*.conf", "/mnt/*/*.conf"):
        for p in sorted(glob.glob(pat)):
            try:
                if os.path.getsize(p) < 8000 and net.wg_parse(open(p, errors="replace").read()) is None:
                    out.append(p)
            except OSError:
                continue
    return out[:20]
