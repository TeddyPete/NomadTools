"""Network checks: DHCP rogue servers, IP conflicts, LLDP/CDP (switch,
port, VLAN) and link/cable errors."""
from __future__ import annotations

import os
import random
import re
import socket
import struct
import threading
import time

from . import capture, oui, scan, util
from .ui import DIM


# ------------------------------------------------------------------ DHCP

def _dhcp_discover(mac: str, xid: int) -> bytes:
    chaddr = bytes.fromhex(mac.replace(":", "")) + b"\0" * 10
    pkt = struct.pack("!BBBBIHH4s4s4s4s16s64s128s", 1, 1, 6, 0, xid, 0, 0x8000, b"\0" * 4, b"\0" * 4,
                      b"\0" * 4, b"\0" * 4, chaddr, b"\0" * 64, b"\0" * 128)
    pkt += b"\x63\x82\x53\x63"                       # magic cookie
    pkt += b"\x35\x01\x01"                           # DHCPDISCOVER
    pkt += b"\x37\x04\x01\x03\x06\x33"               # ask for mask, router, DNS, lease
    pkt += b"\x0c" + bytes([len(socket.gethostname()[:30])]) + socket.gethostname()[:30].encode()
    pkt += b"\xff"
    return pkt


def _dhcp_opts(d: bytes) -> dict[int, bytes]:
    opts = {}
    i = 240
    while i < len(d):
        t = d[i]
        if t == 255:
            break
        if t == 0:
            i += 1
            continue
        if i + 1 >= len(d):
            break
        ln = d[i + 1]
        opts[t] = d[i + 2:i + 2 + ln]
        i += 2 + ln
    return opts


def dhcp(out, iface: str = "", seconds: str = "6") -> None:
    iface = iface or util.wired_name()
    if not capture.check(out, iface):
        return
    mac = util.mac_of(iface)
    xid = random.randint(1, 0xFFFFFFFF)
    cap = capture.Capture(iface, "udp port 67 or udp port 68", promisc=False, snaplen=1500, out=out)
    time.sleep(0.8)  # let tcpdump start
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    pkt = _dhcp_discover(mac, xid)
    idx = util.ifindex(iface)
    sent = False
    for _ in range(2):
        try:
            # send out of the chosen interface (IP_PKTINFO picks it without root)
            anc = [(socket.IPPROTO_IP, socket.IP_PKTINFO, struct.pack("I4s4s", idx, b"\0" * 4, b"\0" * 4))]
            s.sendmsg([pkt], anc, 0, ("255.255.255.255", 67))
            sent = True
        except OSError as e:
            out.warn(f"Send on {iface} failed ({e}); trying the default route")
            try:
                s.sendto(pkt, ("255.255.255.255", 67))
                sent = True
            except OSError as e2:
                out.bad(f"Can't send DHCP discover: {e2}")
        time.sleep(1.0)
    s.close()
    out.dim(f"Sent DHCP DISCOVER on {iface} (MAC {mac}); listening {seconds}s for offers...")
    servers: dict[str, dict] = {}
    for p in cap.packets(float(seconds or 6)):
        d = p.payload
        if p.sport != 67 or len(d) < 240 or d[0] != 2:
            continue
        o = _dhcp_opts(d)
        mtype = o.get(53, b"\0")[0]
        sid = socket.inet_ntoa(o[54]) if len(o.get(54, b"")) == 4 else p.src
        e = servers.setdefault(sid, {"mac": p.src_mac, "offers": 0, "ours": False, "types": set()})
        e["types"].add({2: "OFFER", 5: "ACK", 6: "NAK"}.get(mtype, str(mtype)))
        if struct.unpack_from("!I", d, 4)[0] == xid:
            e["ours"] = True
            e["offers"] += 1
            e["yiaddr"] = socket.inet_ntoa(d[16:20])
            if len(o.get(1, b"")) == 4:
                e["mask"] = socket.inet_ntoa(o[1])
            if len(o.get(3, b"")) >= 4:
                e["router"] = socket.inet_ntoa(o[3][:4])
            if o.get(6):
                e["dns"] = ", ".join(socket.inet_ntoa(o[6][i:i + 4]) for i in range(0, len(o[6]) - 3, 4))
            if len(o.get(51, b"")) == 4:
                e["lease"] = struct.unpack("!I", o[51])[0]
    cap.stop()
    if cap.count == 0 and cap.error:
        capture.explain_error(out, cap)
    if not servers:
        out.warn("No DHCP server answered on this network." if sent else "Nothing sent.")
        return
    out.head(f"DHCP servers heard: {len(servers)}")
    for sid, e in servers.items():
        v = oui.vendor(e["mac"])
        out.ok(f"Server {sid}  {e['mac']} {v}")
        if e.get("yiaddr"):
            out.line(f"   offered {e['yiaddr']} / {e.get('mask', '?')}  gw {e.get('router', '?')}")
            out.line(f"   DNS {e.get('dns', '?')}  lease {e.get('lease', 0) // 60} min")
        out.dim(f"   messages: {', '.join(sorted(e['types']))}")
    if len(servers) > 1:
        out.bad(f"ROGUE DHCP? {len(servers)} servers answered. Normally only one should.")
    else:
        out.ok("One DHCP server: no rogue seen.")


# ------------------------------------------------------------------ IP conflict

def conflict(out, iface: str = "", target: str = "") -> None:
    i = util.best_iface(iface or None)
    if not i:
        out.bad("No interface")
        return
    ips = [target] if target else ([i.ip] if i.ip else [])
    gw = util.default_gateway(i.name)
    if gw and not target:
        ips.append(gw)
    if not ips:
        out.bad(f"{i.name} has no IP to check")
        return
    if not util.have("arping"):
        out.bad("arping is not installed")
    for ip in ips:
        own = ip == i.ip
        out.head(f"{ip}{' (this device)' if own else ' (gateway)' if ip == gw else ''}")
        args = ["arping", "-I", i.name, "-c", "3", "-w", "4"]
        args += ["-D", ip] if own else [ip]
        r = util.run(args, 8)
        macs = sorted(set(m.lower() for m in re.findall(r"\[([0-9A-Fa-f:]{17})\]", r)))
        if "Operation not permitted" in r or "permission" in r.lower():
            out.warn("arping lacks rights; reinstall the package to set them.")
            continue
        if own:
            if macs:
                out.bad(f"CONFLICT: {', '.join(macs)} also use {ip}")
            else:
                out.ok("No other device answers for this address.")
        elif len(macs) > 1:
            out.bad(f"CONFLICT: {len(macs)} devices answer for {ip}:")
            for m in macs:
                out.bad(f"   {m} {oui.vendor(m)}")
        elif macs:
            out.ok(f"One device: {macs[0]} {oui.vendor(macs[0])}")
        else:
            out.warn("No answer")
    if not target:
        out.head("Duplicate IPs on the subnet (ARP scan)")
        hosts = scan.arp_scan(i.name, out)
        if hosts is None:
            out.dim("arp-scan not available; skipped")
        else:
            dups = [h for h in hosts if h.dup]
            if dups:
                for h in dups:
                    out.bad(f"   {h.ip} answered by more than one MAC")
            else:
                out.ok(f"No duplicates among {len(hosts)} devices")


# ------------------------------------------------------------------ LLDP / CDP

LLDP_CAPS = ["other", "repeater", "bridge", "WLAN AP", "router", "phone", "DOCSIS", "station", "C-VLAN", "S-VLAN", "TPMR"]


def parse_lldp(d: bytes) -> list[tuple[str, str]]:
    out = []
    i = 0
    while i + 2 <= len(d):
        hdr = struct.unpack_from("!H", d, i)[0]
        t, ln = hdr >> 9, hdr & 0x1FF
        v = d[i + 2:i + 2 + ln]
        i += 2 + ln
        if t == 0:
            break
        if t == 1:
            out.append(("Chassis", _lldp_id(v)))
        elif t == 2:
            out.append(("Port ID", _lldp_id(v)))
        elif t == 3:
            out.append(("TTL", f"{struct.unpack('!H', v)[0]} s" if len(v) == 2 else ""))
        elif t == 4:
            out.append(("Port", v.decode("utf-8", "replace")))
        elif t == 5:
            out.append(("Switch", v.decode("utf-8", "replace")))
        elif t == 6:
            out.append(("System", v.decode("utf-8", "replace").replace("\r", " ").replace("\n", " ")))
        elif t == 7 and len(v) >= 4:
            caps, en = struct.unpack("!HH", v[:4])
            out.append(("Caps", ", ".join(n for b, n in enumerate(LLDP_CAPS) if en >> b & 1)))
        elif t == 8 and len(v) >= 6 and v[1] == 1:
            out.append(("Mgmt IP", socket.inet_ntoa(v[2:6])))
        elif t == 127 and len(v) >= 4:
            o, sub = v[:3], v[3]
            if o == b"\x00\x80\xc2" and sub == 1 and len(v) >= 6:
                out.append(("VLAN (PVID)", str(struct.unpack("!H", v[4:6])[0])))
            elif o == b"\x00\x80\xc2" and sub == 3 and len(v) >= 7:
                vid = struct.unpack("!H", v[4:6])[0]
                out.append(("VLAN name", f"{vid} {v[7:7 + v[6]].decode('utf-8', 'replace')}"))
            elif o == b"\x00\x12\x0f" and sub == 1 and len(v) >= 9:
                mau = struct.unpack("!H", v[7:9])[0]
                speeds = {16: "100 Full", 15: "100 Half", 30: "1000 Full", 29: "1000 Half", 10: "10 Full", 11: "10 Half"}
                out.append(("Autoneg", ("on" if v[4] & 2 else "off") + f", link {speeds.get(mau, f'MAU {mau}')}"))
            elif o == b"\x00\x12\x0f" and sub == 2 and len(v) >= 7:
                out.append(("PoE", f"{'supported' if v[4] & 2 else 'not supported'}, {'enabled' if v[4] & 4 else 'disabled'}, class {v[6] - 1 if v[6] else '?'}"))
            elif o == b"\x00\x12\xbb" and sub == 2 and len(v) >= 7:
                app = v[4]
                pol = struct.unpack("!I", b"\0" + v[5:8])[0] if len(v) >= 8 else 0
                vid = (pol >> 9) & 0xFFF
                out.append(("LLDP-MED policy", f"app {app} VLAN {vid}"))
    return out


def _lldp_id(v: bytes) -> str:
    if not v:
        return ""
    sub, body = v[0], v[1:]
    if sub in (4,) and len(body) == 6:
        return capture.mac_str(body)
    if sub == 5 and len(body) >= 5 and body[0] == 1:
        return socket.inet_ntoa(body[1:5])
    if sub == 3 and len(body) == 6:
        return capture.mac_str(body)
    return body.decode("utf-8", "replace")


def parse_cdp(d: bytes) -> list[tuple[str, str]]:
    # d = after LLC/SNAP header
    out = []
    i = 4
    names = {1: "Device ID", 3: "Port", 5: "Software", 6: "Platform", 10: "Native VLAN", 11: "Duplex",
             14: "Voice VLAN", 0x16: "Mgmt IP"}
    while i + 4 <= len(d):
        t, ln = struct.unpack_from("!HH", d, i)
        if ln < 4:
            break
        v = d[i + 4:i + ln]
        i += ln
        if t in (1, 3, 6):
            out.append((names[t], v.decode("utf-8", "replace")))
        elif t == 5:
            out.append(("Software", v.decode("utf-8", "replace").splitlines()[0][:80] if v else ""))
        elif t == 10 and len(v) >= 2:
            out.append(("Native VLAN", str(struct.unpack("!H", v[:2])[0])))
        elif t == 11 and v:
            out.append(("Duplex", "full" if v[0] else "half"))
        elif t == 14 and len(v) >= 3:
            out.append(("Voice VLAN", str(struct.unpack("!H", v[1:3])[0])))
        elif t in (2, 0x16) and len(v) >= 13:
            # first address only
            if v[4] == 1 and v[5] == 1 and v[6] == 0xCC:
                out.append(("Mgmt IP" if t == 0x16 else "Address", socket.inet_ntoa(v[9:13])))
    return out


def has_link(iface: str) -> bool:
    try:
        return open(f"/sys/class/net/{iface}/carrier").read().strip() == "1"
    except OSError:
        return False


def lldp(out, iface: str = "", seconds: str = "65") -> None:
    iface = iface or util.wired_name()
    if not capture.check(out, iface):
        return
    if not has_link(iface):
        out.bad(f"{iface}: no link. Plug the Ethernet port into the switch.")
        return
    secs = float(seconds or 65)
    cap = capture.Capture(iface, "ether proto 0x88cc or ether dst 01:00:0c:cc:cc:cc", promisc=False,
                          snaplen=2000, out=out)
    out.dim(f"Listening on {iface} for LLDP (every ~30s) and CDP (every ~60s). Q stops.")
    out.line("")
    got = set()
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs and not out.stopped:
        p = cap.next(1.0)
        if not got:
            out.replace_last(f"  {time.monotonic() - t0:3.0f}s / {secs:.0f}s", DIM)
        if p is None:
            if cap.proc.poll() is not None:
                break
            continue
        if p.ethertype == 0x88CC and "lldp" not in got:
            got.add("lldp")
            out.replace_last(f"LLDP from {p.src_mac} ({oui.vendor(p.src_mac)})", DIM)
            out.head("LLDP")
            for k, v in parse_lldp(p.l3):
                out.ok(f"{k:12} {v}") if k in ("Switch", "Port", "VLAN (PVID)") else out.line(f"{k:12} {v}")
        elif p.dst_mac == "01:00:0c:cc:cc:cc" and "cdp" not in got:
            raw = p.raw[14:]
            if raw[:2] == b"\xaa\xaa" and raw[6:8] == b"\x20\x00":
                got.add("cdp")
                out.head(f"CDP from {p.src_mac}")
                for k, v in parse_cdp(raw[8:]):
                    out.ok(f"{k:12} {v}") if k in ("Device ID", "Port", "Native VLAN") else out.line(f"{k:12} {v}")
        if got == {"lldp", "cdp"}:
            break
    cap.stop()
    if not got:
        capture.explain_error(out, cap)
        out.warn("No LLDP or CDP heard. The switch may have them turned off, or this is")
        out.warn("an unmanaged switch.")


# ------------------------------------------------------------------ link / cable

STAT_KEYS = ["rx_errors", "tx_errors", "rx_crc_errors", "rx_frame_errors", "rx_length_errors",
             "rx_over_errors", "rx_missed_errors", "rx_dropped", "tx_dropped", "collisions", "tx_carrier_errors"]


def _stats(iface: str) -> dict[str, int]:
    d = {}
    for k in STAT_KEYS:
        try:
            d[k] = int(open(f"/sys/class/net/{iface}/statistics/{k}").read())
        except (OSError, ValueError):
            pass
    try:
        d["carrier_changes"] = int(open(f"/sys/class/net/{iface}/carrier_changes").read())
    except (OSError, ValueError):
        pass
    return d


def link(out, iface: str = "", seconds: str = "15") -> None:
    iface = iface or util.wired_name()
    base = f"/sys/class/net/{iface}"
    if not os.path.exists(base):
        out.bad(f"{iface} not found")
        return

    def rd(n):
        try:
            return open(f"{base}/{n}").read().strip()
        except OSError:
            return ""
    carrier = rd("carrier") == "1"
    out.head(f"{iface} link")
    if not carrier:
        out.bad("No link: cable unplugged, broken, or the far port is off.")
    else:
        sp, dup = rd("speed"), rd("duplex")
        (out.ok if dup == "full" else out.bad)(f"Up at {sp} Mb/s, {dup} duplex")
        if dup == "half":
            out.bad("Half duplex: likely a speed/duplex mismatch (one side forced).")
        if sp in ("10",):
            out.warn("10 Mb/s: check the cable or the far port setting.")
    if util.have("ethtool"):
        e = util.run([util.which("ethtool"), iface])
        an = re.search(r"Auto-negotiation: (\w+)", e)
        adv = re.search(r"Advertised link modes:\s+(.+?)\n\s+Advertised pause", e, re.S)
        lp = re.search(r"Link partner advertised link modes:\s+(.+?)\n\s+Link partner", e, re.S)
        if an:
            out.line(f"Auto-negotiation {an.group(1)}")
        if lp:
            out.line("Far end offers: " + " ".join(lp.group(1).split()))
        mdix = re.search(r"MDI-X: (.+)", e)
        if mdix:
            out.line(f"MDI-X {mdix.group(1)}")
        ct = util.run([util.which("ethtool"), "--cable-test", iface], 20)
        if "Pair" in ct or "pair" in ct:
            out.head("Cable test")
            for l in ct.splitlines():
                if "Pair" in l or "pair" in l:
                    (out.ok if "OK" in l else out.bad)(l.strip())
        elif ct and "not supported" not in ct.lower():
            out.dim("Cable test: " + ct.strip().splitlines()[-1][:70])
        else:
            out.dim("Cable test (TDR): not supported by this Ethernet chip")
    out.head(f"Error counters over {seconds}s")
    a = _stats(iface)
    nonzero = {k: v for k, v in a.items() if v}
    out.line("Since boot: " + (", ".join(f"{k} {v}" for k, v in nonzero.items()) or "all zero"))
    gw = util.default_gateway(iface)
    loss = None
    if carrier and gw:
        out.dim(f"Pinging gateway {gw} while counting...")
        r = util.run(["ping", "-I", iface, "-c", str(int(float(seconds or 15) * 4)), "-i", "0.25", "-W", "1", gw],
                     float(seconds or 15) + 10)
        m = re.search(r"([\d.]+)% packet loss", r)
        loss = float(m.group(1)) if m else None
        rt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", r)
        if rt:
            out.line(f"Gateway ping avg {rt.group(2)} ms, max {rt.group(3)} ms, loss {loss}%")
    else:
        out.sleep(float(seconds or 15))
    b = _stats(iface)
    delta = {k: b.get(k, 0) - a.get(k, 0) for k in b}
    bad = {k: v for k, v in delta.items() if v > 0}
    if bad:
        for k, v in bad.items():
            out.bad(f"   +{v} {k}")
        if bad.get("rx_crc_errors") or bad.get("rx_frame_errors"):
            out.bad("CRC/frame errors: bad cable, bad termination or interference.")
        if bad.get("carrier_changes"):
            out.bad("Link dropped while testing: loose connector or failing cable.")
    else:
        out.ok("No new errors while testing.")
    if loss:
        out.bad(f"{loss}% ping loss to the gateway.")
