"""A small read-only web page that lists the saved captures for download,
so you can pull a .pcap onto a laptop and open it in Wireshark.

It only serves files from the captures folder and only while you have it
switched on in the app (it stops when the app quits).
"""
from __future__ import annotations

import html
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import capture as C
from . import files as F

PORT = 8080


class Handler(BaseHTTPRequestHandler):
    server_version = "TNTPacketCapture"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._index()
        name = os.path.basename(path)
        full = os.path.join(C.ROOT, name)
        if name and "/" not in name and (name.endswith(".pcap") or name.endswith(".pcap.json")) \
                and os.path.isfile(full):
            return self._file(full, name)
        self.send_error(404)

    def _index(self):
        rows = []
        for s in F.listing():
            m = s.meta
            secs = m.get("seconds")
            info = " · ".join(x for x in (m.get("preset"), m.get("iface"),
                                          f"{secs:.0f} s" if secs else "",
                                          f"{m['packets']} pkts" if m.get("packets") is not None else "") if x)
            q = urllib.parse.quote(s.name)
            rows.append(f"<tr><td><a href='/{q}' download>{html.escape(s.name)}</a><div class=i>"
                        f"{html.escape(info)}</div></td><td class=r>{F.nice_size(s.size)}</td></tr>")
        body = "".join(rows) or "<tr><td colspan=2>No captures yet.</td></tr>"
        page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>TNT Packet Capture</title><style>
body{{font:16px system-ui,sans-serif;margin:0;background:#0b0e14;color:#eee}}
h1{{background:#127834;margin:0;padding:12px 16px;font-size:20px}}
table{{width:100%;border-collapse:collapse}}td{{padding:10px 16px;border-bottom:1px solid #223}}
a{{color:#8cf;word-break:break-all}}.i{{color:#99a;font-size:13px}}.r{{text-align:right;white-space:nowrap}}
p{{padding:0 16px;color:#99a;font-size:13px}}</style>
<h1>TNT Packet Capture</h1><table>{body}</table>
<p>Open the .pcap files in Wireshark. TheTechNomad.com · {html.escape(time.strftime('%Y-%m-%d %H:%M'))}</p>"""
        data = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, full, name):
        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.tcpdump.pcap" if name.endswith(".pcap")
                         else "application/json")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        with open(full, "rb") as f:
            while True:
                chunk = f.read(256 * 1024)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return


class Share:
    def __init__(self, port: int = PORT):
        self.port = port
        self.srv: ThreadingHTTPServer | None = None
        self.error = ""

    @property
    def on(self) -> bool:
        return self.srv is not None

    def start(self) -> bool:
        if self.srv:
            return True
        for port in (self.port, self.port + 1, self.port + 2):
            try:
                self.srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
                self.port = port
                break
            except OSError as e:
                self.error = str(e)
        if not self.srv:
            return False
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return True

    def stop(self) -> None:
        if self.srv:
            srv, self.srv = self.srv, None
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()
