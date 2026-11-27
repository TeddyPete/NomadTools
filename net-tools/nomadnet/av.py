"""AV discovery: Dante, NDI, AES67/SAP, mDNS, PTP, multicast/IGMP,
Dante health, and Find AV gear (Crestron, Extron, Q-SYS, Biamp, Shure,
Netgear AV Line) with a control-port check."""
from __future__ import annotations

import json
import re
import socket
import struct
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import capture, mdns, oui, scan, snmp, util
from .ui import DIM

DANTE_TYPES = ["_netaudio-arc._udp", "_netaudio-cmc._udp", "_netaudio-dbc._udp", "_netaudio-chan._udp"]


def _ips(iface: str = "") -> list[str]:
    if iface:
        i = util.iface(iface)
        return [i.ip] if i and i.ip else []
    return [i.ip for i in util.interfaces() if i.ip]


# ----------------------------------------------------------------- mDNS based

def dante(out, iface: str = "") -> list:
    out.dim("Asking for Dante devices (mDNS)...")
    svcs = mdns.browse(DANTE_TYPES, 4.0, _ips(iface), lambda: out.stopped)
    devs: dict[str, dict] = {}
    for s in svcs:
        d = devs.setdefault(s.name.lower(), {"name": s.name, "ip": s.ip, "txt": {}, "types": set()})
        d["txt"].update(s.txt)
        d["types"].add(s.type.split(".")[0])
        if s.ip and not d["ip"]:
            d["ip"] = s.ip
    out.replace_last(f"{len(devs)} Dante device(s)", DIM)
    for d in sorted(devs.values(), key=lambda d: d["name"].lower()):
        t = d["txt"]
        mf = t.get("mf", "")
        model = t.get("model", "")
        rate = t.get("rate", "")
        line = f"{d['name'][:28]:28} {d['ip']:15} {mf} {model}".rstrip()
        if rate:
            line += f"  {int(rate) / 1000:g} kHz" if rate.isdigit() else f"  {rate}"
        out.item(line, scan.Host(d["ip"], name=d["name"], vendor=mf))
        extras = {k: v for k, v in t.items() if k in ("router_info", "latency_ns", "enc", "en", "id", "process")}
        if extras:
            out.dim("   " + "  ".join(f"{k}={v}" for k, v in extras.items()))
    if not devs:
        out.warn("No Dante devices answered. Check you are on the Dante (primary) network.")
    return list(devs.values())


def ndi(out, iface: str = "") -> None:
    out.dim("Asking for NDI sources (mDNS _ndi._tcp)...")
    svcs = mdns.browse(["_ndi._tcp"], 4.0, _ips(iface), lambda: out.stopped)
    out.replace_last(f"{len(svcs)} NDI source(s)", DIM)
    for s in svcs:
        out.item(f"{s.name[:40]:40} {s.ip}:{s.port}", scan.Host(s.ip, name=s.name))
    if not svcs:
        out.warn("No NDI sources found. NDI discovery servers are not checked.")


def mdns_all(out, iface: str = "") -> None:
    out.dim("Listing mDNS service types...")
    types = mdns.service_types(3.0, _ips(iface), lambda: out.stopped)
    out.replace_last(f"{len(types)} service types; browsing them...", DIM)
    if not types or out.stopped:
        return
    svcs = mdns.browse(types[:40], 4.0, _ips(iface), lambda: out.stopped)
    by_type = defaultdict(list)
    for s in svcs:
        by_type[s.type].append(s)
    for t in types:
        lst = by_type.get(t, [])
        out.head(f"{t.replace('.local', '')} ({len(lst)})")
        for s in lst:
            out.item(f"  {s.name[:36]:36} {s.ip}:{s.port}", scan.Host(s.ip, name=s.name))


# ----------------------------------------------------------------- SAP / AES67

def parse_sdp(sdp: str) -> dict:
    d = {"name": "", "origin": "", "conn": "", "port": "", "fmt": "", "ptime": "", "clock": "", "channels": ""}
    for line in sdp.splitlines():
        k, _, v = line.partition("=")
        if k == "s":
            d["name"] = v.strip()
        elif k == "o":
            p = v.split()
            d["origin"] = p[-1] if p else ""
        elif k == "c":
            d["conn"] = v.split()[-1]
        elif k == "m":
            p = v.split()
            d["port"] = p[1] if len(p) > 1 else ""
        elif k == "a" and v.startswith("rtpmap:"):
            d["fmt"] = v.split(None, 1)[-1]
        elif k == "a" and v.startswith("ptime:"):
            d["ptime"] = v[6:]
        elif k == "a" and v.startswith("ts-refclk:"):
            d["clock"] = v[10:]
    return d


def sap(out, iface: str = "", seconds: str = "35") -> None:
    secs = float(seconds or 35)
    ips = _ips(iface)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    s.bind(("", 9875))
    for g in ("239.255.255.255", "224.2.127.254"):
        for ip in ips or ["0.0.0.0"]:
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(g) + socket.inet_aton(ip))
            except OSError:
                pass
    s.settimeout(0.5)
    out.dim(f"Listening for SAP/SDP (AES67, Dante AES67, RAVENNA) for {secs:.0f}s; Q stops")
    out.line("")
    sessions: dict[str, dict] = {}
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs and not out.stopped:
        out.replace_last(f"  {time.monotonic() - t0:4.0f}s  {len(sessions)} stream(s)", DIM)
        try:
            data, addr = s.recvfrom(9000)
        except (socket.timeout, OSError):
            continue
        if len(data) < 8:
            continue
        flags = data[0]
        auth_len = data[1]
        off = 4 + (16 if flags & 0x10 else 4) + auth_len * 4
        body = data[off:]
        if body.startswith(b"application/sdp\0"):
            body = body[16:]
        delete = bool(flags & 0x04)
        d = parse_sdp(body.decode("utf-8", "replace"))
        key = d["name"] + d["conn"]
        if delete:
            sessions.pop(key, None)
            continue
        if key not in sessions:
            d["from"] = addr[0]
            sessions[key] = d
            out.replace_last(f"{d['name'][:30]:30} {d['conn']}:{d['port']}  {d['fmt']}")
            out.dim(f"   from {d['origin'] or addr[0]}  ptime {d['ptime'] or '?'} ms  clock {d['clock'] or '?'}")
            out.line("")
    s.close()
    out.replace_last(f"{len(sessions)} AES67/SAP stream(s) announced", DIM)


# ----------------------------------------------------------------- PTP + multicast

class PtpWatch:
    def __init__(self):
        self.syncs = defaultdict(list)        # (ver, domain, leader id) -> [times]
        self.leader_ip = {}
        self.current = {}                     # (ver, domain) -> leader id
        self.changes = []                     # (t, ver, domain, old, new)
        self.announce = {}                    # leader id -> info
        self.v2gm = {}

    def feed(self, p: capture.Packet) -> None:
        d = p.payload
        if len(d) < 36:
            return
        ver = d[1] & 0x0F if d[0] != 0 or d[1] != 1 else 1
        if d[0] == 0 and d[1] == 1:       # PTPv1 (Dante)
            ver = 1
        if ver == 1:
            if len(d) < 40 or p.dport != 319:
                return
            control = d[32]
            if control != 0:              # Sync only
                return
            sub = d[4:20].split(b"\0")[0].decode("latin-1")
            leader = capture.mac_str(d[22:28])
            dom = sub or "_DFLT"
        elif ver == 2:
            mtype = d[0] & 0x0F
            dom = str(d[4])
            leader = d[20:28].hex()
            if mtype == 0x0B and len(d) >= 64:           # Announce
                gm = d[53:61].hex()
                self.v2gm[(dom, leader)] = {"gm": gm, "p1": d[47], "p2": d[52], "class": d[48],
                                           "steps": struct.unpack_from("!H", d, 61)[0]}
                return
            if mtype != 0 or p.dport != 319:
                return
        else:
            return
        key = (ver, dom)
        self.leader_ip[leader] = p.src
        self.syncs[(ver, dom, leader)].append(p.ts)
        old = self.current.get(key)
        if old is None:
            self.current[key] = leader
        elif old != leader:
            # a different clock sending Sync: if the old one stopped, it's a change
            last_old = self.syncs[(ver, dom, old)][-1]
            if p.ts - last_old > 2.5:
                self.changes.append((p.ts, ver, dom, old, leader))
                self.current[key] = leader

    def report(self, out) -> None:
        if not self.syncs:
            out.warn("No PTP Sync messages seen.")
            out.dim("Dante uses PTPv1, AES67 uses PTPv2 (224.0.1.129). On a switch with")
            out.dim("IGMP snooping we join that group, so it should reach us if PTP is running.")
            return
        doms = defaultdict(list)
        for (ver, dom, leader), ts in self.syncs.items():
            doms[(ver, dom)].append((leader, ts))
        for (ver, dom), leaders in sorted(doms.items()):
            label = f"PTPv{ver} {'(Dante)' if ver == 1 else '(AES67/PTPv2)'} domain {dom}"
            out.head(label)
            active = [l for l in leaders if len(l[1]) > 1]
            for leader, ts in leaders:
                ip = self.leader_ip.get(leader, "")
                name = scan.name_for_mac(leader) if ver == 1 else ""
                n = len(ts)
                gaps = [b - a for a, b in zip(ts, ts[1:])]
                med = sorted(gaps)[len(gaps) // 2] if gaps else 0
                drop = sum(1 for g in gaps if med and g > 3 * med)
                worst = max(gaps) if gaps else 0
                who = f"{leader}  {ip} {name}".rstrip()
                out.ok(f"Leader {who}") if leader == self.current.get((ver, dom)) else out.line(f"Clock  {who}")
                out.line(f"   {n} Sync, every {med * 1000:.0f} ms, worst gap {worst * 1000:.0f} ms")
                if drop:
                    out.bad(f"   {drop} sync dropout(s) (gap > 3x normal): clock errors likely")
                if ver == 2:
                    for (d2, l2), a in self.v2gm.items():
                        if d2 == dom and l2 == leader:
                            out.line(f"   GM {a['gm']} prio1 {a['p1']} prio2 {a['p2']} class {a['class']} steps {a['steps']}")
            if len(active) > 1:
                out.bad(f"More than one clock sent Sync in this domain ({len(active)}). Check for")
                out.bad("a leader election fight, or two Dante networks bridged together.")
        if self.changes:
            out.head(f"Leader changes: {len(self.changes)}")
            for t, ver, dom, old, new in self.changes:
                out.warn(f"{time.strftime('%H:%M:%S', time.localtime(t))}  v{ver} {dom}: {old} -> {new}")
        else:
            out.ok("No leader changes while watching.")


class McastWatch:
    def __init__(self, joined: set[str], own: set[str] = frozenset()):
        self.joined = joined
        self.own = set(own)
        self.groups = defaultdict(lambda: [0, 0, set()])     # group -> [pkts, bytes, sources]
        self.queriers = defaultdict(int)
        self.members = defaultdict(set)                       # group -> member ips
        self.leaves = 0
        self.t0 = None
        self.t1 = None

    def feed(self, p: capture.Packet) -> None:
        if p.src in self.own:
            return
        if self.t0 is None:
            self.t0 = p.ts
        self.t1 = p.ts
        if p.proto == 2:
            d = p.payload
            if not d:
                return
            t = d[0]
            if t == 0x11:
                self.queriers[p.src] += 1
            elif t in (0x12, 0x16) and len(d) >= 8:
                self.members[socket.inet_ntoa(d[4:8])].add(p.src)
            elif t == 0x17:
                self.leaves += 1
            elif t == 0x22 and len(d) >= 8:
                n = struct.unpack_from("!H", d, 6)[0]
                off = 8
                for _ in range(n):
                    if off + 8 > len(d):
                        break
                    rtype, aux, ns = d[off], d[off + 1], struct.unpack_from("!H", d, off + 2)[0]
                    g = socket.inet_ntoa(d[off + 4: off + 8])
                    if rtype in (2, 4, 1, 5) and not (rtype == 3 and ns == 0):
                        self.members[g].add(p.src)
                    off += 8 + ns * 4 + aux * 4
            return
        if p.dst and 224 <= int(p.dst.split(".")[0]) <= 239:
            g = self.groups[p.dst]
            g[0] += 1
            g[1] += len(p.raw)
            g[2].add(p.src)

    def report(self, out, seconds: float) -> None:
        dur = max(1e-3, (self.t1 or 0) - (self.t0 or 0)) if self.t0 else seconds
        dur = max(dur, 1.0)
        out.head("IGMP")
        if self.queriers:
            for q, n in self.queriers.items():
                out.ok(f"Querier {q} ({n} queries)")
            if len(self.queriers) > 1:
                out.warn("More than one querier seen; usually only one should be active.")
        else:
            out.warn(f"No IGMP querier heard in {seconds:.0f}s (queries are often every 60-125s).")
            out.dim("With snooping on and no querier, multicast can stop or flood after a few minutes.")
        if self.members:
            out.line(f"{len(self.members)} group(s) joined by other devices:")
            for g, m in sorted(self.members.items()):
                out.dim(f"   {g:15} by {', '.join(sorted(m)[:4])}{' ...' if len(m) > 4 else ''}")
        out.head("Multicast reaching this port")
        rows = []
        for g, (n, b, srcs) in self.groups.items():
            if g in self.joined or g.startswith("224.0.0.") or g == "239.255.255.250":
                continue
            rows.append((b * 8 / dur / 1e6, n / dur, g, srcs))
        rows.sort(reverse=True)
        total = sum(r[0] for r in rows)
        if not rows:
            out.ok("None that we did not ask for. Snooping looks OK on this port.")
            return
        audio = [r for r in rows if r[2].startswith("239.")]
        if total > 1.0:
            out.bad(f"FLOODING: {total:.1f} Mb/s of multicast we never joined ({len(rows)} groups)")
            out.bad("Turn on IGMP snooping (and a querier) on this switch/VLAN.")
        else:
            out.warn(f"{total:.2f} Mb/s of unrequested multicast in {len(rows)} group(s)")
        for mbps, pps, g, srcs in rows[:25]:
            tag = "  Dante/AES67 audio?" if g in [a[2] for a in audio] and pps > 100 else ""
            out.line(f"   {g:15} {mbps:6.2f} Mb/s {pps:6.0f} pkt/s from {', '.join(sorted(srcs)[:2])}{tag}")


def _watch(out, iface: str, seconds: float, want_ptp: bool, want_mcast: bool) -> None:
    if not capture.check(out, iface):
        return
    i = util.iface(iface)
    joined = {"224.0.1.129", "224.0.1.130", "224.0.1.131", "224.0.1.132"} if want_ptp else set()
    keep = capture.join_groups(i.ip if i else None, sorted(joined)) if joined else None
    parts = []
    if want_ptp:
        parts.append("udp port 319 or udp port 320")
    if want_mcast:
        parts.append("igmp or (ip multicast and not udp port 5353 and not udp port 1900)")
    cap = capture.Capture(iface, " or ".join(f"({x})" for x in parts), promisc=False, snaplen=200, out=out)
    out.dim(f"Watching {iface} for {seconds:.0f}s; Q stops early")
    out.line("")
    ptp, mc = PtpWatch(), McastWatch(joined, {x.ip for x in util.interfaces() if x.ip})
    t0, last = time.monotonic(), 0.0
    try:
        for p in cap.packets(seconds):
            if p.proto == 17 and p.dport in (319, 320):
                ptp.feed(p)
            if want_mcast:
                mc.feed(p)
            now = time.monotonic()
            if now - last > 1.0:
                last = now
                leaders = len({k[2] for k in ptp.syncs})
                out.replace_last(f"  {now - t0:4.0f}s  {cap.count} pkts  clocks {leaders}  groups {len(mc.groups)}", DIM)
    finally:
        cap.stop()
        if keep:
            keep.close()
    if cap.count == 0:
        capture.explain_error(out, cap)
    out.replace_last(f"Watched {time.monotonic() - t0:.0f}s, {cap.count} packets", DIM)
    if want_ptp:
        ptp.report(out)
    if want_mcast:
        mc.report(out, seconds)


def dante_health(out, iface: str = "", seconds: str = "30") -> None:
    iface = iface or util.wired_name()
    out.dim("Dante health: PTP leader, leader changes, sync dropouts, multicast flooding")
    _watch(out, iface, float(seconds or 30), True, True)


def ptp_view(out, iface: str = "", seconds: str = "15") -> None:
    _watch(out, iface or util.wired_name(), float(seconds or 15), True, False)


def multicast(out, iface: str = "", seconds: str = "30") -> None:
    _watch(out, iface or util.wired_name(), float(seconds or 30), False, True)


# ----------------------------------------------------------------- Find AV gear

AV_LINE = re.compile(r"\b(M4250|M4300|M4350|M4500|AV Line)", re.I)
PORTS = {
    "Crestron": [22, 23, 80, 443, 41794, 41795, 41796, 41797],
    "Extron": [22, 23, 80, 443, 22023],
    "Q-SYS": [22, 80, 443, 1702, 1710],
    "Biamp": [22, 23, 80, 443],
    "Shure": [80, 443, 2202, 8023],
    "Netgear": [22, 23, 80, 443],
}
PORT_NAMES = {22: "SSH", 23: "Telnet", 80: "HTTP", 443: "HTTPS", 41794: "CIP", 41795: "console",
              41796: "CIP-TLS", 41797: "console-TLS", 22023: "SIS-SSH", 1702: "ECP", 1710: "QRC",
              2202: "Shure-cmd", 8023: "Shure-tel", 161: "SNMP", 4352: "PJLink", 5000: "",
              9090: "", 52000: ""}


def crestron_discover(iface_ips: list[str], seconds: float = 3.0, stop=None, target: str = "") -> dict[str, dict]:
    """Crestron autodiscovery: a UDP broadcast to port 41794. Devices answer
    to port 41794 on the sender, so we listen on that port too."""
    pkt = b"\x14\x00\x00\x00\x01\x04\x00\x03\x00\x00" + socket.gethostname().encode()[:255].ljust(256, b"\0")
    found = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind(("", 41794))
        except OSError:
            s.bind(("", 0))
        s.settimeout(0.2)
    except OSError:
        return found
    dsts = [target] if target else ["255.255.255.255"]
    if not target:
        for ip in iface_ips:
            i = next((x for x in util.interfaces() if x.ip == ip), None)
            if i and i.network:
                dsts.append(str(i.network.broadcast_address))
    for dst in dsts:
        try:
            s.sendto(pkt, (dst, 41794))
        except OSError:
            pass
    own = {x.ip for x in util.interfaces()}
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds and not (stop and stop()):
        try:
            data, addr = s.recvfrom(2048)
        except (socket.timeout, OSError):
            continue
        if not data or data[0] != 0x15 or addr[0] in own:
            continue
        host = data[10:10 + 256].split(b"\0")[0].decode("latin-1")
        info = data[266:].split(b"\0")[0].decode("latin-1")
        model = info.split(" [")[0].strip()
        fw = re.search(r"\[(v[^ ,\]]+)", info)
        mac = re.search(r"@E-([0-9a-fA-F]{12})", info)
        found[addr[0]] = {"host": host, "model": model, "fw": fw.group(1) if fw else "",
                          "mac": ":".join(mac.group(1)[i:i + 2] for i in range(0, 12, 2)).lower() if mac else "",
                          "info": info}
    s.close()
    return found


def qsys_discover(iface_ips: list[str], seconds: float = 3.0, stop=None) -> dict[str, dict]:
    found = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        s.bind(("", 2467))
        for ip in iface_ips or ["0.0.0.0"]:
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton("224.0.23.175") + socket.inet_aton(ip))
            except OSError:
                pass
        s.settimeout(0.3)
    except OSError:
        return found
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds and not (stop and stop()):
        try:
            data, addr = s.recvfrom(9000)
        except (socket.timeout, OSError):
            continue
        txt = data.decode("utf-8", "replace")

        def tag(t):
            m = re.search(rf"<{t}>([^<]*)</{t}>", txt)
            return m.group(1) if m else ""
        ip = tag("lan_a_ip") or addr[0]
        found[ip] = {"name": tag("name"), "type": tag("type"), "platform": tag("platform"),
                     "part": tag("part_number"), "design": tag("design_name") or tag("design")}
    s.close()
    return found


def identify(h: scan.Host, extra: dict) -> dict:
    """Work out brand/model and open control ports for one host."""
    b = extra.get("brand") or h.brand
    model = extra.get("model", "")
    if b == "Audinate":
        b = ""
    if not b:
        return {}
    ports = util.ports_open(h.ip, PORTS.get(b, [22, 23, 80, 443]), 0.8)
    if b == "Crestron" and not model:
        d = crestron_discover([""], 1.5, target=h.ip).get(h.ip)
        if d:
            model = f"{d['model']} {d['fw']}".strip()
            h.name = h.name or d["host"]
    if b == "Extron" and 23 in ports and not model:
        ban = util.banner(h.ip, 23, 2.0)
        m = re.search(r"Extron Electronics,\s*([^,]+),\s*(V[\d.]+)", ban)
        if m:
            model = f"{m.group(1).strip()} {m.group(2)}"
    elif b == "Biamp" and 23 in ports and not model:
        ban = util.banner(h.ip, 23, 2.0)
        if "Tesira" in ban:
            model = "Tesira (TTP on Telnet)"
    elif b == "Shure" and 2202 in ports and not model:
        rep = util.banner(h.ip, 2202, 1.5, b"< GET MODEL >\r\n")
        m = re.search(r"MODEL \{?\s*([^}>]+?)\s*\}? >", rep)
        if m:
            model = m.group(1).strip()
    elif b == "Q-SYS" and not model and 1710 in ports:
        model = qrc_platform(h.ip)
    elif b == "Netgear" and AV_LINE.search(model or ""):
        pass
    elif b == "Netgear":
        r = snmp.get(h.ip, [snmp.SYS_DESCR])
        descr = str(r.get(snmp.SYS_DESCR, ""))
        if not descr and 80 in ports:
            descr = util.http_title(h.ip, 80)
        if not descr and 443 in ports:
            descr = ""
        m = AV_LINE.search(descr)
        if not m:
            return {"brand": "Netgear", "hidden": True, "model": descr[:40]}
        model = descr.split(",")[0].strip()[:40] or m.group(1)
    return {"brand": b, "model": model, "ports": ports}


def qrc_platform(ip: str) -> str:
    try:
        with socket.create_connection((ip, 1710), timeout=1.5) as s:
            s.settimeout(1.5)
            s.sendall(json.dumps({"jsonrpc": "2.0", "method": "StatusGet", "id": 1, "params": 0}).encode() + b"\0")
            data = b""
            end = time.monotonic() + 2
            while time.monotonic() < end and b'"id":1' not in data.replace(b" ", b""):
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            for part in data.split(b"\0"):
                try:
                    j = json.loads(part)
                except ValueError:
                    continue
                if j.get("id") == 1 and "result" in j:
                    return j["result"].get("Platform", "")
    except OSError:
        pass
    return ""


def find_av(out, iface: str = "") -> None:
    i = util.best_iface(iface or None)
    if not i or not i.ip:
        out.bad("No interface with an IP address.")
        return
    ips = [i.ip]
    out.dim(f"Scanning {i.network} on {i.name}, plus Crestron/Q-SYS/Dante discovery...")
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_scan = ex.submit(scan.merged_scan, i)
        f_cr = ex.submit(crestron_discover, ips, 3.0, lambda: out.stopped)
        f_q = ex.submit(qsys_discover, ips, 3.5, lambda: out.stopped)
        f_d = ex.submit(mdns.browse, ["_netaudio-arc._udp", "_http._tcp", "_telnet._tcp", "_ssh._tcp"], 3.0,
                        ips, lambda: out.stopped)
        hosts = f_scan.result()
        cr, qs, dsv = f_cr.result(), f_q.result(), f_d.result()
    if out.stopped:
        return
    by_ip = {h.ip: h for h in hosts}
    extra: dict[str, dict] = defaultdict(dict)
    for ip, d in cr.items():
        extra[ip].update(brand="Crestron", model=f"{d['model']} {d['fw']}".strip(), name=d["host"])
        by_ip.setdefault(ip, scan.Host(ip, d["mac"], "Crestron Electronics"))
    for ip, d in qs.items():
        extra[ip].update(brand="Q-SYS", model=d["platform"] or d["type"], name=d["name"])
        by_ip.setdefault(ip, scan.Host(ip, vendor="QSC"))
    for s in dsv:
        m = AV_LINE.search(s.name)
        if m and s.ip:
            extra[s.ip].update(brand="Netgear", model=s.name.split(".")[0])
            by_ip.setdefault(s.ip, scan.Host(s.ip, vendor="NETGEAR"))
            continue
        if not s.type.startswith("_netaudio"):
            continue
        mf = s.txt.get("mf", "")
        b = oui.brand(mf)
        if b in ("Shure", "Biamp", "Q-SYS", "Extron", "Crestron") and s.ip:
            extra[s.ip].setdefault("brand", b)
            extra[s.ip].setdefault("model", s.txt.get("model", ""))
            extra[s.ip].setdefault("name", s.name)
            by_ip.setdefault(s.ip, scan.Host(s.ip, vendor=mf))
    scan.remember(by_ip.values())
    cands = [h for h in by_ip.values() if h.brand in PORTS or extra.get(h.ip, {}).get("brand")]
    out.replace_last(f"{len(by_ip)} devices on the subnet; checking {len(cands)} AV candidates...", DIM)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda h: (h, identify(h, extra.get(h.ip, {}))), cands))
    shown = hidden = 0
    order = ["Crestron", "Extron", "Q-SYS", "Biamp", "Shure", "Netgear"]
    results.sort(key=lambda r: (order.index(r[1].get("brand")) if r[1].get("brand") in order else 9,
                                scan.sort_ip(r[0])))
    cur = None
    for h, r in results:
        if not r:
            continue
        if r.get("hidden"):
            hidden += 1
            continue
        b = r["brand"]
        if b != cur:
            out.head("Netgear AV Line" if b == "Netgear" else b)
            cur = b
        name = extra.get(h.ip, {}).get("name") or h.name
        h.name = name or h.name
        out.item(f"{h.ip:15} {name}\n  {(r.get('model') or '?')[:28]}", ("dev", b, h))
        pn = [f"{p} {PORT_NAMES.get(p, '')}".strip() for p in r["ports"]]
        out.dim(f"   {h.mac}  ports: {', '.join(pn) or 'none open'}")
        shown += 1
    if shown:
        out.dim(f"{shown} AV device(s). Enter on one = info pull, ports, terminal")
    if not shown:
        out.warn("No Crestron, Extron, Q-SYS, Biamp, Shure or Netgear AV Line gear found.")
    if hidden:
        out.dim(f"({hidden} other Netgear device(s) not shown: not AV Line, or SNMP/web closed)")


def port_check(out, ip: str, extra_ports: str = "") -> None:
    ports = sorted({p for lst in PORTS.values() for p in lst} | {4352, 161, 5000, 9090, 8080, 52000, 3389, 5900})
    for p in re.findall(r"\d+", extra_ports or ""):
        ports.append(int(p))
    ports = sorted(set(ports))
    out.dim(f"Checking {len(ports)} control ports on {ip}...")
    openp = util.ports_open(ip, ports, 1.0)
    out.replace_last(f"{len(openp)} of {len(ports)} TCP ports open on {ip}", DIM)
    for p in ports:
        if p == 161:
            r = snmp.get(ip, [snmp.SYS_DESCR, snmp.SYS_NAME])
            if r:
                out.ok(f"  161 SNMP (public): {str(r.get(snmp.SYS_DESCR, ''))[:60]}")
            else:
                out.dim("  161 SNMP: no answer to 'public'")
            continue
        name = PORT_NAMES.get(p, "")
        if p in openp:
            out.ok(f"  {p:5} open    {name}")
        else:
            out.dim(f"  {p:5} closed  {name}")
