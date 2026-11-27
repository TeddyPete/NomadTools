"""Getting reports off the device (TNT file transfer standard, same as
TNT Packet Capture):

* a small web page listing every saved report by site, reached by a QR code
  on the screen (download a file, or a whole site as a .zip), and
* copy everything to a USB stick (TNT-Net-Reports folder).

The web page only serves files under ~/TNT-Net-Reports and only runs while
it is switched on in the app.
"""
from __future__ import annotations

import html
import io
import os
import shutil
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import reports

PORT = 8080


def nice_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _safe(rel: str) -> str | None:
    full = os.path.realpath(os.path.join(reports.ROOT, rel))
    root = os.path.realpath(reports.ROOT)
    if full.startswith(root + os.sep) and os.path.isfile(full):
        return full
    return None


def _site_dir(site: str) -> str | None:
    full = os.path.realpath(os.path.join(reports.ROOT, os.path.basename(site)))
    return full if os.path.isdir(full) and full.startswith(os.path.realpath(reports.ROOT)) else None


class Handler(BaseHTTPRequestHandler):
    server_version = "TNTNetTools"

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(u.path)
        if path in ("/", "/index.html"):
            return self._index()
        if path == "/zip":
            site = urllib.parse.parse_qs(u.query).get("site", [""])[0]
            return self._zip(site)
        if path.startswith("/f/"):
            full = _safe(path[3:])
            if full:
                return self._file(full)
        self.send_error(404)

    def _send(self, data: bytes, ctype: str, name: str = "") -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if name:
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _file(self, full: str) -> None:
        name = os.path.basename(full)
        ctype = {"csv": "text/csv", "json": "application/json", "txt": "text/plain"}.get(
            name.rsplit(".", 1)[-1], "application/octet-stream")
        with open(full, "rb") as f:
            self._send(f.read(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""), name)

    def _zip(self, site: str) -> None:
        d = _site_dir(site)
        if not d:
            return self.send_error(404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(os.listdir(d)):
                p = os.path.join(d, f)
                if os.path.isfile(p):
                    z.write(p, f"{os.path.basename(d)}/{f}")
        self._send(buf.getvalue(), "application/zip", f"{os.path.basename(d)}.zip")

    def _index(self) -> None:
        blocks = []
        for site in reports.sites():
            rows = []
            for f in reports.files(site):
                p = os.path.join(reports.ROOT, site, f)
                if not os.path.isfile(p):
                    continue
                q = urllib.parse.quote(f"{site}/{f}")
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))
                rows.append(f"<tr><td><a href='/f/{q}' download>{html.escape(f)}</a>"
                            f"<div class=i>{when}</div></td><td class=r>{nice_size(os.path.getsize(p))}</td></tr>")
            zq = urllib.parse.quote(site)
            blocks.append(f"<h2>{html.escape(site.replace('_', ' '))} "
                          f"<a class=z href='/zip?site={zq}'>Download all (.zip)</a></h2>"
                          f"<table>{''.join(rows) or '<tr><td>No reports.</td></tr>'}</table>")
        body = "".join(blocks) or "<p>No reports yet. Press S on a result screen to save one.</p>"
        page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>TNT AV Net Tools reports</title><style>
body{{font:16px system-ui,sans-serif;margin:0;background:#0b0e14;color:#eee}}
h1{{background:#127834;margin:0;padding:12px 16px;font-size:20px}}
h2{{font-size:17px;margin:18px 16px 4px;display:flex;justify-content:space-between;align-items:center}}
table{{width:100%;border-collapse:collapse}}td{{padding:10px 16px;border-bottom:1px solid #223}}
a{{color:#8cf;word-break:break-all}}.i{{color:#99a;font-size:13px}}.r{{text-align:right;white-space:nowrap}}
a.z{{font-size:14px;font-weight:normal;background:#1e5ac8;color:#fff;padding:6px 10px;border-radius:6px;text-decoration:none}}
p{{padding:0 16px;color:#99a;font-size:13px}}</style>
<h1>TNT AV Net Tools reports</h1>{body}
<p>Tap a file to download it. CSV files open in Excel.<br>TheTechNomad.com · {html.escape(time.strftime('%Y-%m-%d %H:%M'))}</p>"""
        self._send(page.encode(), "text/html; charset=utf-8")


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
        os.makedirs(reports.ROOT, exist_ok=True)
        for port in (self.port, self.port + 1, self.port + 2, 8090):
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


# ---------------------------------------------------------------- USB stick

def usb_drives() -> list[str]:
    """Mounted removable drives (USB sticks) we can write to."""
    out = []
    try:
        lines = open("/proc/mounts").read().splitlines()
    except OSError:
        return []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mnt = parts[1].replace("\\040", " ")
        if parts[2] in ("vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "ext4", "ext3") and \
                (mnt.startswith("/media/") or mnt.startswith("/mnt/") or mnt.startswith("/run/media/")):
            if os.access(mnt, os.W_OK):
                out.append(mnt)
    return out


def copy_all(out, mnt: str = "") -> None:
    """Copy every report to <stick>/TNT-Net-Reports/<site>/, skipping files
    already there with the same size."""
    drives = [mnt] if mnt else usb_drives()
    if not drives:
        out.warn("No USB stick found. Plug one in and try again.")
        return
    mnt = drives[0]
    dst_root = os.path.join(mnt, "TNT-Net-Reports")
    todo, skipped = [], 0
    for site in reports.sites():
        for f in reports.files(site):
            src = os.path.join(reports.ROOT, site, f)
            dst = os.path.join(dst_root, site, f)
            if not os.path.isfile(src):
                continue
            if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                skipped += 1
            else:
                todo.append((src, dst))
    need = sum(os.path.getsize(s) for s, _ in todo)
    if shutil.disk_usage(mnt).free < need + 1_000_000:
        out.bad(f"Not enough space on the stick ({nice_size(need)} needed).")
        return
    out.dim(f"Copying to {mnt} ...")
    for i, (src, dst) in enumerate(todo, 1):
        if out.stopped:
            break
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        out.replace_last(f"{i}/{len(todo)} {os.path.basename(src)[:24]}", (140, 140, 150))
    os.sync()
    out.ok(f"Copied {len(todo)} file(s), {nice_size(need)}." + (f" {skipped} already there." if skipped else ""))
    out.ok(f"On the stick: TNT-Net-Reports/")
    out.dim("Safe to remove the stick now.")
