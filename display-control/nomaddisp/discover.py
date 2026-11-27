"""Find displays on the local network.

Three passes run together, then the hits are identified:
  * SSDP M-SEARCH for LG, Samsung, Sony and Roku service types
  * PJLink class 2 UDP search (%2SRCH)
  * a TCP port sweep of each local subnet (/24 around our own address) for
    4352 PJLink, 3001 LG, 8001 Samsung, 8060 Roku, 80 Sony
"""
from __future__ import annotations

import concurrent.futures as cf
import ipaddress
import json
import re
import socket
import subprocess
import time
import urllib.request

from .base import Display
from . import pjlink

PORTS = {4352: "pjlink", 3001: "lg", 8001: "samsung", 8002: "samsung", 8060: "roku", 80: "sony?"}
SSDP_ST = {
    "urn:lge-com:service:webos-second-screen:1": "lg",
    "urn:samsung.com:device:RemoteControlReceiver:1": "samsung",
    "urn:schemas-sony-com:service:ScalarWebAPI:1": "sony",
    "roku:ecp": "roku",
}


def local_nets(max_hosts: int = 254) -> list[tuple[str, ipaddress.IPv4Network]]:
    """[(our_ip, network)] for each IPv4 interface; big subnets are cut to
    the /24 around our address."""
    out = []
    try:
        txt = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    for m in re.finditer(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+/\d+)", txt, re.M):
        if m.group(1) == "lo":
            continue
        iface = ipaddress.IPv4Interface(m.group(2))
        net = iface.network
        if net.num_addresses - 2 > max_hosts:
            net = ipaddress.IPv4Interface(f"{iface.ip}/24").network
        out.append((str(iface.ip), net))
    return out


def arp_table() -> dict[str, str]:
    out = {}
    try:
        for line in open("/proc/net/arp").read().splitlines()[1:]:
            p = line.split()
            if len(p) >= 4 and p[3] != "00:00:00:00:00:00":
                out[p[0]] = p[3].lower()
    except OSError:
        pass
    return out


def ssdp(timeout: float = 2.5) -> dict[str, set]:
    found: dict[str, set] = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(0.3)
        for st in SSDP_ST:
            msg = (f'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
                   f"MX: 2\r\nST: {st}\r\n\r\n").encode()
            try:
                s.sendto(msg, ("239.255.255.250", 1900))
            except OSError:
                return found
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, (ip, _) = s.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            t = data.decode("latin-1", "replace").lower()
            for st, kind in SSDP_ST.items():
                if st.lower() in t:
                    found.setdefault(ip, set()).add(kind)
    finally:
        s.close()
    return found


def _open(ip: str, port: int, timeout: float) -> bool:
    try:
        socket.create_connection((ip, port), timeout).close()
        return True
    except OSError:
        return False


def sweep(hosts: list[str], timeout: float = 0.5, workers: int = 48, progress=None) -> dict[str, set]:
    """{ip: {ports open}}"""
    found: dict[str, set] = {}
    jobs = [(h, p) for h in hosts for p in PORTS]
    done = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_open, h, p, timeout): (h, p) for h, p in jobs}
        for f in cf.as_completed(futs):
            done += 1
            if progress and done % 50 == 0:
                progress(done, len(jobs))
            if f.result():
                h, p = futs[f]
                found.setdefault(h, set()).add(p)
    return found


def _http_json(url: str, data: bytes | None = None, timeout: float = 2.0) -> dict:
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def identify(ip: str, kinds: set, ports: set, macs: dict) -> Display | None:
    """Work out what is at ip. Returns a Display (not saved) or None."""
    mac = macs.get(ip, "")
    if "samsung" in kinds or 8001 in ports or 8002 in ports:
        try:
            dev = _http_json(f"http://{ip}:8001/api/v2/").get("device") or {}
            if dev.get("type", "").lower().find("tv") >= 0 or dev.get("modelName"):
                return Display(dev.get("name") or "Samsung TV", "samsung", ip, 8002 if 8002 in ports else 0,
                               (dev.get("wifiMac") or mac).lower(), model=dev.get("modelName", ""))
        except (OSError, ValueError):
            pass
    if "roku" in kinds or 8060 in ports:
        try:
            from .roku import Roku, mac_from_info
            di = Roku(Display("", "roku", ip), 2.0).device_info()
            name = di.get("friendly-device-name") or di.get("user-device-name") or "Roku"
            return Display(name, "roku", ip, 0, mac_from_info(di) or mac, model=di.get("model-name", ""))
        except Exception:
            pass
    if "lg" in kinds or 3001 in ports:
        return Display("LG TV", "lg", ip, 0, mac, model="webOS")
    if "sony" in kinds or 80 in ports:
        try:
            r = _http_json(f"http://{ip}/sony/system", json.dumps(
                {"method": "getInterfaceInfo", "id": 1, "params": [], "version": "1.0"}).encode(), 2.0)
            info = (r.get("result") or [{}])[0]
            if info.get("productCategory") or info.get("modelName"):
                return Display(f"Sony {info.get('modelName', 'Bravia')}".strip(), "sony", ip, 0, mac,
                               model=info.get("modelName", ""))
        except (OSError, ValueError, AttributeError, IndexError):
            pass
    if "pjlink" in kinds or 4352 in ports:
        d = Display("Projector", "pjlink", ip, 0, mac)
        try:
            p = pjlink.PJLink(d, 2.5)
            name, maker, model = p.session(["%1NAME ?", "%1INF1 ?", "%1INF2 ?"])
            bad = lambda v: not v or v.upper().startswith("ERR")
            d.model = " ".join(x for x in (maker, model) if not bad(x))
            d.name = (name if not bad(name) else d.model) or "Projector"
        except Exception as e:
            if "password" in str(e).lower():
                d.name, d.extra = "Projector (password)", {"auth": True}
            # still a PJLink port, keep it
        return d
    return None


def retry_saved(saved: list, tries: int = 3, timeout: float = 2.0) -> list:
    """Saved displays that missed the quick sweep get a slower second chance.

    TVs on Wi-Fi in power-save often drop the first packets (ARP stays
    INCOMPLETE) and only answer once a few probes have woken the radio.
    """
    back = []
    for d in saved:
        ports = [d.port] if d.port else [p for p, k in PORTS.items() if k.rstrip("?") == d.kind]
        if not ports:
            continue
        for _ in range(tries):
            if any(_open(d.host, p, timeout) for p in ports):
                back.append(d)
                break
    return back


def scan(progress=None) -> list[Display]:
    """Find displays; progress(text) is called now and then."""
    say = progress or (lambda t: None)
    nets = local_nets()
    hosts = []
    mine = set()
    for ip, net in nets:
        mine.add(ip)
        hosts += [str(h) for h in net.hosts() if str(h) != ip]
    hosts = list(dict.fromkeys(hosts))
    result: dict[str, set] = {}
    with cf.ThreadPoolExecutor(2) as ex:
        f_ssdp = ex.submit(ssdp)
        f_pj = ex.submit(pjlink.search)
        say(f"Sweeping {len(hosts)} addresses")
        ports = sweep(hosts, progress=lambda d, n: say(f"Checked {d * 100 // max(1, n)}%"))
        for ip, kinds in f_ssdp.result().items():
            result.setdefault(ip, set()).update(kinds)
        pj_macs = f_pj.result()
        for ip in pj_macs:
            result.setdefault(ip, set()).add("pjlink")
    for ip in ports:
        result.setdefault(ip, set())
    macs = arp_table()
    for ip, mac in pj_macs.items():
        from .wol import norm_mac
        macs.setdefault(ip, norm_mac(mac) or "")
    say(f"Identifying {len(result)} devices")
    out = []
    with cf.ThreadPoolExecutor(8) as ex:
        futs = [ex.submit(identify, ip, kinds, ports.get(ip, set()), macs) for ip, kinds in result.items()
                if ip not in mine]
        for f in futs:
            try:
                d = f.result()
            except Exception:
                d = None
            if d:
                out.append(d)
    macs = arp_table()        # filled in by the connections we just made
    for d in out:
        if not d.mac:
            d.mac = macs.get(d.host, "")
    out.sort(key=lambda d: tuple(int(x) for x in d.host.split(".")))
    return out
