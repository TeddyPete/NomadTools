"""Tiny SNMP v2c GET (sysDescr, sysName...) for identifying switches."""
from __future__ import annotations

import random
import socket

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"


def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(t: int, v: bytes) -> bytes:
    return bytes([t]) + _len(len(v)) + v


def _int(n: int) -> bytes:
    return _tlv(0x02, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def _oid(oid: str) -> bytes:
    parts = [int(x) for x in oid.split(".")]
    out = bytes([parts[0] * 40 + parts[1]])
    for p in parts[2:]:
        enc = [p & 0x7F]
        p >>= 7
        while p:
            enc.insert(0, 0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(enc)
    return _tlv(0x06, out)


def _parse(data: bytes, off: int = 0):
    t = data[off]
    ln = data[off + 1]
    off += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(data[off:off + n], "big")
        off += n
    return t, data[off:off + ln], off + ln


def get(host: str, oids: list[str], community: str = "public", timeout: float = 1.0) -> dict[str, object]:
    rid = random.randint(1, 0x7FFFFFFF)
    vbl = b"".join(_tlv(0x30, _oid(o) + b"\x05\x00") for o in oids)
    pdu = _tlv(0xA0, _int(rid) + _int(0) + _int(0) + _tlv(0x30, vbl))
    msg = _tlv(0x30, _int(1) + _tlv(0x04, community.encode()) + pdu)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(msg, (host, 161))
            data, _ = s.recvfrom(65535)
    except OSError:
        return {}
    try:
        _, body, _ = _parse(data)
        _, _, o = _parse(body)          # version
        _, _, o = _parse(body, o)       # community
        _, pdu_b, _ = _parse(body, o)
        _, _, o = _parse(pdu_b)         # request id
        _, _, o = _parse(pdu_b, o)      # error
        _, _, o = _parse(pdu_b, o)      # index
        _, vbl_b, _ = _parse(pdu_b, o)
        out, i = {}, 0
        for oid in oids:
            if i >= len(vbl_b):
                break
            _, vb, i = _parse(vbl_b, i)
            _, _, j = _parse(vb)
            t, val, _ = _parse(vb, j)
            if t == 0x04:
                out[oid] = val.decode("utf-8", "replace")
            elif t in (0x02, 0x41, 0x42, 0x43):
                out[oid] = int.from_bytes(val, "big")
        return out
    except (IndexError, ValueError):
        return {}
