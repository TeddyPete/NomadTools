"""Read .pcap files: follow a growing capture for the live view, and count
packets in a saved file. Pure Python, headers only.

The live view reads the file tcpdump is writing. If traffic comes in faster
than the Pi can read it, it skips ahead (the summary is a sample then), so
it never slows the capture down.
"""
from __future__ import annotations

import os
import socket
import struct
from collections import Counter

PORTS = {
    319: "PTP", 320: "PTP", 4321: "Dante audio", 4440: "Dante ctl", 4444: "Dante ctl", 4455: "Dante ctl",
    8700: "Dante ctl", 8701: "Dante ctl", 8702: "Dante ctl", 8703: "Dante ctl", 8704: "Dante ctl",
    8705: "Dante ctl", 8706: "Dante ctl", 8707: "Dante ctl", 8708: "Dante mon", 8800: "Dante ctl",
    5353: "mDNS", 1900: "SSDP", 9875: "SAP", 5004: "RTP/AES67", 5005: "RTP/AES67",
    41794: "Crestron CIP", 41795: "Crestron CTP", 41796: "Crestron CIP-S", 41797: "Crestron CTP-S",
    1702: "Q-SYS", 1710: "Q-SYS QRC", 2467: "Q-SYS disc", 4352: "PJLink", 2202: "Shure", 49280: "Yamaha",
    22023: "Extron SIS", 23: "Telnet", 22: "SSH", 80: "HTTP", 443: "HTTPS", 53: "DNS", 67: "DHCP", 68: "DHCP",
    123: "NTP", 161: "SNMP", 162: "SNMP trap", 5959: "NDI", 137: "NetBIOS", 138: "NetBIOS", 5355: "LLMNR",
    3702: "WS-Disc", 554: "RTSP", 1935: "RTMP",
}
ETHER = {0x0806: "ARP", 0x88F7: "PTP (L2)", 0x88CC: "LLDP", 0x86DD: "IPv6", 0x22F0: "AVB", 0x8809: "LACP"}


def port_name(sport: int, dport: int, proto: str) -> str:
    for p in (dport, sport):
        if p in PORTS:
            return PORTS[p]
    for p in (dport, sport):
        if 14336 <= p <= 14591:
            return "Dante audio"
        if 5960 <= p <= 5999:
            return "NDI"
    return f"{proto} {min(sport, dport)}"


def classify(data: bytes, linktype: int) -> tuple[str, str]:
    """(protocol label, source address) for one packet."""
    if linktype == 1:
        if len(data) < 14:
            return "short", ""
        dst = data[0:6]
        et, off = struct.unpack_from("!H", data, 12)[0], 14
        while et in (0x8100, 0x88A8) and len(data) >= off + 4:
            et = struct.unpack_from("!H", data, off + 2)[0]
            off += 4
        if et < 0x0600:                       # 802.3 length: LLC (STP, CDP)
            if dst == b"\x01\x80\xc2\x00\x00\x00":
                return "STP", ""
            if dst == b"\x01\x00\x0c\xcc\xcc\xcc":
                return "CDP", ""
            return "LLC", ""
    elif linktype == 113:                     # Linux cooked
        if len(data) < 16:
            return "short", ""
        et, off = struct.unpack_from("!H", data, 14)[0], 16
    elif linktype == 101:                     # raw IP
        et, off = 0x0800, 0
    else:
        return f"link {linktype}", ""
    l3 = data[off:]
    if et != 0x0800:
        return ETHER.get(et, f"eth {et:04x}"), ""
    if len(l3) < 20:
        return "IPv4", ""
    ihl = (l3[0] & 0x0F) * 4
    proto = l3[9]
    src = socket.inet_ntoa(l3[12:16])
    l4 = l3[ihl:]
    if proto == 2:
        return "IGMP", src
    if proto == 1:
        return "ICMP", src
    if proto in (6, 17) and len(l4) >= 4:
        sport, dport = struct.unpack_from("!HH", l4)
        return port_name(sport, dport, "TCP" if proto == 6 else "UDP"), src
    return f"IP proto {proto}", src


class Follower:
    """Follow a growing pcap (or the newest of a set of ring files)."""

    MAX_BYTES_PER_POLL = 2_000_000

    def __init__(self):
        self.path = None
        self.pos = 0
        self.linktype = None
        self.swap = "<"
        self.protos: Counter = Counter()
        self.talkers: Counter = Counter()
        self.seen = 0
        self.skipped = False

    def reset(self):
        self.__init__()

    def _open(self, path: str) -> bool:
        try:
            with open(path, "rb") as f:
                hdr = f.read(24)
        except OSError:
            return False
        if len(hdr) < 24:
            return False
        magic = hdr[:4]
        if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
            self.swap = "<"
        elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
            self.swap = ">"
        else:
            return False
        self.linktype = struct.unpack_from(self.swap + "I", hdr, 20)[0] & 0x0FFFFFFF
        self.path, self.pos = path, 24
        return True

    def poll(self, path: str | None) -> None:
        if not path:
            return
        if path != self.path:
            if not self._open(path):
                return
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size < self.pos:                   # ring file reused
            self.pos = 24
        if size - self.pos > self.MAX_BYTES_PER_POLL * 3:
            self.skipped = True               # far behind: resync near the end
            self._resync(path, size - self.MAX_BYTES_PER_POLL)
        try:
            with open(path, "rb") as f:
                f.seek(self.pos)
                buf = f.read(min(size - self.pos, self.MAX_BYTES_PER_POLL))
        except OSError:
            return
        i = 0
        fmt = self.swap + "IIII"
        while i + 16 <= len(buf):
            _, _, incl, orig = struct.unpack_from(fmt, buf, i)
            if incl > 262144 or incl > orig + 65535:  # lost sync
                break
            if i + 16 + incl > len(buf):
                break
            proto, src = classify(buf[i + 16:i + 16 + incl], self.linktype)
            self.protos[proto] += 1
            if src:
                self.talkers[src] += 1
            self.seen += 1
            i += 16 + incl
        self.pos += i

    def _resync(self, path: str, at: int) -> None:
        """Find a believable record header at or after byte `at`."""
        try:
            with open(path, "rb") as f:
                f.seek(at)
                buf = f.read(300_000)
        except OSError:
            return
        fmt = self.swap + "IIII"
        for j in range(0, len(buf) - 48):
            sec, usec, incl, orig = struct.unpack_from(fmt, buf, j)
            if 0 < incl <= orig <= 262144 and usec < 1_000_000_000 and sec > 1_000_000_000:
                k = j + 16 + incl
                if k + 16 <= len(buf):
                    s2, u2, i2, o2 = struct.unpack_from(fmt, buf, k)
                    if 0 < i2 <= o2 <= 262144 and abs(s2 - sec) < 60:
                        self.pos = at + j
                        return
        self.pos = at


def summarize(path: str, limit_bytes: int = 50_000_000) -> dict:
    """Packet count, first/last time and top protocols of a saved file
    (reads at most limit_bytes)."""
    fl = Follower()
    fl.MAX_BYTES_PER_POLL = limit_bytes
    if not fl._open(path):
        return {"ok": False}
    first = last = None
    try:
        with open(path, "rb") as f:
            f.seek(24)
            buf = f.read(limit_bytes)
    except OSError:
        return {"ok": False}
    i, n = 0, 0
    fmt = fl.swap + "IIII"
    while i + 16 <= len(buf):
        sec, frac, incl, _ = struct.unpack_from(fmt, buf, i)
        if i + 16 + incl > len(buf):
            break
        proto, src = classify(buf[i + 16:i + 16 + incl], fl.linktype)
        fl.protos[proto] += 1
        if src:
            fl.talkers[src] += 1
        first = first if first is not None else sec
        last = sec
        n += 1
        i += 16 + incl
    return {"ok": True, "packets": n, "complete": os.path.getsize(path) <= limit_bytes + 24,
            "first": first, "last": last, "protos": fl.protos.most_common(8),
            "talkers": fl.talkers.most_common(5)}
