"""Shared helpers: interfaces, running commands, TCP probes, Telnet and SSH."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b[=>]")


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None or os.path.exists(f"/usr/sbin/{cmd}")


def which(cmd: str) -> str:
    return shutil.which(cmd) or (f"/usr/sbin/{cmd}" if os.path.exists(f"/usr/sbin/{cmd}") else cmd)


def run(cmd: list[str], timeout: float = 10) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout + p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"({e})"


def stream(out, cmd: list[str], color=None, filt=None) -> int:
    """Run a command, writing each output line to out until it ends or the
    user stops it. Returns the exit status (or -1)."""
    try:
        p = out.track(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1))
    except OSError as e:
        out.bad(f"Can't run {cmd[0]}: {e}")
        return -1
    for line in p.stdout:
        if out.stopped:
            break
        line = line.rstrip()
        if filt:
            line = filt(line)
            if line is None:
                continue
        if color:
            out.line(line, color)
        else:
            out.line(line)
    if out.stopped:
        p.terminate()
    try:
        return p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        p.kill()
        return -1


# ------------------------------------------------------------ interfaces

class Iface:
    def __init__(self, name, state, mac, addrs):
        self.name, self.state, self.mac, self.addrs = name, state, mac, addrs  # addrs: [(ip, prefix)]

    @property
    def ip(self) -> str | None:
        return self.addrs[0][0] if self.addrs else None

    @property
    def network(self) -> ipaddress.IPv4Network | None:
        if not self.addrs:
            return None
        ip, pfx = self.addrs[0]
        return ipaddress.ip_network(f"{ip}/{pfx}", strict=False)

    @property
    def up(self) -> bool:
        return self.state == "UP" or bool(self.addrs)


def interfaces() -> list[Iface]:
    try:
        data = json.loads(run(["ip", "-j", "addr"]))
    except ValueError:
        return []
    out = []
    for d in data:
        name = d.get("ifname", "")
        if name == "lo" or name.startswith(("p2p", "docker", "veth")):
            continue
        addrs = [(a["local"], a["prefixlen"]) for a in d.get("addr_info", []) if a.get("family") == "inet"]
        out.append(Iface(name, d.get("operstate", ""), d.get("address", ""), addrs))
    return out


def iface(name: str) -> Iface | None:
    return next((i for i in interfaces() if i.name == name), None)


def best_iface(pref: str | None = None) -> Iface | None:
    ifs = interfaces()
    if pref:
        for i in ifs:
            if i.name == pref:
                return i
    for want in ("eth", "en", "wl"):
        for i in ifs:
            if i.name.startswith(want) and i.ip:
                return i
    return ifs[0] if ifs else None


def wired_name() -> str:
    for i in interfaces():
        if i.name.startswith(("eth", "en")):
            return i.name
    return "eth0"


def iface_names() -> list[str]:
    return [i.name for i in interfaces()]


def default_gateway(dev: str | None = None) -> str | None:
    try:
        routes = json.loads(run(["ip", "-j", "route", "show", "default"]))
    except ValueError:
        return None
    for r in routes:
        if dev is None or r.get("dev") == dev:
            return r.get("gateway")
    return None


def mac_of(name: str) -> str:
    try:
        return open(f"/sys/class/net/{name}/address").read().strip()
    except OSError:
        return "00:00:00:00:00:00"


def ifindex(name: str) -> int:
    try:
        return socket.if_nametoindex(name)
    except OSError:
        return 0


def arp_table() -> dict[str, str]:
    """IP -> MAC from the kernel neighbour table."""
    out = {}
    try:
        for line in open("/proc/net/arp").read().splitlines()[1:]:
            p = line.split()
            if len(p) >= 4 and p[3] != "00:00:00:00:00:00":
                out[p[0]] = p[3].lower()
    except OSError:
        pass
    return out


# ------------------------------------------------------------ probes

def tcp_open(ip: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def ports_open(ip: str, ports: list[int], timeout: float = 1.0) -> list[int]:
    with ThreadPoolExecutor(max_workers=min(16, len(ports) or 1)) as ex:
        res = list(ex.map(lambda p: (p, tcp_open(ip, p, timeout)), ports))
    return [p for p, ok in res if ok]


def banner(ip: str, port: int, timeout: float = 2.0, send: bytes | None = None, limit: int = 2048) -> str:
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(timeout)
            if send:
                s.sendall(send)
            data = b""
            end = time.monotonic() + timeout
            while len(data) < limit and time.monotonic() < end:
                try:
                    chunk = s.recv(1024)
                except socket.timeout:
                    break
                if not chunk:
                    break
                data += chunk
                if send is None and b"\n" in data and len(data) > 20:
                    break
            return strip_telnet(data).decode("latin-1", "replace")
    except OSError:
        return ""


def rdns(ip: str, timeout: float = 1.5) -> str:
    with ThreadPoolExecutor(max_workers=1) as ex:
        f = ex.submit(lambda: socket.gethostbyaddr(ip)[0])
        try:
            return f.result(timeout=timeout)
        except Exception:
            return ""


def http_title(ip: str, port: int = 80, timeout: float = 2.0) -> str:
    txt = banner(ip, port, timeout, f"GET / HTTP/1.0\r\nHost: {ip}\r\n\r\n".encode(), limit=8192)
    m = re.search(r"<title[^>]*>([^<]{1,120})", txt, re.I)
    server = re.search(r"^Server:\s*(.+)$", txt, re.I | re.M)
    t = m.group(1).strip() if m else ""
    if server:
        t = (t + f" [{server.group(1).strip()}]").strip()
    return t


# ------------------------------------------------------------ telnet

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


def strip_telnet(data: bytes, sock=None) -> bytes:
    """Remove telnet option negotiation. If sock is given, refuse every
    option the far end asks for (so it falls back to plain text)."""
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == IAC and i + 1 < len(data):
            cmd = data[i + 1]
            if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(data):
                opt = data[i + 2]
                if sock is not None:
                    try:
                        if cmd == DO:
                            sock.sendall(bytes([IAC, WONT, opt]))
                        elif cmd == WILL:
                            sock.sendall(bytes([IAC, DO if opt in (1, 3) else DONT, opt]))
                    except OSError:
                        pass
                i += 3
                continue
            if cmd == SB:
                j = data.find(bytes([IAC, SE]), i)
                i = j + 2 if j >= 0 else len(data)
                continue
            if cmd == IAC:
                out.append(IAC)
            i += 2
            continue
        out.append(b)
        i += 1
    return bytes(out)


class LineClient:
    """A text session over Telnet/raw TCP or SSH with prompt-based reads."""

    def __init__(self):
        self.sock = None
        self.chan = None
        self.ssh = None
        self.buf = b""

    # -- connect
    def telnet(self, host: str, port: int = 23, timeout: float = 5.0) -> "LineClient":
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.3)
        return self

    def open_ssh(self, host: str, user: str, password: str, port: int = 22, timeout: float = 8.0) -> "LineClient":
        import paramiko
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.ssh.connect(host, port=port, username=user, password=password, timeout=timeout,
                             allow_agent=False, look_for_keys=False, banner_timeout=timeout,
                             auth_timeout=timeout)
        except paramiko.ssh_exception.AuthenticationException:
            # some AV gear only offers keyboard-interactive
            t = self.ssh.get_transport()
            if t is None or not t.is_active():
                raise
            t.auth_interactive(user, lambda title, instr, prompts: [password for _ in prompts])
        self.chan = self.ssh.invoke_shell(width=200, height=50)
        self.chan.settimeout(0.3)
        return self

    # -- io
    def send(self, text: str) -> None:
        data = text.encode("latin-1", "replace")
        if self.chan is not None:
            self.chan.send(data)
        else:
            self.sock.sendall(data)

    def _recv(self) -> bytes:
        try:
            if self.chan is not None:
                return self.chan.recv(4096) or b""
            data = self.sock.recv(4096)
            if not data:
                raise EOFError
            return strip_telnet(data, self.sock)
        except (socket.timeout, TimeoutError):
            return b""

    def read_until(self, patterns, timeout: float = 5.0, quiet: float = 0.0) -> str:
        """Read until a regex in patterns matches the text so far, or until
        quiet seconds pass with no new data (if quiet > 0), or timeout."""
        if isinstance(patterns, str):
            patterns = [patterns]
        regs = [re.compile(p, re.M) for p in patterns]
        end = time.monotonic() + timeout
        last = time.monotonic()
        while time.monotonic() < end:
            try:
                chunk = self._recv()
            except EOFError:
                break
            if chunk:
                self.buf += chunk
                last = time.monotonic()
            text = self.buf.decode("latin-1", "replace")
            if any(r.search(text) for r in regs):
                break
            if quiet and self.buf and time.monotonic() - last > quiet:
                break
        text = ANSI.sub("", self.buf.decode("latin-1", "replace")).replace("\r", "")
        self.buf = b""
        return text

    def close(self) -> None:
        for c in (self.chan, self.ssh, self.sock):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
