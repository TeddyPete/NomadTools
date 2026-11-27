"""Getting inventories off the device (Nomad file transfer standard):

* a small web page, reached by a QR code on the screen, with each job's
  Excel (.xlsx) and CSV file, a .zip with the label photos, and one Excel
  workbook with every job on its own sheet, and
* copy everything to a USB stick (Nomad-Label-Scans folder).

The page only serves files under ~/Nomad-Label-Scans and only runs while it
is switched on in the app.
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

from . import export, store

PORT = 8082
TYPES = {"csv": "text/csv; charset=utf-8", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "jpg": "image/jpeg", "json": "application/json"}


def nice_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _inside(path: str) -> bool:
    root = os.path.realpath(store.data_root())
    return os.path.realpath(path).startswith(root + os.sep)


class Handler(BaseHTTPRequestHandler):
    server_version = "NomadLabelScanner"

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = urllib.parse.unquote(u.path)
        job = q.get("job", [""])[0]
        if path in ("/", "/index.html"):
            return self._index()
        if path == "/all.xlsx":
            p = export.export_all()
            return self._file(p, "All-Jobs.xlsx")
        if job and job in store.jobs():
            name = store.safe_name(job)
            if path in ("/job.xlsx", "/job.csv"):
                paths = export.export_job(job)
                p = paths[1] if path.endswith("xlsx") else paths[0]
                return self._file(p, os.path.basename(p))
            if path == "/job.zip":
                return self._zip(job)
            if path == "/photo":
                p = store.photo_path(job, os.path.basename(q.get("f", [""])[0]))
                if os.path.isfile(p) and _inside(p):
                    return self._file(p, os.path.basename(p), inline=True)
        self.send_error(404)

    def _send(self, data: bytes, ctype: str, name: str = "", inline: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if name:
            disp = "inline" if inline else "attachment"
            self.send_header("Content-Disposition", f'{disp}; filename="{name}"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _file(self, full: str, name: str, inline: bool = False) -> None:
        with open(full, "rb") as f:
            self._send(f.read(), TYPES.get(name.rsplit(".", 1)[-1], "application/octet-stream"), name, inline)

    def _zip(self, job: str) -> None:
        export.export_job(job)
        d = store.job_dir(job)
        name = store.safe_name(job)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _, files in os.walk(d):
                for f in sorted(files):
                    if f.endswith(".tmp"):
                        continue
                    p = os.path.join(base, f)
                    z.write(p, os.path.join(name, os.path.relpath(p, d)))
        self._send(buf.getvalue(), "application/zip", f"{name}.zip")

    def _index(self) -> None:
        blocks = []
        for job in store.jobs():
            items = store.load(job)
            jq = urllib.parse.quote(job)
            rows = []
            for it in items:
                ph = (f"<a href='/photo?job={jq}&f={urllib.parse.quote(it.photo)}'>photo</a>" if it.photo else "")
                rows.append("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in
                                             (it.name or it.model, it.serial, it.mac, it.ip, it.room)) + f"<td>{ph}</td></tr>")
            table = ("<div class=t><table><tr><th>Device</th><th>Serial</th><th>MAC</th><th>IP</th><th>Room</th><th></th></tr>"
                     + "".join(rows) + "</table></div>") if rows else "<p>No items yet.</p>"
            blocks.append(f"<h2>{html.escape(job)} <span class=n>{len(items)} item(s)</span></h2>"
                          f"<div class=b><a href='/job.xlsx?job={jq}'>Excel</a><a href='/job.csv?job={jq}'>CSV</a>"
                          f"<a href='/job.zip?job={jq}'>All + photos (.zip)</a></div>{table}")
        body = "".join(blocks) or "<p>No jobs yet. Scan a label first.</p>"
        page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Nomad Label Scanner</title><style>
body{{font:16px system-ui,sans-serif;margin:0;background:#0b0e14;color:#eee}}
h1{{background:#127834;margin:0;padding:12px 16px;font-size:20px}}
h2{{font-size:17px;margin:20px 16px 6px}}.n{{color:#99a;font-weight:normal;font-size:14px}}
.b{{margin:0 16px 8px;display:flex;gap:8px;flex-wrap:wrap}}
.b a,a.all{{background:#1e5ac8;color:#fff;padding:7px 12px;border-radius:6px;text-decoration:none;font-size:15px}}
a.all{{display:inline-block;margin:14px 16px 0}}
.t{{overflow-x:auto;margin:0 8px}}table{{border-collapse:collapse;font-size:14px;width:100%}}
td,th{{padding:6px 8px;border-bottom:1px solid #223;text-align:left;white-space:nowrap}}th{{color:#99a}}
a{{color:#8cf}}p{{padding:0 16px;color:#99a;font-size:13px}}</style>
<h1>Nomad Label Scanner</h1><a class=all href='/all.xlsx'>Every job in one Excel file</a>{body}
<p>Excel files have one sheet per job. CSV opens in any spreadsheet.<br>TheTechNomad.com · {html.escape(time.strftime('%Y-%m-%d %H:%M'))}</p>"""
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
        os.makedirs(store.data_root(), exist_ok=True)
        for port in (self.port, self.port + 1, self.port + 2, 8092):
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
                mnt.startswith(("/media/", "/mnt/", "/run/media/")) and os.access(mnt, os.W_OK):
            out.append(mnt)
    return out


def copy_all(progress=None) -> str:
    """Export every job, then copy the whole scans folder to
    <stick>/Nomad-Label-Scans/. Returns a short result line."""
    drives = usb_drives()
    if not drives:
        raise RuntimeError("No USB stick found. Plug one in and try again.")
    mnt = drives[0]
    for job in store.jobs():
        export.export_job(job)
    export.export_all()
    root = store.data_root()
    dst_root = os.path.join(mnt, "Nomad-Label-Scans")
    todo = []
    for base, _, files in os.walk(root):
        for f in files:
            if f.endswith(".tmp"):
                continue
            src = os.path.join(base, f)
            dst = os.path.join(dst_root, os.path.relpath(src, root))
            if not (os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src)
                    and not f.endswith((".csv", ".xlsx", ".json"))):
                todo.append((src, dst))
    need = sum(os.path.getsize(s) for s, _ in todo)
    if shutil.disk_usage(mnt).free < need + 1_000_000:
        raise RuntimeError(f"Not enough space on the stick ({nice_size(need)} needed).")
    for i, (src, dst) in enumerate(todo, 1):
        if progress:
            progress(f"{i}/{len(todo)} {os.path.basename(src)[:24]}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    os.sync()
    return f"Copied {len(todo)} file(s), {nice_size(need)} to Nomad-Label-Scans/ on the stick. Safe to remove it now."
