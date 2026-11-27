"""A small web page that lists every capture (including one still
recording) for download, and lets you delete old ones, so you can pull a
.pcap onto a phone or laptop and open it in Wireshark.

It only touches files in the captures folder and only runs while you have
it switched on in the app (it stops when the app quits). The app shows its
address as a QR code.
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


def _safe(name: str) -> str | None:
    name = os.path.basename(name)
    if name and (name.endswith(".pcap") or name.endswith(".pcap.json")) and \
            os.path.isfile(os.path.join(C.ROOT, name)):
        return os.path.join(C.ROOT, name)
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "NomadPacketCapture"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._index()
        full = _safe(path.lstrip("/")) if "/" not in path.lstrip("/") else None
        if full:
            return self._file(full, os.path.basename(full))
        self.send_error(404)

    def do_POST(self):
        """POST /delete with name=<file> (repeatable) or all=1."""
        if urllib.parse.urlparse(self.path).path != "/delete":
            return self.send_error(404)
        n = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(min(n, 100_000)).decode(errors="replace"))
        live = set((C.running() or {}).get("files") or [])
        saved = {s.name: s for s in F.listing()}
        names = list(saved) if form.get("all") else form.get("name", [])
        for name in names:
            s = saved.get(os.path.basename(name))
            if s and s.path not in live:
                F.delete(s)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def _index(self):
        rows = []
        for s in F.listing(include_live=True):
            m = s.meta
            secs = m.get("seconds")
            info = " · ".join(x for x in (m.get("preset"), "inline tap" if m.get("tap") else m.get("iface"),
                                          f"{secs:.0f} s" if secs else "",
                                          f"{m['packets']:,} pkts" if m.get("packets") is not None else "") if x)
            q = urllib.parse.quote(s.name)
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(m.get("started") or s.mtime))
            if m.get("recording"):
                act = "<span class=rec>● recording</span>"
            else:
                act = (f"<button name=name value='{html.escape(s.name, quote=True)}' "
                       f"onclick=\"return confirm('Delete {html.escape(s.name, quote=True)}?')\">Delete</button>")
            rows.append(f"<tr><td><a href='/{q}' download>{html.escape(s.name)}</a>"
                        f"<div class=i>{when} · {html.escape(info)}</div></td>"
                        f"<td class=r>{F.nice_size(s.size)}</td><td class=r>{act}</td></tr>")
        body = "".join(rows) or "<tr><td colspan=3>No captures yet.</td></tr>"
        free = C.free_mb() / 1000
        page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Nomad Packet Capture</title><style>
body{{font:16px system-ui,sans-serif;margin:0;background:#0b0e14;color:#eee}}
h1{{background:#127834;margin:0;padding:12px 16px;font-size:20px}}
table{{width:100%;border-collapse:collapse}}td{{padding:10px 12px;border-bottom:1px solid #223;vertical-align:middle}}
a{{color:#8cf;word-break:break-all}}.i{{color:#99a;font-size:13px}}.r{{text-align:right;white-space:nowrap}}
button{{background:#3a1c1c;color:#f99;border:1px solid #844;border-radius:6px;padding:6px 10px;font-size:14px}}
.rec{{color:#f66;font-size:14px}}p{{padding:0 16px;color:#99a;font-size:13px}}
.bar{{display:flex;justify-content:space-between;align-items:center;padding:8px 16px;color:#99a;font-size:14px}}</style>
<h1>Nomad Packet Capture</h1>
<form method=post action=/delete>
<div class=bar><span>{len(rows)} files · {free:.1f} GB free</span>
<button name=all value=1 onclick="return confirm('Delete ALL saved captures? This can\\'t be undone.')">Delete all</button></div>
<table>{body}</table></form>
<p>Tap a file name to download it, then open it in Wireshark. A file that is still recording downloads as it is so far.
<br>TheTechNomad.com · {html.escape(time.strftime('%Y-%m-%d %H:%M'))}</p>"""
        data = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, full, name):
        size = os.path.getsize(full)   # a recording file: send what's there now
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.tcpdump.pcap" if name.endswith(".pcap")
                         else "application/json")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        left = size
        with open(full, "rb") as f:
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                left -= len(chunk)
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
