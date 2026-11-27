"""Find a scanned device on the network.

* MAC known: wake up every address on the local subnet(s) (arp-scan when
  Nomad Net Tools has given it network rights, otherwise a tiny UDP poke to
  each address so the kernel ARPs it) and look the MAC up in the ARP table.
* IP known: ping it and read its MAC from the ARP table.

No root needed. Works on Ethernet and Wi-Fi.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import subprocess
import time

from . import parse


def local_nets() -> list[tuple[str, str, ipaddress.IPv4Network]]:
    """[(iface, my_ip, network)] for every up IPv4 interface except loopback."""
    out = []
    try:
        r = subprocess.run(["ip", "-o", "-4", "addr", "show", "up"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return out
    for line in r.stdout.splitlines():
        m = re.search(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
        if not m or m.group(1) == "lo" or m.group(1).startswith(("docker", "veth")):
            continue
        net = ipaddress.ip_network(f"{m.group(2)}/{m.group(3)}", strict=False)
        out.append((m.group(1), m.group(2), net))
    return out


def arp_table() -> dict[str, tuple[str, str]]:
    """MAC -> (ip, iface) from the kernel's neighbour table."""
    out = {}
    try:
        with open("/proc/net/arp") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) >= 6 and p[2] != "0x0" and p[3] != "00:00:00:00:00:00":
                    out[p[3].upper()] = (p[0], p[5])
    except (OSError, StopIteration):
        pass
    return out


def _hosts(net: ipaddress.IPv4Network, my_ip: str) -> list[str]:
    if net.prefixlen < 22:          # don't sweep huge networks: the /24 around us
        net = ipaddress.ip_network(f"{my_ip}/24", strict=False)
    return [str(h) for h in net.hosts() if str(h) != my_ip]


def _arp_scan(iface: str) -> dict[str, str]:
    exe = shutil.which("arp-scan") or ("/usr/sbin/arp-scan" if os.path.exists("/usr/sbin/arp-scan") else "")
    if not exe:
        return {}
    try:
        r = subprocess.run([exe, "-q", "-x", "-r", "2", "-I", iface, "--localnet"],
                           capture_output=True, text=True, timeout=25)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and parse.norm_mac(p[1]):
            out[parse.norm_mac(p[1])] = p[0]
    return out


def _poke(hosts: list[str]) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(False)
    for h in hosts:
        try:
            s.sendto(b"\0", (h, 9))      # discard port: the point is the ARP request
        except OSError:
            pass
        time.sleep(0.002)
    s.close()


def sweep(progress=None) -> dict[str, tuple[str, str]]:
    """Every device that answers on the local networks: MAC -> (ip, iface)."""
    found: dict[str, tuple[str, str]] = {}
    for iface, my_ip, net in local_nets():
        if progress:
            progress(f"Looking on {iface} {net}")
        got = _arp_scan(iface) if net.prefixlen >= 16 else {}
        if got:
            for mac, ip in got.items():
                found[mac] = (ip, iface)
            continue
        _poke(_hosts(net, my_ip))
    time.sleep(2.0)
    for mac, (ip, iface) in arp_table().items():
        found.setdefault(mac, (ip, iface))
    return found


def find_mac(mac: str, progress=None) -> tuple[str, str] | None:
    mac = parse.norm_mac(mac)
    if not mac:
        return None
    hit = arp_table().get(mac)
    if hit and ping(hit[0], 1)[0]:
        return hit
    return sweep(progress).get(mac)


def ping(ip: str, count: int = 3) -> tuple[bool, str]:
    """(answered, "2.1 ms" / "no reply")."""
    try:
        r = subprocess.run(["ping", "-n", "-c", str(count), "-W", "1", "-i", "0.3", ip],
                           capture_output=True, text=True, timeout=count * 2 + 3)
    except (OSError, subprocess.TimeoutExpired):
        return False, "no reply"
    m = re.search(r"= [\d.]+/([\d.]+)/", r.stdout)
    if r.returncode == 0 and m:
        return True, f"{float(m.group(1)):.1f} ms"
    return False, "no reply"


def mac_of_ip(ip: str) -> str:
    for mac, (a, _) in arp_table().items():
        if a == ip:
            return mac
    return ""


def rdns(ip: str) -> str:
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(1.5)
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return ""
    finally:
        socket.setdefaulttimeout(old)


def check(mac: str = "", ip: str = "", progress=None) -> dict:
    """Look one device up. Returns {ip, mac, online, text, iface, host}."""
    res = {"ip": ip, "mac": parse.norm_mac(mac), "online": False, "text": "", "iface": "", "host": ""}
    if res["mac"]:
        hit = find_mac(res["mac"], progress)
        if hit:
            res["ip"], res["iface"] = hit
            ok, t = ping(hit[0])
            res["online"] = True
            res["text"] = f"online {t}" if ok else "online (no ping reply)"
        elif ip:
            ok, t = ping(ip)
            res["online"] = ok
            res["text"] = f"IP answers {t}, MAC not seen" if ok else "not found"
        else:
            res["text"] = "not found on this network"
    elif ip:
        ok, t = ping(ip)
        res["online"] = ok
        res["text"] = f"online {t}" if ok else "no reply"
        if ok:
            res["mac"] = mac_of_ip(ip)
    else:
        res["text"] = "no MAC or IP to look for"
    if res["online"] and res["ip"]:
        res["host"] = rdns(res["ip"])
    return res
