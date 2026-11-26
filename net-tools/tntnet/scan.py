"""IP scan: who is on the subnet, with MAC maker and names."""
from __future__ import annotations

import ipaddress
import random
import re
import socket
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import mdns, oui, util


@dataclass
class Host:
    ip: str
    mac: str = ""
    vendor: str = ""
    name: str = ""
    dup: bool = False

    @property
    def brand(self) -> str:
        return oui.brand(self.vendor)


# every scan result lands here so other tools can match MACs to names
KNOWN: dict[str, Host] = {}


def remember(hosts) -> None:
    for h in hosts:
        old = KNOWN.get(h.ip)
        if old and not h.name:
            h.name = old.name
        KNOWN[h.ip] = h


def name_for_mac(mac: str) -> str:
    mac = mac.lower()
    for h in KNOWN.values():
        if h.mac.lower() == mac:
            return h.name or h.ip
    return ""


def ip_for_mac(mac: str) -> str:
    mac = mac.lower()
    for h in KNOWN.values():
        if h.mac.lower() == mac:
            return h.ip
    return ""


def arp_scan(iface: str, out=None) -> list[Host] | None:
    """Run arp-scan; None if it isn't installed or not permitted."""
    if not util.have("arp-scan"):
        return None
    cmd = [util.which("arp-scan"), "-I", iface, "--localnet", "--plain", "--retry=2", "--ignoredups"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0 and not p.stdout.strip():
        if out:
            out.dim("arp-scan: " + (p.stderr.strip().splitlines() or ["failed"])[-1][:120])
        return None
    hosts: dict[str, Host] = {}
    for line in p.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and re.match(r"\d+\.\d+\.\d+\.\d+$", parts[0]):
            ip, mac = parts[0], parts[1].lower()
            vend = parts[2].strip() if len(parts) > 2 else ""
            if ip in hosts and hosts[ip].mac != mac:
                hosts[ip].dup = True
                continue
            if vend in ("(Unknown)", "(Unknown: locally administered)"):
                vend = ""
            hosts[ip] = Host(ip, mac, oui.vendor(mac) or vend)
    return list(hosts.values())


def poke_scan(net: ipaddress.IPv4Network, own_ip: str, stop=None) -> list[Host]:
    """No arp-scan: send one UDP packet to every address so the kernel ARPs
    for it, then read the neighbour table."""
    hosts = list(net.hosts())[:1024]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for rnd in range(2):
        for h in hosts:
            if stop and stop():
                break
            try:
                s.sendto(b"\0", (str(h), 9))
            except OSError:
                pass
        time.sleep(1.5)
    s.close()
    arp = util.arp_table()
    return [Host(ip, mac, oui.vendor(mac)) for ip, mac in arp.items()
            if ipaddress.ip_address(ip) in net and ip != own_ip]


def netbios_name(ip: str, timeout: float = 0.8) -> str:
    q = struct.pack("!HHHHHH", random.randint(1, 65535), 0, 1, 0, 0, 0)
    q += b"\x20" + b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + b"\x00" + struct.pack("!HH", 0x21, 1)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(q, (ip, 137))
            data, _ = s.recvfrom(2048)
        n = data[56]
        for i in range(n):
            off = 57 + i * 18
            name = data[off: off + 15].decode("latin-1").strip()
            flags = data[off + 16]
            if not flags & 0x80 and name:
                return name
    except (OSError, IndexError):
        pass
    return ""


def merged_scan(i, out=None) -> list[Host]:
    """arp-scan plus a kernel ARP sweep. Over Wi-Fi many access points
    drop arp-scan's packets, so the sweep finds devices it misses."""
    stop = (lambda: out.stopped) if out is not None else None
    hosts = {h.ip: h for h in (arp_scan(i.name, out) or [])}
    if i.network.prefixlen < 22 and out is not None:
        out.warn("Large subnet; sweeping the first 1024 addresses only")
    for h in poke_scan(i.network, i.ip, stop):
        hosts.setdefault(h.ip, h)
    if i.name.startswith("wl") and out is not None:
        out.dim("On Wi-Fi some devices stay hidden; Ethernet gives the full list.")
    return list(hosts.values())


def resolve_names(hosts: list[Host], stop=None) -> None:
    def one(h: Host):
        if stop and stop():
            return
        h.name = util.rdns(h.ip, 1.2) or mdns.reverse_name(h.ip, 0.8) or netbios_name(h.ip) or h.name
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, hosts))


def sort_ip(h: Host):
    return ipaddress.ip_address(h.ip)


def scan(out, iface: str = "") -> list[Host]:
    i = util.best_iface(iface or None)
    if not i or not i.ip:
        out.bad(f"{iface or 'No interface'} has no IP address. Connect Ethernet or Wi-Fi first.")
        return []
    net = i.network
    out.dim(f"Scanning {net} on {i.name} ({i.ip})...")
    t0 = time.monotonic()
    hosts = merged_scan(i, out)
    how = "ARP"
    if out.stopped:
        return []
    out.replace_last(f"{len(hosts)} devices found ({how}, {time.monotonic() - t0:.0f}s). Getting names...", util_dim())
    resolve_names(hosts, lambda: out.stopped)
    hosts.sort(key=sort_ip)
    remember(hosts)
    out.replace_last(f"{len(hosts)} devices on {net} via {i.name}  (Enter = actions)", util_dim())
    gw = util.default_gateway(i.name)
    for h in hosts:
        tag = " GW" if h.ip == gw else ""
        sub = f"\n  {h.mac or '?':17} {(h.vendor or '?')[:11]}"   # fits one LCD row
        line = f"{h.ip:15} {h.name}{tag}" + sub
        if h.dup:
            out.item(f"{h.ip:15} DUPLICATE IP! {h.name}{tag}" + sub, h, (255, 95, 95))
        else:
            out.item(line, h)
    return hosts


def util_dim():
    from .ui import DIM
    return DIM


def find_all(out, iface: str = "") -> list[Host]:
    """Your own network settings (IP, mask, gateway, DNS, DHCP...) followed by
    every device on the subnet."""
    from . import basics
    basics.basics(out)
    if out.stopped:
        return []
    out.head("Devices on this subnet")
    return scan(out, iface)
