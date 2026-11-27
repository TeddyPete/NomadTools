"""Capture jobs: filter presets, the tcpdump command, and the supervisor.

A capture runs in its own small background process (the supervisor), not in
the screen app. The supervisor starts tcpdump writing straight to the .pcap
file, asks it for packet counts once a second (SIGUSR1), enforces the time,
size and free-disk limits, and keeps a state file the app reads. So a capture
never drops packets because the screen is busy, and it keeps going (and
still stops at its limits) if you leave the app.

tcpdump gets capture rights from the package (setcap), so nothing here runs
as root.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = os.path.expanduser(os.environ.get("NOMAD_CAPTURE_DIR", "~/Nomad-Captures"))
MIN_FREE_MB = 150          # stop before the SD card fills up
HEADER_SNAP = 128          # "headers only": enough for Ethernet/IP/UDP/TCP + some payload

# ---- filter presets ------------------------------------------------------------
# (key, menu label, short name for filenames/title, tcpdump expression, help)
PRESETS = [
    ("all", "Everything", "All", "", "Every packet on the port."),
    ("dante", "Dante (all)", "Dante",
     "udp and (port 319 or port 320 or port 4321 or port 4440 or port 4444 or port 4455 or port 5353"
     " or portrange 8700-8708 or port 8800 or portrange 14336-14591)",
     "Audio, clock, control, discovery"),
    ("dantectl", "Dante control (no audio)", "DanteCtl",
     "udp and (port 319 or port 320 or port 4440 or port 4444 or port 4455 or port 5353"
     " or portrange 8700-8708 or port 8800)",
     "Clock, control, discovery. No audio"),
    ("ptp", "PTP clock", "PTP", "(udp and (port 319 or port 320)) or ether proto 0x88f7",
     "PTP v1/v2 clock (Dante, AES67, AVB)"),
    ("aes67", "AES67 / RTP / SAP", "AES67",
     "udp and (port 319 or port 320 or port 9875 or port 5004 or port 5005)",
     "RTP 5004, SAP and PTP"),
    ("ndi", "NDI", "NDI", "port 5353 or port 5959 or portrange 5960-5999",
     "Discovery and streams 5959-5999"),
    ("control", "Control systems", "Control",
     "tcp and (port 23 or port 22 or port 41794 or port 41795 or port 41796 or port 41797 or port 1702"
     " or port 1710 or port 4352 or port 2202 or port 22023 or port 49280 or port 80 or port 443)",
     "Crestron, Q-SYS, Extron, PJLink, web"),
    ("multicast", "Multicast / IGMP", "Mcast", "igmp or ip multicast or ip6 multicast",
     "IGMP and all multicast streams"),
    ("bcast", "ARP / DHCP / broadcast", "Bcast", "arp or (udp and (port 67 or port 68)) or ether broadcast",
     "IP conflicts, rogue DHCP, storms"),
    ("discovery", "Discovery (mDNS/LLDP/CDP)", "Disc",
     "udp port 5353 or udp port 1900 or ether proto 0x88cc or ether dst 01:00:0c:cc:cc:cc",
     "mDNS, SSDP, LLDP, CDP (switch port)"),
    ("custom", "Custom (type a filter)", "Custom", None,
     "Type your own tcpdump filter"),
]
PRESET = {p[0]: p for p in PRESETS}

DURATIONS = ["No limit", "30 s", "1 min", "5 min", "15 min", "30 min", "1 h", "4 h", "12 h", "24 h"]
SIZES = ["10 MB", "50 MB", "100 MB", "250 MB", "500 MB", "1 GB", "2 GB", "4 GB"]


def seconds_of(label: str) -> int:
    m = re.match(r"(\d+)\s*(s|min|h)", label or "")
    if not m:
        return 0
    return int(m.group(1)) * {"s": 1, "min": 60, "h": 3600}[m.group(2)]


def mb_of(label: str) -> int:
    m = re.match(r"(\d+)\s*(MB|GB)", label or "")
    if not m:
        return 100
    return int(m.group(1)) * (1000 if m.group(2) == "GB" else 1)


def valid_ip(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def build_filter(cfg: dict) -> str:
    """Preset AND host AND port AND extra, as one tcpdump expression."""
    parts = []
    key = cfg.get("preset", "all")
    expr = PRESET.get(key, PRESET["all"])[3]
    if expr is None:                       # custom
        expr = (cfg.get("custom") or "").strip()
    if expr:
        parts.append(f"({expr})")
    host = (cfg.get("host") or "").strip()
    if host:
        parts.append(f"(host {host})")
    port = str(cfg.get("port") or "").strip()
    if port:
        parts.append(f"(port {port})")
    return " and ".join(parts)


def check_filter(expr: str) -> str:
    """'' if tcpdump accepts the filter, else its error message. Compiles it
    against an empty Ethernet pcap file, so no capture rights are needed."""
    if not expr:
        return ""
    tcpdump = shutil.which("tcpdump") or "/usr/bin/tcpdump"
    import struct
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".pcap")
    try:
        os.write(fd, struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 1))
        os.close(fd)
        r = subprocess.run([tcpdump, "-r", tmp, "-d", expr], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if r.returncode == 0:
        return ""
    err = [l for l in r.stderr.strip().splitlines() if l.strip() and "reading from file" not in l]
    msg = err[-1] if err else "filter not accepted"
    return msg.replace("tcpdump: ", "")


def clean(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "", (s or "").replace(" ", "-"))[:40]


def new_job(cfg: dict) -> dict:
    """Everything the supervisor needs, decided now (so later settings
    changes don't affect a running capture)."""
    iface = cfg.get("iface") or "eth0"
    adapter = ""
    if cfg.get("capmode") == "Inline tap":
        from . import tap
        adapter = cfg.get("tap_adapter") or tap.adapter_in_use() or (tap.adapters() or [""])[0]
        iface = tap.BRIDGE
    preset = PRESET.get(cfg.get("preset", "all"), PRESET["all"])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bits = [stamp] + [b for b in (clean(cfg.get("tag", "")), preset[2], ("Tap" if adapter else clean(iface))) if b]
    base = "_".join(bits)
    ring = cfg.get("mode") == "Ring buffer"
    return {
        "iface": iface,
        "tap": adapter,
        "filter": build_filter(cfg),
        "preset": preset[0],
        "preset_name": preset[1],
        "tag": cfg.get("tag", ""),
        "promisc": bool(cfg.get("promisc", True)),
        "snaplen": HEADER_SNAP if cfg.get("snap") == "Headers only" else 0,
        "seconds": seconds_of(cfg.get("duration", "No limit")),
        "max_mb": mb_of(cfg.get("size", "100 MB")),
        "ring": ring,
        "ring_files": 10,
        "dir": ROOT,
        "base": base,
        "file": os.path.join(ROOT, base + ".pcap"),
    }


def tcpdump_cmd(job: dict) -> list[str]:
    cmd = [shutil.which("tcpdump") or "/usr/bin/tcpdump", "-i", job["iface"], "-n", "-U",
           "-s", str(job["snaplen"])]
    if not job["promisc"]:
        cmd.append("-p")
    if os.geteuid() == 0:
        cmd += ["-Z", "root"]          # tests as root: don't drop to the tcpdump user
    if job["ring"]:
        per = max(1, job["max_mb"] // job["ring_files"])
        cmd += ["-C", str(per), "-W", str(job["ring_files"]), "-w", job["file"]]
    else:
        cmd += ["-w", job["file"]]
    if job["filter"]:
        cmd.append(job["filter"])
    return cmd


# ---- state (shared between the app and the supervisor) --------------------------

def state_dir() -> str:
    d = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not os.path.isdir(d) or not os.access(d, os.W_OK):
        d = "/tmp"
    return os.path.join(d, "nomad-packet-capture")


def state_path() -> str:
    return os.path.join(state_dir(), "state.json")


def read_state() -> dict:
    try:
        with open(state_path()) as f:
            st = json.load(f)
    except (OSError, ValueError):
        return {}
    booting = st.get("starting") and not st.get("pid") and time.time() - st.get("started", 0) < 10
    if st.get("running") and not booting and not _alive(st.get("pid")):
        st["running"] = False
        st.setdefault("reason", "capture process ended")
    return st


def write_state(st: dict) -> None:
    os.makedirs(state_dir(), exist_ok=True)
    tmp = state_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, state_path())


def _alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    try:   # a zombie isn't alive
        with open(f"/proc/{int(pid)}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def running() -> dict | None:
    st = read_state()
    return st if st.get("running") else None


def free_mb(path: str = ROOT) -> int:
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    try:
        s = os.statvfs(p or "/")
        return int(s.f_bavail * s.f_frsize / 1e6)
    except OSError:
        return 0


def start(cfg: dict) -> dict:
    """Start a capture in the background. Returns the job. Raises on problems."""
    if running():
        raise RuntimeError("A capture is already running.")
    if not shutil.which("tcpdump") and not os.path.exists("/usr/bin/tcpdump"):
        raise RuntimeError("tcpdump is not installed (sudo apt install tcpdump).")
    job = new_job(cfg)
    if job.get("tap"):
        from . import tap
        tap.start(job["tap"])          # no-op if the bridge is already up
    if not os.path.exists(f"/sys/class/net/{job['iface']}"):
        raise RuntimeError(f"Interface {job['iface']} not found.")
    err = check_filter(job["filter"])
    if err:
        raise RuntimeError(f"Filter problem: {err}")
    os.makedirs(job["dir"], exist_ok=True)
    if free_mb(job["dir"]) < MIN_FREE_MB + 20:
        raise RuntimeError(f"Not enough free space ({free_mb(job['dir'])} MB free).")
    write_state({"running": True, "starting": True, "pid": None, "job": job, "started": time.time(),
                 "packets": 0, "drops": 0, "bytes": 0})
    env = dict(os.environ)
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = pkg_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    p = subprocess.Popen([sys.executable, "-m", "nomadcap", "--supervise"], env=env, cwd=pkg_dir,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    # Wait until tcpdump is really running (or failed) so errors show at once.
    end = time.monotonic() + 6
    while time.monotonic() < end:
        st = read_state()
        if not st.get("starting"):
            break
        if p.poll() is not None:
            break
        time.sleep(0.1)
    st = read_state()
    if not st.get("running") and st.get("error"):
        raise RuntimeError(st["error"])
    return job


def stop(wait: float = 6.0) -> dict:
    st = read_state()
    pid = st.get("pid")
    if st.get("running") and pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
        end = time.monotonic() + wait
        while time.monotonic() < end and _alive(pid):
            time.sleep(0.1)
    return read_state()


# ---- supervisor (runs in its own process: python3 -m nomadcap --supervise) --------

STATS_RE = re.compile(r"(\d+) packets? captured, (\d+) packets? received by filter, (\d+) packets? dropped by kernel")


def job_files(job: dict) -> list[str]:
    """The capture's files (ring mode: base.pcap0..9), oldest first."""
    if not job["ring"]:
        return [job["file"]] if os.path.exists(job["file"]) else []
    d, name = os.path.split(job["file"])
    try:
        found = [os.path.join(d, f) for f in os.listdir(d) if re.fullmatch(re.escape(name) + r"\d+", f)]
    except OSError:
        return []
    return sorted(found, key=lambda p: (os.path.getmtime(p), p))


SYNC_EVERY = 5   # seconds: at most this much capture is lost if the power is cut


def sync_files(files: list[str]) -> None:
    """Push what tcpdump wrote out of the page cache onto the SD card."""
    for f in files[-1:]:
        try:
            fd = os.open(f, os.O_RDONLY)
            try:
                os.fdatasync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass


def supervise() -> int:
    st = read_state()
    job = st.get("job")
    if not job:
        return 1
    st.update(pid=os.getpid(), running=True)
    stop_reason = {"why": ""}

    def on_term(*_):
        stop_reason["why"] = stop_reason["why"] or "stopped"
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    try:
        proc = subprocess.Popen(tcpdump_cmd(job), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
    except OSError as e:
        st.update(running=False, starting=False, error=f"Could not start tcpdump: {e}")
        write_state(st)
        return 1
    os.set_blocking(proc.stderr.fileno(), False)
    errbuf = ""
    t0 = time.time()
    st.update(started=t0, tcpdump_pid=proc.pid)
    write_state(st)
    limit = job["max_mb"] * 1_000_000
    last_ask = 0.0
    last_sync = time.time()
    hist: list[tuple[float, int, int]] = []

    def read_err() -> str:
        nonlocal errbuf
        try:
            chunk = proc.stderr.read()
        except (OSError, ValueError):
            chunk = None
        if chunk:
            errbuf += chunk.decode(errors="replace")
        return errbuf

    while True:
        time.sleep(0.25)
        now = time.time()
        text = read_err()
        if proc.poll() is not None:
            if not stop_reason["why"]:
                lines = [l.replace("tcpdump: ", "") for l in text.splitlines()
                         if l.strip() and "listening on" not in l and not STATS_RE.search(l)
                         and not re.match(r"\d+ packets", l)]
                msg = lines[-1] if lines else f"tcpdump exited ({proc.returncode})"
                if "permitted" in msg.lower() or "permission" in msg.lower():
                    msg += ". tcpdump needs capture rights: reinstall the app"
                stop_reason["why"] = "error"
                st["error"] = msg
            break
        if st.get("starting") and ("listening on" in text or now - t0 > 1.5):
            st["starting"] = False
        if now - last_ask >= 1.0:
            last_ask = now
            try:
                proc.send_signal(signal.SIGUSR1)
            except OSError:
                pass
        m = None
        for m in STATS_RE.finditer(text):
            pass
        if m:
            st["packets"], st["drops"] = int(m.group(1)), int(m.group(3))
            errbuf = errbuf[m.end():]
        files = job_files(job)
        st["bytes"] = sum(os.path.getsize(f) for f in files if os.path.exists(f))
        st["files"] = files
        st["elapsed"] = now - t0
        hist.append((now, st.get("packets", 0), st["bytes"]))
        hist = [h for h in hist if now - h[0] <= 5]
        if len(hist) > 1 and hist[-1][0] > hist[0][0]:
            dt = hist[-1][0] - hist[0][0]
            st["pps"] = (hist[-1][1] - hist[0][1]) / dt
            st["bps"] = None if job["ring"] else (hist[-1][2] - hist[0][2]) * 8 / dt
        if not stop_reason["why"]:
            if job["seconds"] and now - t0 >= job["seconds"]:
                stop_reason["why"] = "time limit"
            elif not job["ring"] and st["bytes"] >= limit:
                stop_reason["why"] = "size limit"
            elif free_mb(job["dir"]) < MIN_FREE_MB:
                stop_reason["why"] = "disk almost full"
            elif job.get("tap") and not os.path.exists(f"/sys/class/net/{job['tap']}"):
                stop_reason["why"] = "USB adapter unplugged"
        if now - last_sync >= SYNC_EVERY:
            last_sync = now
            sync_files(files)
        write_state(st)
        if stop_reason["why"]:
            break

    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    text = read_err()
    for m in STATS_RE.finditer(text):
        st["packets"], st["drops"] = int(m.group(1)), int(m.group(3))
    finals = re.findall(r"^(\d+) packets? captured$", text, re.M)
    if finals:
        st["packets"] = int(finals[-1])
    drops = re.findall(r"^(\d+) packets? dropped by kernel$", text, re.M)
    if drops:
        st["drops"] = int(drops[-1])
    files = finish_files(job)
    st.update(running=False, starting=False, files=files, ended=time.time(), elapsed=time.time() - t0,
              reason=stop_reason["why"] or "stopped",
              bytes=sum(os.path.getsize(f) for f in files if os.path.exists(f)))
    for f in files:
        write_meta(f, job, st, len(files))
    write_state(st)
    return 0


def finish_files(job: dict) -> list[str]:
    """Ring files base.pcapN -> base_partNN.pcap in time order (Wireshark and
    Windows like a .pcap ending). Empty capture files are kept (0 packets)."""
    files = job_files(job)
    if not job["ring"]:
        return files
    out = []
    root = job["file"][:-5]
    for i, f in enumerate(files, 1):
        dst = f"{root}_part{i:02d}.pcap"
        try:
            os.replace(f, dst)
            out.append(dst)
        except OSError:
            out.append(f)
    return out


def meta_path(pcap: str) -> str:
    return pcap + ".json"


def write_meta(pcap: str, job: dict, st: dict, parts: int) -> None:
    meta = {
        "iface": job["iface"], "filter": job["filter"], "preset": job["preset_name"], "tag": job["tag"],
        "started": st.get("started"), "ended": st.get("ended"), "seconds": round(st.get("elapsed", 0), 1),
        "packets": st.get("packets", 0) if parts == 1 else None, "drops": st.get("drops", 0),
        "reason": st.get("reason"), "snaplen": job["snaplen"] or "full", "promisc": job["promisc"],
        "ring_parts": parts if job["ring"] else 0, "tap": job.get("tap", ""), "app": "Nomad Packet Capture",
    }
    try:
        with open(meta_path(pcap), "w") as f:
            json.dump(meta, f, indent=1)
    except OSError:
        pass


def autotap(adapter: str) -> int:
    """Called by the udev-started unit when a USB Ethernet adapter appears:
    bridge it with the built-in port and start capturing, if Auto tap is on."""
    from . import settings as S
    from . import tap
    cfg = S.load()
    if not cfg.get("autotap"):
        return 0
    time.sleep(2)                       # let the adapter settle / NM notice it
    if adapter == tap.builtin() or adapter not in tap.adapters():
        return 0
    if running():
        return 0
    cfg.update(capmode="Inline tap", tap_adapter=adapter)
    try:
        start(cfg)
    except RuntimeError as e:
        write_state({"running": False, "error": f"Auto tap: {e}", "reason": "auto tap failed",
                     "job": {"iface": tap.BRIDGE, "tap": adapter}})
        print(f"autotap: {e}", file=sys.stderr)
        return 1
    return 0
