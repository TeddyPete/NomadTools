"""Recordings: list, delete, copy to a USB stick, and a small web page to
download them (Nomad file-transfer standard: QR code on screen + USB copy)."""
from __future__ import annotations

import html
import os
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .audio import REC_DIR

USB_FOLDER = "Nomad-SDR"
PORT = 8090


def nice_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def listing() -> list[dict]:
    out = []
    try:
        names = os.listdir(REC_DIR)
    except OSError:
        return []
    for n in names:
        if n.endswith(".wav") or n.endswith(".wav.part"):
            p = os.path.join(REC_DIR, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append({"name": n, "path": p, "size": st.st_size, "mtime": st.st_mtime,
                        "live": n.endswith(".part"), "seconds": max(0, st.st_size - 44) / 64000})
    out.sort(key=lambda d: d["mtime"], reverse=True)
    return out


def label(d: dict) -> str:
    """'11-28 10:35  146.5200 NFM' from the file name."""
    parts = d["name"].replace(".wav.part", "").replace(".wav", "").split("_")
    try:
        day, hms, mhz, mode = parts[0], parts[1], parts[2], parts[3]
        return f"{day[5:]} {hms[:2]}:{hms[2:4]}  {mhz.replace('MHz', '')} {mode}"
    except IndexError:
        return d["name"]


def delete(d: dict) -> None:
    if not d.get("live"):
        try:
            os.remove(d["path"])
        except OSError:
            pass


def usb_drives() -> list[str]:
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


def copy_all(mnt: str) -> tuple[int, int]:
    """Copy recordings not already on the stick. Returns (copied, skipped)."""
    d = os.path.join(mnt, USB_FOLDER)
    os.makedirs(d, exist_ok=True)
    todo, skipped = [], 0
    for r in listing():
        if r["live"]:
            continue
        dst = os.path.join(d, r["name"])
        if os.path.exists(dst) and os.path.getsize(dst) == r["size"]:
            skipped += 1
        else:
            todo.append((r, dst))
    need = sum(r["size"] for r, _ in todo)
    if shutil.disk_usage(mnt).free < need + 1_000_000:
        raise RuntimeError(f"Not enough space on the USB stick ({nice_size(need)} needed)")
    for r, dst in todo:
        shutil.copyfile(r["path"], dst)
    os.sync()
    return len(todo), skipped


def free_mb() -> float:
    try:
        os.makedirs(REC_DIR, exist_ok=True)
        return shutil.disk_usage(REC_DIR).free / 1e6
    except OSError:
        return 0.0


def _safe(name: str) -> str | None:
    name = os.path.basename(name)
    if name == "aprs.log":
        p = os.path.join(os.path.dirname(REC_DIR), name)
        return p if os.path.isfile(p) else None
    p = os.path.join(REC_DIR, name)
    if name.endswith((".wav", ".wav.part", ".log")) and os.path.isfile(p):
        return p
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "NomadSDR"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path).lstrip("/")
        if path in ("", "index.html"):
            return self._index()
        full = _safe(path) if "/" not in path else None
        if full:
            return self._file(full)
        self.send_error(404)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/delete":
            return self.send_error(404)
        n = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(min(n, 100_000)).decode(errors="replace"))
        saved = {r["name"]: r for r in listing()}
        names = list(saved) if form.get("all") else form.get("name", [])
        for name in names:
            r = saved.get(os.path.basename(name))
            if r:
                delete(r)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def _index(self):
        rows = []
        for r in listing():
            q = urllib.parse.quote(r["name"])
            act = "<span class=rec>● recording</span>" if r["live"] else (
                f"<button name=name value='{html.escape(r['name'], quote=True)}' "
                f"onclick=\"return confirm('Delete this recording?')\">Delete</button>")
            rows.append(f"<tr><td><a href='/{q}' download>{html.escape(label(r))}</a>"
                        f"<div class=i>{r['seconds']:.0f} s · {html.escape(r['name'])}</div>"
                        f"<audio controls preload=none src='/{q}'></audio></td>"
                        f"<td class=r>{nice_size(r['size'])}</td><td class=r>{act}</td></tr>")
        body = "".join(rows) or "<tr><td colspan=3>No recordings yet.</td></tr>"
        page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Nomad SDR recordings</title><style>
body{{font:16px system-ui,sans-serif;margin:0;background:#0b0e14;color:#eee}}
h1{{background:#127834;margin:0;padding:12px 16px;font-size:20px}}
table{{width:100%;border-collapse:collapse}}td{{padding:10px 12px;border-bottom:1px solid #223;vertical-align:middle}}
a{{color:#8cf}}.i{{color:#99a;font-size:13px;word-break:break-all}}.r{{text-align:right;white-space:nowrap}}
audio{{width:100%;margin-top:6px;height:32px}}
button{{background:#3a1c1c;color:#f99;border:1px solid #844;border-radius:6px;padding:6px 10px;font-size:14px}}
.rec{{color:#f66;font-size:14px}}p{{padding:0 16px;color:#99a;font-size:13px}}
.bar{{display:flex;justify-content:space-between;align-items:center;padding:8px 16px;color:#99a;font-size:14px}}</style>
<h1>Nomad SDR recordings</h1>
<form method=post action=/delete>
<div class=bar><span>{len(rows)} files · {free_mb() / 1000:.1f} GB free · <a href="/aprs.log">APRS log</a></span>
<button name=all value=1 onclick="return confirm('Delete ALL recordings? This can\\'t be undone.')">Delete all</button></div>
<table>{body}</table></form>
<p>Tap a name to download the WAV file. TheTechNomad.com</p>"""
        data = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, full):
        size = os.path.getsize(full)
        name = os.path.basename(full).replace(".part", "")
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav" if ".wav" in name else "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'inline; filename="{name}"')
        self.end_headers()
        with open(full, "rb") as f:
            left = size
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
        self.srv = None
        self.error = ""

    @property
    def on(self) -> bool:
        return self.srv is not None

    def start(self) -> bool:
        if self.srv:
            return True
        os.makedirs(REC_DIR, exist_ok=True)
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


def my_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()
