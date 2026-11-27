"""Packet capture through tcpdump (the package gives tcpdump capture rights
via file capabilities, so the app itself never runs as root).

tcpdump writes pcap to a pipe; we parse it here into simple Packet objects.
"""
from __future__ import annotations

import select
import socket
import struct
import subprocess
import time
from dataclasses import dataclass

from . import util


@dataclass
class Packet:
    ts: float
    raw: bytes
    src_mac: str = ""
    dst_mac: str = ""
    ethertype: int = 0
    l3: bytes = b""          # payload after the Ethernet (and VLAN) header
    vlan: int | None = None
    src: str = ""
    dst: str = ""
    proto: int = 0           # 6 tcp, 17 udp, 2 igmp
    sport: int = 0
    dport: int = 0
    payload: bytes = b""
    tcp_flags: int = 0


def mac_str(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def decode(ts: float, data: bytes, linktype: int) -> Packet:
    p = Packet(ts, data)
    if linktype == 1:
        if len(data) < 14:
            return p
        p.dst_mac, p.src_mac = mac_str(data[0:6]), mac_str(data[6:12])
        et, off = struct.unpack_from("!H", data, 12)[0], 14
        while et in (0x8100, 0x88A8) and len(data) >= off + 4:
            p.vlan = struct.unpack_from("!H", data, off)[0] & 0x0FFF
            et = struct.unpack_from("!H", data, off + 2)[0]
            off += 4
    elif linktype == 113:   # Linux cooked
        if len(data) < 16:
            return p
        p.src_mac = mac_str(data[6:12])
        et, off = struct.unpack_from("!H", data, 14)[0], 16
    else:
        return p
    p.ethertype, p.l3 = et, data[off:]
    if et == 0x0800 and len(p.l3) >= 20:
        ihl = (p.l3[0] & 0x0F) * 4
        p.proto = p.l3[9]
        p.src, p.dst = socket.inet_ntoa(p.l3[12:16]), socket.inet_ntoa(p.l3[16:20])
        total = struct.unpack_from("!H", p.l3, 2)[0]
        l4 = p.l3[ihl:total if total >= ihl else None]
        if p.proto == 17 and len(l4) >= 8:
            p.sport, p.dport = struct.unpack_from("!HH", l4)
            p.payload = l4[8:]
        elif p.proto == 6 and len(l4) >= 20:
            p.sport, p.dport = struct.unpack_from("!HH", l4)
            doff = (l4[12] >> 4) * 4
            p.tcp_flags = l4[13]
            p.payload = l4[doff:]
        else:
            p.payload = l4
    return p


class Capture:
    """Iterate packets from tcpdump. Stop with .stop() or the out flag."""

    def __init__(self, iface: str, bpf: str = "", promisc: bool = True, snaplen: int = 2048,
                 out=None, raw_sink=None):
        cmd = [util.which("tcpdump"), "-i", iface, "-U", "-n", "-s", str(snaplen), "-w", "-"]
        if not promisc:
            cmd.insert(1, "-p")
        if bpf:
            cmd += bpf.split()
        self.cmd = cmd
        self.out = out
        self.raw_sink = raw_sink   # file object that gets the raw pcap stream
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if out is not None:
            out.track(self.proc)
        self.buf = b""
        self.linktype = None
        self.swap = "<"
        self.nano = False
        self.error = ""
        self.count = 0
        self.bytes = 0

    def _fill(self, need: int, timeout: float) -> bool:
        end = time.monotonic() + timeout
        fd = self.proc.stdout.fileno()
        while len(self.buf) < need:
            left = end - time.monotonic()
            if left <= 0:
                return False
            r, _, _ = select.select([fd], [], [], min(left, 0.25))
            if self.out is not None and self.out.stopped:
                return False
            if not r:
                if self.proc.poll() is not None:
                    self._read_err()
                    return False
                continue
            import os
            chunk = os.read(fd, 65536)
            if not chunk:
                self._read_err()
                return False
            if self.raw_sink is not None:
                self.raw_sink.write(chunk)
            self.buf += chunk
        return True

    def _read_err(self) -> None:
        try:
            err = self.proc.stderr.read().decode(errors="replace").strip()
        except Exception:
            err = ""
        if err and not self.error:
            lines = [l for l in err.splitlines() if "listening on" not in l and "packets" not in l]
            self.error = lines[-1] if lines else ""

    def next(self, timeout: float = 1.0) -> Packet | None:
        """Next packet, or None when none arrived within timeout."""
        if self.linktype is None:
            if not self._fill(24, max(timeout, 3.0)):
                return None
            magic = self.buf[:4]
            if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
                self.swap = "<"
            else:
                self.swap = ">"
            self.nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
            self.linktype = struct.unpack_from(self.swap + "I", self.buf, 20)[0]
            self.buf = self.buf[24:]
        if not self._fill(16, timeout):
            return None
        sec, frac, incl, _ = struct.unpack_from(self.swap + "IIII", self.buf)
        if not self._fill(16 + incl, timeout + 1):
            return None
        data = self.buf[16:16 + incl]
        self.buf = self.buf[16 + incl:]
        self.count += 1
        self.bytes += incl
        return decode(sec + frac / (1e9 if self.nano else 1e6), data, self.linktype)

    def packets(self, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.out is not None and self.out.stopped:
                break
            p = self.next(min(1.0, max(0.05, end - time.monotonic())))
            if p is not None:
                yield p
            elif self.proc.poll() is not None:
                break

    def stop(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self._read_err()


def check(out, iface: str) -> bool:
    """Tell the user if capture can't work and why."""
    if not util.have("tcpdump"):
        out.bad("tcpdump is not installed (sudo apt install tcpdump)")
        return False
    if not iface or not util.iface(iface):
        out.bad(f"Interface {iface or '?'} not found")
        return False
    return True


def explain_error(out, cap: Capture) -> None:
    if cap.error:
        out.bad("Capture: " + cap.error)
        if "permission" in cap.error.lower() or "operation not permitted" in cap.error.lower():
            out.warn("tcpdump lacks capture rights. Reinstall the app package, or run:")
            out.warn("sudo setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump")


def join_groups(iface_ip: str | None, groups: list[str]) -> socket.socket | None:
    """Join multicast groups so IGMP-snooping switches send them to us.
    The socket must stay open for as long as we want the traffic."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("", 0))
        for g in groups:
            mreq = socket.inet_aton(g) + socket.inet_aton(iface_ip or "0.0.0.0")
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass
        return s
    except OSError:
        return None
