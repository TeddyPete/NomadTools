"""Minimal mDNS / DNS-SD browser (no avahi needed).

Queries go from an ordinary UDP port, so responders answer us directly
("legacy unicast", RFC 6762 s6.7). We also set the QU bit. No root needed.
"""
from __future__ import annotations

import random
import socket
import struct
import time
from dataclasses import dataclass, field

GROUP, PORT = "224.0.0.251", 5353
PTR, A, TXT, AAAA, SRV, ANY = 12, 1, 16, 28, 33, 255


def encode_name(name: str) -> bytes:
    out = b""
    for part in name.rstrip(".").split("."):
        b = part.encode()
        out += bytes([len(b)]) + b
    return out + b"\0"


def build_query(questions: list[tuple[str, int]]) -> bytes:
    hdr = struct.pack("!HHHHHH", random.randint(1, 65535), 0, len(questions), 0, 0, 0)
    body = b"".join(encode_name(n) + struct.pack("!HH", t, 0x8001) for n, t in questions)
    return hdr + body


def read_name(data: bytes, off: int) -> tuple[str, int]:
    labels, jumped, end, hops = [], False, off, 0
    while off < len(data) and hops < 64:
        ln = data[off]
        if ln == 0:
            off += 1
            break
        if ln & 0xC0 == 0xC0:
            ptr = ((ln & 0x3F) << 8) | data[off + 1]
            if not jumped:
                end = off + 2
            jumped, off, hops = True, ptr, hops + 1
            continue
        labels.append(data[off + 1: off + 1 + ln].decode("utf-8", "replace"))
        off += 1 + ln
    return ".".join(labels), (end if jumped else off)


@dataclass
class RR:
    name: str
    type: int
    data: object


def parse(data: bytes) -> list[RR]:
    try:
        _, flags, qd, an, ns, ar = struct.unpack_from("!HHHHHH", data)
    except struct.error:
        return []
    off = 12
    for _ in range(qd):
        _, off = read_name(data, off)
        off += 4
    out = []
    for _ in range(an + ns + ar):
        try:
            name, off = read_name(data, off)
            t, _, _, rdlen = struct.unpack_from("!HHIH", data, off)
            off += 10
            rd = data[off: off + rdlen]
            if t == PTR:
                val = read_name(data, off)[0]
            elif t == A and rdlen == 4:
                val = socket.inet_ntoa(rd)
            elif t == AAAA and rdlen == 16:
                val = socket.inet_ntop(socket.AF_INET6, rd)
            elif t == SRV:
                pri, w, port = struct.unpack_from("!HHH", data, off)
                val = (read_name(data, off + 6)[0], port)
            elif t == TXT:
                items, i = {}, 0
                while i < len(rd):
                    ln = rd[i]
                    s = rd[i + 1: i + 1 + ln].decode("utf-8", "replace")
                    k, _, v = s.partition("=")
                    if k:
                        items[k] = v
                    i += 1 + ln
                val = items
            else:
                val = rd
            out.append(RR(name, t, val))
            off += rdlen
        except (struct.error, IndexError):
            break
    return out


def _sock(iface_ip: str | None = None) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    if iface_ip:
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))
        except OSError:
            pass
    s.bind(("", 0))
    s.settimeout(0.2)
    return s


def query(questions: list[tuple[str, int]], seconds: float = 3.0, iface_ips: list[str] | None = None,
          stop=None, unicast_to: str | None = None) -> tuple[list[RR], dict[str, str]]:
    """Send the questions (on each interface) and collect answers.
    Returns (records, name->source ip for each responder's records)."""
    socks = [_sock(ip) for ip in (iface_ips or [None])]
    pkt = build_query(questions)
    recs: list[RR] = []
    src: dict[str, str] = {}
    sends = [0.0, 0.7, 1.8]
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        if stop and stop():
            break
        el = time.monotonic() - t0
        while sends and el >= sends[0]:
            sends.pop(0)
            for s in socks:
                try:
                    s.sendto(pkt, (unicast_to or GROUP, PORT))
                except OSError:
                    pass
        for s in socks:
            try:
                data, addr = s.recvfrom(9000)
            except (socket.timeout, OSError):
                continue
            for rr in parse(data):
                recs.append(rr)
                src.setdefault(rr.name.lower(), addr[0])
    for s in socks:
        s.close()
    return recs, src


@dataclass
class Service:
    instance: str
    type: str
    host: str = ""
    port: int = 0
    ips: list = field(default_factory=list)
    txt: dict = field(default_factory=dict)
    src: str = ""

    @property
    def name(self) -> str:
        return self.instance[: -len(self.type) - 1] if self.instance.endswith("." + self.type) else self.instance

    @property
    def ip(self) -> str:
        v4 = [i for i in self.ips if "." in i]
        return (v4 or self.ips or [self.src])[0]


def browse(types: list[str], seconds: float = 3.0, iface_ips=None, stop=None) -> list[Service]:
    """Find instances of each service type with host, port, IPs and TXT."""
    qs = [(t if t.endswith(".local") else t + ".local", PTR) for t in types]
    recs, src = query(qs, seconds, iface_ips, stop)
    return assemble(recs, src, [q[0] for q in qs])


def assemble(recs: list[RR], src: dict, types: list[str]) -> list[Service]:
    types_l = {t.lower() for t in types}
    svcs: dict[str, Service] = {}
    for r in recs:
        if r.type == PTR and r.name.lower() in types_l:
            key = str(r.data).lower()
            svcs.setdefault(key, Service(str(r.data), r.name, src=src.get(r.name.lower(), "")))
    addrs: dict[str, list] = {}
    for r in recs:
        if r.type in (A, AAAA):
            lst = addrs.setdefault(r.name.lower(), [])
            if r.data not in lst:
                lst.append(r.data)
    for r in recs:
        s = svcs.get(r.name.lower())
        if not s:
            continue
        if r.type == SRV:
            s.host, s.port = r.data
            s.src = src.get(r.name.lower(), s.src)
        elif r.type == TXT:
            s.txt.update(r.data)
    missing = []
    for s in svcs.values():
        s.ips = addrs.get(s.host.lower(), [])
        if s.host and not s.ips:
            missing.append(s)
    if missing:
        # ask for the addresses we didn't get
        recs2, _ = query([(s.host, A) for s in missing][:20], 1.2)
        for r in recs2:
            if r.type == A:
                for s in missing:
                    if s.host.lower() == r.name.lower() and r.data not in s.ips:
                        s.ips.append(r.data)
    return sorted(svcs.values(), key=lambda s: (s.type, s.name.lower()))


def service_types(seconds: float = 3.0, iface_ips=None, stop=None) -> list[str]:
    recs, _ = query([("_services._dns-sd._udp.local", PTR)], seconds, iface_ips, stop)
    return sorted({str(r.data) for r in recs if r.type == PTR and r.name.lower().startswith("_services")})


def reverse_name(ip: str, timeout: float = 1.0) -> str:
    """Hostname a device announces over mDNS for its IP, asked directly."""
    rev = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    recs, _ = query([(rev, PTR)], timeout, unicast_to=ip)
    for r in recs:
        if r.type == PTR and r.name.lower() == rev:
            return str(r.data).rstrip(".")
    return ""
