"""The tools Claude can call on the CardputerZero.

Everything runs as the pi user (never root). Output is capped so a chatty
command can't flood the phone app or use up the Pi's memory.
"""
from __future__ import annotations

import base64
import os
import shutil
import signal
import socket
import stat
import subprocess
import threading
import time
from collections import deque

from . import config as C

MAX_OUT = 60_000          # characters returned per call
MAX_READ = 2_000_000      # bytes read from a file per call
MAX_WRITE = 5_000_000


class ToolError(Exception):
    pass


PROTECTED = (C.CONF_DIR, C.STATE_DIR, C.RUN_DIR)


def _wpath(p: str, cfg: dict) -> str:
    """A path Claude may change: not TNT Remote's own settings, tokens or log."""
    norm = _path(p, cfg)
    for full in {norm, os.path.realpath(norm)}:
        for d in PROTECTED:
            d = os.path.realpath(d)
            if full == d or full.startswith(d + os.sep):
                raise ToolError("TNT Remote's own settings, sign-ins and log can only be changed on the device")
    return norm


def _path(p: str, cfg: dict) -> str:
    if not p:
        raise ToolError("path is required")
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(cfg.get("default_cwd") or C.HOME, p)
    return os.path.normpath(p)


def _cap(s: str, n: int = MAX_OUT) -> str:
    if len(s) <= n:
        return s
    half = n // 2
    return s[:half] + f"\n\n... [{len(s) - n} characters cut] ...\n\n" + s[-half:]


def _env() -> dict:
    env = dict(os.environ)
    env.setdefault("HOME", C.HOME)
    env["PATH"] = env.get("PATH", "/usr/bin:/bin") + ":/usr/sbin:/sbin:" + os.path.join(C.HOME, ".local/bin")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("TERM", "dumb")
    env.pop("TUNNEL_TOKEN", None)
    return env


# ---- device ---------------------------------------------------------------------

def _read(p: str) -> str:
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return ""


def _ips() -> list[str]:
    try:
        out = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    res = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) > 3 and parts[1] != "lo":
            res.append(f"{parts[1]} {parts[3]}")
    return res


def device_status(args: dict, cfg: dict, ctx) -> str:
    up = float((_read("/proc/uptime") or "0").split()[0])
    mem = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0]) // 1024 if v.split() else 0
    du = shutil.disk_usage("/")
    temp = _read("/sys/class/thermal/thermal_zone0/temp")
    st = C.read_json(C.STATUS_FILE) or {}
    lines = [
        f"Host: {socket.gethostname()}  user: {os.environ.get('USER') or os.getuid()}",
        f"Uptime: {int(up // 86400)}d {int(up % 86400 // 3600)}h {int(up % 3600 // 60)}m   load: {_read('/proc/loadavg')}",
        f"Memory: {mem.get('MemAvailable', 0)} MB free of {mem.get('MemTotal', 0)} MB, swap free {mem.get('SwapFree', 0)} MB",
        f"Disk /: {du.free // 2**20} MB free of {du.total // 2**20} MB",
        f"CPU temp: {int(temp) / 1000:.1f} C" if temp.isdigit() else "CPU temp: ?",
        "IP: " + ("; ".join(_ips()) or "none"),
        f"Tunnel: {st.get('tunnel', '?')}   public URL: {cfg.get('public_url') or '(not set)'}",
        f"Permissions: commands {'on' if cfg['allow_commands'] else 'OFF'}, sudo {'ON' if cfg.get('allow_sudo') else 'off'}, file writes {'on' if cfg['allow_writes'] else 'OFF'}, net tools {'on' if cfg['allow_net_tools'] else 'OFF'}",
        "Installed TNT apps: " + ", ".join(sorted(os.listdir("/usr/share/APPLaunch/lib")) if os.path.isdir("/usr/share/APPLaunch/lib") else []),
    ]
    return "\n".join(lines)


# ---- commands ---------------------------------------------------------------------

def _need(cfg: dict, key: str, what: str) -> None:
    if not cfg.get(key):
        raise ToolError(f"{what} is switched off on the device (TNT Remote > Permissions).")


ROOTRUN = "/usr/lib/tnt-remote/rootrun"


def _argv(cmd: str, args: dict, cfg: dict) -> list[str]:
    """bash -lc cmd, or as root through the sudo helper when asked and allowed."""
    if args.get("sudo"):
        if not cfg.get("allow_sudo"):
            raise ToolError("Admin (sudo) is switched off. Ask Ted to turn on TNT Remote > Permissions > Admin (sudo) on the device.")
        if not os.access(ROOTRUN, os.X_OK):
            raise ToolError("the sudo helper is missing; reinstall the tnt-remote package")
        return ["sudo", "-n", ROOTRUN, cmd]
    return ["/bin/bash", "-lc", cmd]


def run_command(args: dict, cfg: dict, ctx) -> str:
    _need(cfg, "allow_commands", "Running commands")
    cmd = str(args.get("command") or "")
    if not cmd.strip():
        raise ToolError("command is required")
    argv = _argv(cmd, args, cfg)
    cwd = _path(args.get("cwd") or cfg.get("default_cwd") or C.HOME, cfg)
    timeout = max(1, min(int(args.get("timeout_s") or 120), 900))
    ctx.note(("# " if args.get("sudo") else "$ ") + cmd[:60])
    t0 = time.monotonic()
    try:
        p = subprocess.Popen(argv, cwd=cwd, env=_env(), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError as e:
        raise ToolError(f"could not start: {e}")
    try:
        out, err = p.communicate(input=(args.get("stdin") or "").encode(), timeout=timeout)
        code = p.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            out, err = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            out, err = p.communicate()
        code, timed_out = p.returncode, True
    dt = time.monotonic() - t0
    o, e = out.decode(errors="replace"), err.decode(errors="replace")
    head = f"exit code {code}" + (f" (stopped after {timeout}s timeout; use start_background for long jobs)" if timed_out else "") + f", {dt:.1f}s"
    parts = [head]
    if o:
        parts.append("--- stdout ---\n" + _cap(o))
    if e:
        parts.append("--- stderr ---\n" + _cap(e, MAX_OUT // 3))
    return "\n".join(parts)


class Job:
    def __init__(self, jid: int, cmd: str, cwd: str, argv: list[str]):
        self.id, self.cmd, self.cwd = jid, cmd, cwd
        self.buf: deque[str] = deque(maxlen=4000)
        self.started = time.time()
        self.p = subprocess.Popen(argv, cwd=cwd, env=_env(), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        self.total = 0
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for raw in iter(self.p.stdout.readline, b""):
            self.buf.append(raw.decode(errors="replace").rstrip("\n"))
            self.total += 1
        self.p.stdout.close()

    @property
    def state(self) -> str:
        rc = self.p.poll()
        return "running" if rc is None else f"exited {rc}"


JOBS: dict[int, Job] = {}
_next = [1]


def start_background(args: dict, cfg: dict, ctx) -> str:
    _need(cfg, "allow_commands", "Running commands")
    cmd = str(args.get("command") or "")
    if not cmd.strip():
        raise ToolError("command is required")
    running = [j for j in JOBS.values() if j.p.poll() is None]
    if len(running) >= 6:
        raise ToolError("6 background jobs are already running; stop one first")
    for jid in [j.id for j in JOBS.values() if j.p.poll() is not None][:-10]:
        JOBS.pop(jid, None)
    cwd = _path(args.get("cwd") or cfg.get("default_cwd") or C.HOME, cfg)
    j = Job(_next[0], cmd, cwd, _argv(cmd, args, cfg))
    _next[0] += 1
    JOBS[j.id] = j
    ctx.note(f"bg {j.id}: {cmd[:50]}")
    time.sleep(min(float(args.get("wait_s") or 1), 20))
    return f"job {j.id} started (pid {j.p.pid}), {j.state}\n" + _cap("\n".join(j.buf))


def read_background(args: dict, cfg: dict, ctx) -> str:
    j = JOBS.get(int(args.get("job_id") or 0))
    if not j:
        raise ToolError("no such job; see list_background")
    n = max(1, min(int(args.get("tail_lines") or 100), 4000))
    lines = list(j.buf)[-n:]
    return f"job {j.id} {j.state}, {j.total} lines so far: {j.cmd}\n" + _cap("\n".join(lines))


def stop_background(args: dict, cfg: dict, ctx) -> str:
    j = JOBS.get(int(args.get("job_id") or 0))
    if not j:
        raise ToolError("no such job")
    if j.p.poll() is None:
        os.killpg(j.p.pid, signal.SIGTERM)
        try:
            j.p.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(j.p.pid, signal.SIGKILL)
    return f"job {j.id} {j.state}\n" + _cap("\n".join(list(j.buf)[-40:]))


def list_background(args: dict, cfg: dict, ctx) -> str:
    if not JOBS:
        return "no background jobs"
    return "\n".join(f"{j.id}: {j.state}, started {time.strftime('%H:%M:%S', time.localtime(j.started))}: {j.cmd[:100]}"
                     for j in JOBS.values())


def stop_all_jobs() -> None:
    for j in JOBS.values():
        if j.p.poll() is None:
            try:
                os.killpg(j.p.pid, signal.SIGTERM)
            except OSError:
                pass


# ---- files ----------------------------------------------------------------------

def read_file(args: dict, cfg: dict, ctx) -> str | dict:
    p = _path(args.get("path"), cfg)
    if not os.path.isfile(p):
        raise ToolError(f"not a file: {p}")
    size = os.path.getsize(p)
    if args.get("base64"):
        off = int(args.get("offset_bytes") or 0)
        with open(p, "rb") as f:
            f.seek(off)
            data = f.read(MAX_READ)
        return f"{p}: {size} bytes, returning {len(data)} from offset {off} as base64\n" + base64.b64encode(data).decode()
    start = max(1, int(args.get("start_line") or 1))
    count = max(1, min(int(args.get("max_lines") or 2000), 20000))
    out, n = [], 0
    with open(p, "rb") as f:
        for n, raw in enumerate(f, 1):
            if n < start:
                continue
            if n >= start + count:
                break
            out.append(raw.decode(errors="replace").rstrip("\n"))
    text = "\n".join(out)
    if b"\x00" in text.encode()[:4096]:
        return f"{p} looks binary ({size} bytes); call read_file with base64=true"
    more = "" if n < start + count else f"  (more lines after {start + count - 1}; use start_line)"
    return f"{p} ({size} bytes) lines {start}-{start + len(out) - 1}{more}\n" + _cap(text, MAX_OUT * 2)


def write_file(args: dict, cfg: dict, ctx) -> str:
    _need(cfg, "allow_writes", "Writing files")
    p = _wpath(args.get("path"), cfg)
    content = args.get("content")
    if content is None:
        raise ToolError("content is required")
    data = base64.b64decode(content) if args.get("base64") else str(content).encode()
    if len(data) > MAX_WRITE:
        raise ToolError("too big (5 MB max per call); use append in parts")
    os.makedirs(os.path.dirname(p) or "/", exist_ok=True)
    mode = "ab" if args.get("append") else "wb"
    if mode == "wb":
        tmp = p + ".tnt-tmp"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(p):
            shutil.copymode(p, tmp)
        os.replace(tmp, p)
    else:
        with open(p, "ab") as f:
            f.write(data)
    if args.get("executable"):
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    ctx.note(f"wrote {os.path.basename(p)}")
    return f"{'appended' if mode == 'ab' else 'wrote'} {len(data)} bytes to {p}"


def edit_file(args: dict, cfg: dict, ctx) -> str:
    _need(cfg, "allow_writes", "Writing files")
    p = _wpath(args.get("path"), cfg)
    old, new = args.get("old_text"), args.get("new_text")
    if old is None or new is None:
        raise ToolError("old_text and new_text are required")
    with open(p, encoding="utf-8", errors="surrogateescape") as f:
        text = f.read()
    n = text.count(old)
    if n == 0:
        raise ToolError("old_text not found in the file")
    if n > 1 and not args.get("replace_all"):
        raise ToolError(f"old_text appears {n} times; add more context or set replace_all")
    text = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
    return write_file({"path": p, "content": text}, cfg, ctx).replace("wrote", f"edited ({n if args.get('replace_all') else 1} change),", 1)


def list_dir(args: dict, cfg: dict, ctx) -> str:
    p = _path(args.get("path") or cfg.get("default_cwd") or C.HOME, cfg)
    if not os.path.isdir(p):
        raise ToolError(f"not a folder: {p}")
    depth = max(0, min(int(args.get("depth") or 0), 4))
    hidden = bool(args.get("show_hidden"))
    out: list[str] = []

    def walk(d: str, level: int) -> None:
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            out.append("  " * level + f"[{e.strerror}]")
            return
        for nm in names:
            if len(out) >= 1500:
                return
            if nm.startswith(".") and not hidden:
                continue
            full = os.path.join(d, nm)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode):
                out.append("  " * level + nm + "/")
                if level < depth:
                    walk(full, level + 1)
            elif stat.S_ISLNK(st.st_mode):
                out.append("  " * level + f"{nm} -> {os.readlink(full)}")
            else:
                out.append("  " * level + f"{nm}  ({st.st_size} B, {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))})")

    walk(p, 0)
    if len(out) >= 1500:
        out.append("... (list cut at 1500 entries)")
    return p + "\n" + ("\n".join(out) or "(empty)")


def move_path(args: dict, cfg: dict, ctx) -> str:
    _need(cfg, "allow_writes", "Writing files")
    src, dst = _wpath(args.get("source"), cfg), _wpath(args.get("destination"), cfg)
    if not os.path.lexists(src):
        raise ToolError(f"not found: {src}")
    if args.get("copy"):
        if os.path.isdir(src):
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
        return f"copied {src} -> {dst}"
    shutil.move(src, dst)
    return f"moved {src} -> {dst}"


def delete_path(args: dict, cfg: dict, ctx) -> str:
    _need(cfg, "allow_writes", "Writing files")
    p = _wpath(args.get("path"), cfg)
    if p in ("/", C.HOME, "/home", "/usr", "/etc"):
        raise ToolError("refusing to delete that")
    if os.path.isdir(p) and not os.path.islink(p):
        if not args.get("recursive"):
            raise ToolError("that is a folder; set recursive=true to delete it and everything inside")
        shutil.rmtree(p)
    else:
        os.unlink(p)
    ctx.note(f"deleted {os.path.basename(p)}")
    return f"deleted {p}"


# ---- screen ----------------------------------------------------------------------

def screenshot(args: dict, cfg: dict, ctx) -> dict:
    """PNG of the built-in 320x170 LCD."""
    from . import fbshot
    png = fbshot.lcd_png()
    if png is None:
        raise ToolError("could not read the LCD framebuffer")
    return {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}
