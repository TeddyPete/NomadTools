"""Control-protocol sniffer/decoder and pcap capture.

Plug the built-in Ethernet into a switch mirror (SPAN) port of the
controller's port. Inline bridging is not supported (deferred)."""
from __future__ import annotations

import json
import os
import struct
import time
from collections import Counter

from . import capture, reports, util
from .ui import DIM, INFO, OK, WARN

PROTO_PORTS = {41794: "CIP", 41796: "CIP-TLS", 41795: "Crestron console", 1710: "Q-SYS QRC",
               1702: "Q-SYS ECP", 23: "Telnet/SIS", 22023: "Extron SSH", 4352: "PJLink"}
BPF = ("tcp port 41794 or tcp port 41795 or tcp port 41796 or tcp port 1710 or tcp port 1702 "
       "or tcp port 23 or tcp port 4352 or udp port 4352")

PJ_CMDS = {"POWR": "power", "INPT": "input", "AVMT": "AV mute", "ERST": "errors", "LAMP": "lamp hours",
           "INST": "inputs", "NAME": "name", "INF1": "maker", "INF2": "model", "INFO": "info",
           "CLSS": "class", "SNUM": "serial", "SVER": "sw ver", "FILT": "filter hrs", "RLMP": "lamp model"}
PJ_POWER = {"0": "off", "1": "on", "2": "cooling", "3": "warming"}
PJ_ERR = {"ERR1": "undefined cmd", "ERR2": "bad parameter", "ERR3": "unavailable now", "ERR4": "projector failure",
          "ERRA": "auth error"}


def esc(b: bytes) -> str:
    out = []
    for x in b:
        if x == 0x1B:
            out.append("{Esc}")
        elif x == 13:
            out.append("{CR}")
        elif x == 10:
            out.append("{LF}")
        elif 32 <= x < 127:
            out.append(chr(x))
        else:
            out.append(f"{{{x:02X}}}")
    return "".join(out)


def decode_cip(d: bytes) -> list[str]:
    out = []
    i = 0
    names = {0x01: "connect req", 0x02: "connect resp", 0x03: "disconnect", 0x04: "disconnect resp",
             0x05: "data", 0x0A: "connect req (ipid)", 0x0D: "heartbeat", 0x0E: "heartbeat resp",
             0x0F: "registration", 0x12: "serial data"}
    while i + 3 <= len(d):
        t = d[i]
        ln = struct.unpack_from("!H", d, i + 1)[0]
        body = d[i + 3: i + 3 + ln]
        i += 3 + ln
        if t == 0x05 and len(body) >= 4:
            sub = body[3] if len(body) > 3 else 0
            pl = body[4:]
            if sub == 0x00 and len(pl) >= 2:
                join = (pl[0] | ((pl[1] & 0x7F) << 8)) + 1
                val = 0 if pl[1] & 0x80 else 1
                out.append(f"digital join {join} = {val}")
            elif sub == 0x14 and len(pl) >= 4:
                join = struct.unpack_from("!H", pl)[0] + 1
                val = struct.unpack_from("!H", pl, 2)[0]
                out.append(f"analog join {join} = {val}")
            elif sub in (0x12, 0x15) and len(pl) >= 3:
                join = struct.unpack_from("!H", pl)[0] + 1
                out.append(f"serial join {join} = {esc(pl[3:])[:60]!s}")
            elif sub == 0x03:
                out.append("update request")
            else:
                out.append(f"data sub {sub:02X} {pl[:12].hex(' ')}")
        else:
            out.append(names.get(t, f"type {t:02X}") + (f" {body[:8].hex(' ')}" if t not in (0x0D, 0x0E) else ""))
    return out


def decode_qrc(d: bytes) -> list[str]:
    out = []
    for part in d.split(b"\0"):
        if not part.strip():
            continue
        try:
            j = json.loads(part)
        except ValueError:
            out.append(esc(part[:80]))
            continue
        if "method" in j:
            p = j.get("params")
            ps = json.dumps(p, separators=(",", ":"))[:80] if p not in (None, 0) else ""
            if j["method"] == "Logon":
                ps = "(credentials hidden)"
            out.append(f"{j['method']} {ps}")
        elif "result" in j:
            out.append(f"result id {j.get('id')}: {json.dumps(j['result'], separators=(',', ':'))[:80]}")
        elif "error" in j:
            out.append(f"ERROR id {j.get('id')}: {j['error']}")
    return out


def decode_pjlink(d: bytes) -> list[str]:
    out = []
    for line in d.replace(b"\n", b"\r").split(b"\r"):
        s = line.decode("latin-1", "replace").strip()
        if not s:
            continue
        if s.startswith("PJLINK"):
            out.append("auth " + ("off" if s.endswith(" 0") else "on (challenge)"))
            continue
        if s.startswith("%") and len(s) >= 7:
            cls, cmd, rest = s[1], s[2:6], s[7:]
            sep = s[6]
            what = PJ_CMDS.get(cmd, cmd)
            if sep == " ":
                val = "?" if rest == "?" else rest
                if cmd == "POWR" and rest in PJ_POWER:
                    val = PJ_POWER[rest]
                out.append(f"class{cls} {what} {'query' if rest == '?' else 'set ' + val}")
            elif sep == "=":
                val = PJ_ERR.get(rest, rest)
                if cmd == "POWR" and rest in PJ_POWER:
                    val = PJ_POWER[rest]
                out.append(f"class{cls} {what} -> {val}")
            else:
                out.append(s)
        else:
            out.append(esc(line))
    return out


def decode(p: capture.Packet) -> tuple[str, list[str]]:
    port = p.dport if p.dport in PROTO_PORTS else p.sport
    name = PROTO_PORTS.get(port, str(port))
    d = p.payload
    if port in (41794,):
        return name, decode_cip(d)
    if port == 1710:
        return name, decode_qrc(d)
    if port == 4352:
        return name, decode_pjlink(d)
    if port in (41796, 22023):
        return name, ["(encrypted)"]
    # Crestron console, ECP, Telnet/Extron SIS: text
    txt = util.strip_telnet(d)
    return name, [esc(txt)[:160]] if txt else []


def sniffer(out, iface: str = "", extra: str = "") -> None:
    iface = iface or util.wired_name()
    if not capture.check(out, iface):
        return
    bpf = BPF
    for port in [x for x in extra.replace(",", " ").split() if x.isdigit()]:
        bpf += f" or port {port}"
        PROTO_PORTS.setdefault(int(port), f"port {port}")
    cap = capture.Capture(iface, bpf, promisc=True, snaplen=4096, out=out)
    out.dim(f"Sniffing control traffic on {iface} (promiscuous). Use a mirror port. X stops.")
    out.dim("Crestron CIP/console, Q-SYS QRC/ECP, Extron SIS/Telnet, PJLink")
    seen = Counter()
    try:
        while not out.stopped:
            p = cap.next(1.0)
            if p is None:
                if cap.proc.poll() is not None:
                    break
                continue
            if not p.payload:
                continue
            name, lines = decode(p)
            seen[name] += 1
            arrow = f"{p.src}>{p.dst}"
            for l in lines[:6]:
                color = INFO if p.dport in PROTO_PORTS else OK
                out.line(f"{time.strftime('%H:%M:%S')} {name[:8]:8} {arrow} {l}", color)
    finally:
        cap.stop()
    if cap.count == 0:
        capture.explain_error(out, cap)
        out.dim("No control traffic seen. Is this port mirrored from the controller's port?")
    out.dim("Packets by protocol: " + ", ".join(f"{k} {v}" for k, v in seen.items()))


def pcap(out, cfg, iface: str = "", bpf: str = "", seconds: str = "", max_mb: str = "100") -> None:
    iface = iface or util.wired_name()
    if not capture.check(out, iface):
        return
    d = reports.site_dir(cfg)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{time.strftime('%Y%m%d-%H%M%S')}-capture-{iface}.pcap")
    limit = float(max_mb or 100) * 1e6
    dur = float(seconds) if seconds else 1e9
    with open(path, "wb") as f:
        cap = capture.Capture(iface, bpf, promisc=True, snaplen=65535, out=out, raw_sink=f)
        out.dim(f"Capturing on {iface} (promiscuous){' filter: ' + bpf if bpf else ''}. X stops.")
        out.line(f"File: {path}")
        out.line("")
        protos = Counter()
        t0 = time.monotonic()
        last = 0
        try:
            while not out.stopped and time.monotonic() - t0 < dur:
                p = cap.next(1.0)
                if p is not None:
                    if p.proto == 6:
                        protos[f"tcp/{min(p.sport, p.dport)}"] += 1
                    elif p.proto == 17:
                        protos[f"udp/{min(p.sport, p.dport)}"] += 1
                    elif p.ethertype == 0x0806:
                        protos["arp"] += 1
                    elif p.proto == 2:
                        protos["igmp"] += 1
                    else:
                        protos[f"eth {p.ethertype:04x}"] += 1
                if cap.bytes > limit:
                    out.warn("Size limit reached")
                    break
                if time.monotonic() - last > 1:
                    last = time.monotonic()
                    out.replace_last(f"  {time.monotonic() - t0:5.0f}s  {cap.count} packets  {cap.bytes / 1e6:.1f} MB", DIM)
                if p is None and cap.proc.poll() is not None:
                    break
        finally:
            cap.stop()
    if cap.count == 0:
        capture.explain_error(out, cap)
    out.ok(f"Saved {cap.count} packets ({os.path.getsize(path) / 1e6:.1f} MB) to")
    out.line(path)
    out.head("Top protocols")
    for k, v in protos.most_common(12):
        out.line(f"  {k:12} {v}")
    out.dim("Open the .pcap in Wireshark (copy it off from the Pi desktop or with scp).")
