"""Check one IP address: which display control methods answer, and what
the display still needs (password, pairing, a setting turned on).

Nothing here changes the display or makes it show anything: only greetings,
status queries and read-only HTTP requests.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import socket
import urllib.error
import urllib.request

from .base import Display

# Other control ports AV gear often has (reported, not used by this app yet).
OTHER_PORTS = {23: "Telnet", 7142: "NEC control", 3629: "Epson ESC/VP.net", 1024: "Panasonic control",
               3002: "Christie", 1025: "Barco", 9090: "Sharp/NEC (some)", 6466: "Android TV remote",
               8009: "Google Cast", 9197: "Samsung UPnP", 20060: "Sony Bravia Pro (simple IP)"}

READY, NEEDS, NO, INFO = "ready", "needs", "no", "info"


def _open(ip, port, t=1.0) -> bool:
    try:
        socket.create_connection((ip, port), t).close()
        return True
    except OSError:
        return False


def _http(url, data=None, headers=None, t=2.5):
    req = urllib.request.Request(url, data, headers or {})
    with urllib.request.urlopen(req, timeout=t) as r:
        return r.status, r.read()


def pjlink(ip):
    try:
        s = socket.create_connection((ip, 4352), 1.5)
    except OSError:
        return NO, "PJLink: port 4352 closed (turn PJLink on in the network menu)", None
    try:
        s.settimeout(2.5)
        hello = s.recv(64).decode("latin-1").strip()
        if not hello.upper().startswith("PJLINK"):
            return NO, f"Port 4352 open but not PJLink ({hello[:20]})", None
        p = hello.split()
        if p[1:2] == ["1"]:
            return NEEDS, "PJLink: answers, needs the projector's PJLink password", "pjlink"
        if p[1:2] == ["0"]:
            s.sendall(b"%1CLSS ?\r")
            cls = s.recv(64).decode("latin-1").strip().split("=")[-1]
            return READY, f"PJLink class {cls if cls in ('1', '2') else '1'}: ready, no password", "pjlink"
        return NEEDS, f"PJLink: {hello[:30]}", "pjlink"
    except OSError:
        return NEEDS, "PJLink: port open but no greeting", "pjlink"
    finally:
        s.close()


def lg(ip):
    if _open(ip, 3001) or _open(ip, 3000):
        return READY, "LG webOS: control port open. Pair once (TV asks), power on by WoL", "lg"
    return NO, "LG webOS: closed (not LG, or TV is off: turn on via Wi-Fi needed)", None


def samsung(ip):
    try:
        _, body = _http(f"http://{ip}:8001/api/v2/")
        dev = json.loads(body.decode()).get("device") or {}
    except (OSError, ValueError):
        return NO, "Samsung Tizen: no API on 8001", None
    model = dev.get("modelName") or dev.get("name") or "TV"
    tok = str(dev.get("TokenAuthSupport", "")).lower() == "true"
    return READY, f"Samsung {model}: remote API on. {'Allow on TV once' if tok else 'No token needed'}", "samsung"


def sony(ip):
    body = json.dumps({"method": "getInterfaceInfo", "id": 1, "params": [], "version": "1.0"}).encode()
    try:
        _, r = _http(f"http://{ip}/sony/system", body, {"Content-Type": "application/json"})
        info = (json.loads(r.decode()).get("result") or [{}])[0]
    except (OSError, ValueError, IndexError, AttributeError):
        return NO, "Sony Bravia: no IP control API", None
    model = info.get("modelName", "Bravia")
    body = json.dumps({"method": "getPowerStatus", "id": 1, "params": [], "version": "1.0"}).encode()
    try:
        _, r = _http(f"http://{ip}/sony/system", body, {"Content-Type": "application/json"})
        data = json.loads(r.decode())
        if "error" in data and data["error"][0] in (401, 403):
            raise urllib.error.HTTPError("", 403, "", None, None)
        return READY, f"Sony {model}: IP control on, no key needed", "sony"
    except urllib.error.HTTPError:
        return NEEDS, f"Sony {model}: IP control on, needs the pre-shared key", "sony"
    except (OSError, ValueError):
        return NEEDS, f"Sony {model}: API found, power status refused", "sony"


def roku(ip):
    try:
        _, body = _http(f"http://{ip}:8060/query/device-info")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return NEEDS, "Roku: control blocked, set Control by mobile apps: Enabled", "roku"
        return NO, "Roku: no ECP", None
    except OSError:
        return NO, "Roku: no ECP on 8060", None
    import xml.etree.ElementTree as ET
    try:
        di = {c.tag: c.text or "" for c in ET.fromstring(body)}
    except ET.ParseError:
        di = {}
    name = di.get("friendly-device-name") or di.get("model-name") or "Roku"
    tv = " TV" if di.get("is-tv") == "true" else " (player, no TV power/inputs)"
    return READY, f"Roku {name}{tv}: ECP on", "roku"


def mac_of(ip) -> str:
    try:
        for line in open("/proc/net/arp").read().splitlines()[1:]:
            p = line.split()
            if p[0] == ip and p[3] != "00:00:00:00:00:00":
                return p[3].lower()
    except OSError:
        pass
    return ""


def check(ip: str) -> dict:
    """{"lines": [(state, text)], "kinds": [kind...], "mac": str, "reachable": bool}"""
    with cf.ThreadPoolExecutor(10) as ex:
        probes = {k: ex.submit(f, ip) for k, f in
                  (("pjlink", pjlink), ("lg", lg), ("samsung", samsung), ("sony", sony), ("roku", roku))}
        others = {p: ex.submit(_open, ip, p, 0.8) for p in OTHER_PORTS}
        alive = ex.submit(_open, ip, 80, 0.8)
        res = {k: f.result() for k, f in probes.items()}
        open_other = [p for p, f in others.items() if f.result()]
        alive = alive.result()
    lines, kinds = [], []
    for k in ("pjlink", "lg", "samsung", "sony", "roku"):
        state, text, kind = res[k]
        if state != NO:
            lines.append((state, text))
            kinds.append(kind)
    mac = mac_of(ip)
    reachable = bool(kinds or open_other or alive or mac)
    if not kinds:
        lines.append((NO, "No display control found." + ("" if reachable else " Nothing answers at this address.")))
    if open_other:
        lines.append((INFO, "Other ports: " + ", ".join(f"{p} {OTHER_PORTS[p]}" for p in sorted(open_other))))
    lines.append((INFO, f"MAC {mac} (for Wake-on-LAN)" if mac else "MAC unknown (not on this subnet?)"))
    return {"lines": lines, "kinds": kinds, "mac": mac, "reachable": reachable}


def to_display(ip: str, r: dict) -> Display | None:
    if not r["kinds"]:
        return None
    kind = r["kinds"][0]
    names = {"pjlink": "Projector", "lg": "LG TV", "samsung": "Samsung TV", "sony": "Sony TV", "roku": "Roku TV"}
    return Display(names[kind], kind, ip, mac=r["mac"])
