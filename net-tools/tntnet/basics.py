"""Network basics, ping and traceroute."""
from __future__ import annotations

import re

from . import util


def _nm_dev(dev: str) -> dict:
    out = {}
    for line in util.run(["nmcli", "-t", "-f", "GENERAL.CONNECTION,IP4.DNS,IP4.DOMAIN", "dev", "show", dev]).splitlines():
        k, _, v = line.partition(":")
        if v:
            out.setdefault(k.split("[")[0], []).append(v)
    return out


def _method(conn: str) -> str:
    m = util.run(["nmcli", "-g", "ipv4.method", "con", "show", conn]).strip()
    return {"auto": "DHCP", "manual": "Static", "link-local": "Link-local", "shared": "Shared (hotspot)",
            "disabled": "Disabled"}.get(m, m or "?")


def _read(path: str) -> str:
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def basics(out) -> None:
    gw_all = util.default_gateway()
    for i in util.interfaces():
        out.head(f"{i.name}  ({'up' if i.up else 'down'})")
        out.line(f"MAC      {i.mac}")
        if i.addrs:
            for ip, pfx in i.addrs:
                net = util.ipaddress.ip_network(f"{ip}/{pfx}", strict=False)
                out.ok(f"IP       {ip}/{pfx}  (mask {net.netmask})")
        else:
            out.warn("IP       none")
        gw = util.default_gateway(i.name)
        if gw:
            out.line(f"Gateway  {gw}")
        nm = _nm_dev(i.name)
        conn = (nm.get("GENERAL.CONNECTION") or [""])[0]
        if conn:
            out.line(f"Mode     {_method(conn)}  ({conn})")
        if nm.get("IP4.DNS"):
            out.line(f"DNS      {', '.join(nm['IP4.DNS'])}")
        if i.name.startswith(("eth", "en")):
            carrier = _read(f"/sys/class/net/{i.name}/carrier")
            speed = _read(f"/sys/class/net/{i.name}/speed")
            duplex = _read(f"/sys/class/net/{i.name}/duplex")
            if carrier == "1":
                out.ok(f"Link     up  {speed} Mb/s {duplex} duplex")
            else:
                out.warn("Link     no cable / no link")
        if i.name.startswith("wl"):
            link = util.run([util.which("iw"), "dev", i.name, "link"]) if util.have("iw") else ""
            ssid = re.search(r"SSID: (.+)", link)
            sig = re.search(r"signal: (-?\d+) dBm", link)
            freq = re.search(r"freq: ([\d.]+)", link)
            rate = re.search(r"tx bitrate: ([\d.]+ \S+)", link)
            if ssid:
                out.line(f"Wi-Fi    {ssid.group(1)}")
            if sig:
                dbm = int(sig.group(1))
                q = "excellent" if dbm >= -55 else "good" if dbm >= -67 else "fair" if dbm >= -75 else "poor"
                (out.ok if dbm >= -67 else out.warn if dbm >= -75 else out.bad)(f"Signal   {dbm} dBm ({q})")
            else:
                w = _read("/proc/net/wireless")
                m = re.search(rf"{i.name}:\s+\S+\s+([\d.]+)\s+(-?[\d.]+)", w)
                if m:
                    out.line(f"Signal   {m.group(2)} dBm")
            if freq:
                f = float(freq.group(1))
                out.line(f"Band     {'5 GHz' if f > 4000 else '2.4 GHz'} ({f:.0f} MHz)")
            if rate:
                out.line(f"Rate     {rate.group(1)}")
    if gw_all:
        out.head("Reachability")
        for tgt, name in ((gw_all, "gateway"), ("1.1.1.1", "internet"), ("one.one.one.one", "DNS name")):
            r = util.run(["ping", "-c", "2", "-W", "1", "-i", "0.3", tgt], timeout=6)
            m = re.search(r"= [\d.]+/([\d.]+)/", r)
            if m:
                out.ok(f"{name:9}{tgt}  {float(m.group(1)):.1f} ms")
            else:
                out.bad(f"{name:9}{tgt}  no reply")
    else:
        out.warn("No default gateway")


def ping(out, target: str, count: str = "", size: str = "") -> None:
    cmd = ["ping", "-i", "0.5", "-W", "1"]
    if count and count.isdigit() and int(count) > 0:
        cmd += ["-c", count]
    if size and size.isdigit():
        cmd += ["-s", size]
    cmd.append(target)
    out.dim("X stops. " + " ".join(cmd))
    sent = [0]

    def filt(line: str):
        m = re.search(r"icmp_seq=(\d+).*time=([\d.]+)", line)
        if m:
            sent[0] += 1
            return f"#{m.group(1):>4}  {float(m.group(2)):7.2f} ms"
        return line

    util.stream(out, cmd, filt=filt)
    if out.stopped:
        out.dim("(stopped; summary not printed by ping)")


def traceroute(out, target: str) -> None:
    if util.have("traceroute"):
        cmd = ["traceroute", "-n", "-w", "2", "-q", "2", "-m", "25", target]
    else:
        cmd = ["tracepath", "-n", target]
    out.dim(" ".join(cmd))
    names: dict[str, str] = {}

    def filt(line: str):
        ips = re.findall(r"\d+\.\d+\.\d+\.\d+", line)
        if ips and not line.startswith("traceroute"):
            ip = ips[0]
            if ip not in names:
                names[ip] = util.rdns(ip, 1.0)
            if names[ip]:
                return f"{line}  {names[ip]}"
        return line

    util.stream(out, cmd, filt=filt)
