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


# ---- one-line packet descriptions (desktop viewer) --------------------------------

PTP_TYPES = {0: "Sync", 1: "Delay_Req", 2: "Pdelay_Req", 3: "Pdelay_Resp", 8: "Follow_Up", 9: "Delay_Resp",
             10: "Pdelay_Resp_FU", 11: "Announce", 12: "Signaling", 13: "Management"}
DHCP_TYPES = {1: "Discover", 2: "Offer", 3: "Request", 4: "Decline", 5: "ACK", 6: "NAK", 7: "Release", 8: "Inform"}
IGMP_TYPES = {0x11: "Query", 0x12: "v1 Report", 0x16: "v2 Report", 0x17: "Leave", 0x22: "v3 Report"}


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def _tcp_flags(f: int) -> str:
    names = [(0x02, "SYN"), (0x10, "ACK"), (0x01, "FIN"), (0x04, "RST"), (0x08, "PSH")]
    return ",".join(n for bit, n in names if f & bit)


def describe(data: bytes, linktype: int) -> tuple[str, str, str, str]:
    """(source, destination, protocol, info) for one packet."""
    proto, _ = classify(data, linktype)
    if linktype != 1 or len(data) < 14:
        return "", "", proto, f"{len(data)} bytes"
    dst_mac, src_mac = _mac(data[0:6]), _mac(data[6:12])
    et, off = struct.unpack_from("!H", data, 12)[0], 14
    vlan = ""
    while et in (0x8100, 0x88A8) and len(data) >= off + 4:
        vlan = f"VLAN {struct.unpack_from('!H', data, off)[0] & 0xFFF} "
        et = struct.unpack_from("!H", data, off + 2)[0]
        off += 4
    l3 = data[off:]
    if et == 0x0806 and len(l3) >= 28:
        op = struct.unpack_from("!H", l3, 6)[0]
        spa, tpa = socket.inet_ntoa(l3[14:18]), socket.inet_ntoa(l3[24:28])
        info = f"Who has {tpa}? Tell {spa}" if op == 1 else f"{spa} is at {_mac(l3[8:14])}"
        if op == 1 and spa == tpa:
            info = f"Gratuitous ARP for {spa}"
        return src_mac, dst_mac, "ARP", vlan + info
    if et == 0x88F7 and len(l3) >= 34:
        return src_mac, dst_mac, "PTP (L2)", vlan + f"{PTP_TYPES.get(l3[0] & 0x0F, 'type ' + str(l3[0] & 0x0F))} domain {l3[4]}"
    if et != 0x0800 or len(l3) < 20:
        return src_mac, dst_mac, proto, vlan + f"{len(data)} bytes"
    ihl = (l3[0] & 0x0F) * 4
    p = l3[9]
    src, dst = socket.inet_ntoa(l3[12:16]), socket.inet_ntoa(l3[16:20])
    l4 = l3[ihl:]
    info = ""
    if p == 2 and l4:
        t = l4[0]
        grp = socket.inet_ntoa(l4[4:8]) if len(l4) >= 8 else ""
        info = f"{IGMP_TYPES.get(t, hex(t))} {grp if grp != '0.0.0.0' else '(general)'}"
    elif p == 1 and len(l4) >= 2:
        info = {0: "Echo reply", 8: "Echo request", 3: "Unreachable", 11: "TTL exceeded"}.get(l4[0], f"type {l4[0]}")
    elif p == 6 and len(l4) >= 20:
        sp, dp = struct.unpack_from("!HH", l4)
        doff = (l4[12] >> 4) * 4
        info = f"{sp} → {dp} [{_tcp_flags(l4[13])}] len {max(0, len(l4) - doff)}"
    elif p == 17 and len(l4) >= 8:
        sp, dp = struct.unpack_from("!HH", l4)
        pay = l4[8:]
        info = f"{sp} → {dp} len {len(pay)}"
        if proto == "PTP" and len(pay) >= 34:
            info = f"{PTP_TYPES.get(pay[0] & 0x0F, 'type ' + str(pay[0] & 0x0F))} domain {pay[4]}  ({sp}→{dp})"
        elif proto == "DHCP" and len(pay) > 240:
            i = 240
            while i + 2 <= len(pay) and pay[i] != 255:
                if pay[i] == 53 and i + 2 < len(pay):
                    info = f"DHCP {DHCP_TYPES.get(pay[i + 2], pay[i + 2])}  xid {pay[4:8].hex()}"
                    break
                i += 2 + (pay[i + 1] if pay[i] else -1)
        elif proto == "mDNS" and len(pay) >= 12:
            qd, an = struct.unpack_from("!HH", pay, 4)
            info = ("Response" if pay[2] & 0x80 else "Query") + f" q={qd} a={an}"
    else:
        info = f"IP proto {p}"
    return src, dst, proto, vlan + info


class Reader(Follower):
    """Follower that also keeps the last N packets for a packet list."""

    def __init__(self, keep: int = 4000):
        super().__init__()
        from collections import deque
        self.keep = keep
        self.rows = deque(maxlen=keep)
        self.n = 0

    def reset(self):
        keep = self.keep
        self.__init__(keep)

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
        if size < self.pos:
            self.pos = 24
        if size - self.pos > self.MAX_BYTES_PER_POLL * 3:
            self.skipped = True
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
            sec, frac, incl, orig = struct.unpack_from(fmt, buf, i)
            if incl > 262144 or incl > orig + 65535:
                break
            if i + 16 + incl > len(buf):
                break
            data = buf[i + 16:i + 16 + incl]
            src, dst, proto, info = describe(data, self.linktype)
            self.protos[proto] += 1
            if src and "." in src:
                self.talkers[src] += 1
            self.seen += 1
            self.n += 1
            self.rows.append((self.n, sec + frac / 1e6, src, dst, proto, orig, info, data))
            i += 16 + incl
        self.pos += i
