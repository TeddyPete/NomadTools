"""Network control through NetworkManager (nmcli).

Safety rules this module follows:
- Every connection profile the app creates is in-memory only ("save no")
  and named tnt-share-*. NetworkManager forgets them on reboot, so a reboot
  always brings back the normal network setup.
- Before the app changes an interface, it records which profile was active
  on it (in $XDG_RUNTIME_DIR, also cleared on reboot). restore() removes the
  app's profiles, stops NAT and re-activates what was there before.
- The only root-level step (NAT + IP forwarding) runs in a systemd unit,
  tnt-wifi-share-nat@<iface>.service, which is never enabled at boot.
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import time

from . import settings as S

PREFIX = "tnt-share-"
CON_ETH = PREFIX + "eth"          # mode 1: Ethernet side of Wi-Fi -> Ethernet
CON_HOTSPOT = PREFIX + "hotspot"  # mode 2: the access point
CON_UPLINK = PREFIX + "uplink"    # mode 2: static-IP Ethernet uplink
NAT_UNIT = "tnt-wifi-share-nat@{}.service"

MODE_NAMES = {None: "Not sharing", "wifi2eth": "Wi-Fi -> Ethernet", "hotspot": "Ethernet -> Hotspot"}

os.environ["PATH"] = os.environ.get("PATH", "/usr/bin:/bin") + ":/usr/sbin:/sbin"
RUN_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "tnt-wifi-share")
STATE = os.path.join(RUN_DIR, "state.json")


class NetError(Exception):
    pass


# ---- command helpers -----------------------------------------------------

def run(args: list[str], timeout: float = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{args[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{args[0]} timed out"


def nm(*args: str, timeout: float = 30) -> tuple[int, str, str]:
    return run(["nmcli", "-w", str(int(timeout)), *args], timeout=timeout + 5)


def split_terse(line: str) -> list[str]:
    """Split one line of `nmcli -t` output (':' separated, '\\:' escaped)."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def terse(*args: str, timeout: float = 20) -> list[list[str]]:
    rc, out, _ = nm("-t", *args, timeout=timeout)
    if rc != 0:
        return []
    return [split_terse(l) for l in out.splitlines() if l]


def nm_error(err: str) -> str:
    err = err.replace("Error: ", "").strip()
    if "Not authorized" in err or "Insufficient privileges" in err:
        return "Not allowed to change the network (polkit). Reinstall the app."
    return err.splitlines()[-1][:160] if err else "failed"


# ---- devices and status --------------------------------------------------

def devices() -> list[dict]:
    rows = terse("-f", "DEVICE,TYPE,STATE,CONNECTION", "device")
    return [dict(dev=r[0], type=r[1], state=r[2], con=r[3]) for r in rows if len(r) >= 4]


def wifi_dev(devs=None) -> str | None:
    for d in devs or devices():
        if d["type"] == "wifi":
            return d["dev"]
    return None


def eth_dev(devs=None) -> str | None:
    for d in devs or devices():
        if d["type"] == "ethernet":
            return d["dev"]
    return None


def active_uuid(dev: str) -> str | None:
    rc, out, _ = nm("-g", "GENERAL.CON-UUID", "device", "show", dev, timeout=10)
    u = out.strip()
    return u if rc == 0 and u and u != "--" else None


def ipv4(dev: str) -> list[str]:
    rc, out, _ = run(["ip", "-4", "-o", "addr", "show", "dev", dev], timeout=5)
    return [l.split()[3] for l in out.splitlines() if len(l.split()) > 3]


def carrier(dev: str) -> bool:
    try:
        return open(f"/sys/class/net/{dev}/carrier").read().strip() == "1"
    except OSError:
        return False


def default_route() -> tuple[str, str] | None:
    rc, out, _ = run(["ip", "-4", "route", "show", "default"], timeout=5)
    for l in out.splitlines():
        p = l.split()
        if "via" in p and "dev" in p:
            return p[p.index("via") + 1], p[p.index("dev") + 1]
    return None


def wifi_link(dev: str) -> dict:
    """SSID / signal / channel of the network wlan is joined to (or AP)."""
    for r in terse("-f", "IN-USE,SSID,SIGNAL,SECURITY,CHAN", "device", "wifi", "list", "ifname", dev,
                   "--rescan", "no"):
        if len(r) >= 5 and r[0] == "*":
            return dict(ssid=r[1], signal=int(r[2] or 0), security=r[3], chan=r[4])
    return {}


def scan(dev: str, rescan: bool = True) -> list[dict]:
    rows = terse("-f", "IN-USE,SSID,SIGNAL,SECURITY,CHAN", "device", "wifi", "list", "ifname", dev,
                 "--rescan", "yes" if rescan else "auto", timeout=25)
    best: dict[str, dict] = {}
    for r in rows:
        if len(r) < 5 or not r[1]:
            continue
        n = dict(ssid=r[1], signal=int(r[2] or 0), security=r[3] if r[3] not in ("", "--") else "",
                 chan=r[4], active=r[0] == "*")
        cur = best.get(n["ssid"])
        if not cur or n["active"] or (n["signal"] > cur["signal"] and not cur["active"]):
            best[n["ssid"]] = n
    saved = saved_wifi()
    for n in best.values():
        n["saved"] = n["ssid"] in saved
    return sorted(best.values(), key=lambda n: (not n["active"], -n["signal"]))


def saved_wifi() -> dict[str, str]:
    """SSID -> UUID of saved (on-disk) Wi-Fi client profiles."""
    out: dict[str, str] = {}
    for r in terse("-f", "NAME,UUID,TYPE", "connection", "show"):
        if len(r) >= 3 and r[2] in ("802-11-wireless", "wifi") and not r[0].startswith(PREFIX):
            rc, ssid, _ = nm("-g", "802-11-wireless.ssid,802-11-wireless.mode", "connection", "show", r[1], timeout=10)
            parts = ssid.strip().splitlines()
            if rc == 0 and parts and (len(parts) < 2 or parts[1] in ("infrastructure", "")):
                out.setdefault(parts[0], r[1])
    return out


def leases(dev: str) -> dict[str, tuple[str, str]]:
    """MAC -> (ip, hostname) from NetworkManager's dnsmasq lease file."""
    out = {}
    try:
        for l in open(f"/var/lib/NetworkManager/dnsmasq-{dev}.leases"):
            p = l.split()
            if len(p) >= 4:
                out[p[1].lower()] = (p[2], "" if p[3] == "*" else p[3])
    except OSError:
        pass
    return out


def clients(dev: str, ap: bool = False) -> list[dict]:
    """Devices seen on the shared side: DHCP leases, ARP neighbours and, for
    the hotspot, associated Wi-Fi stations."""
    seen: dict[str, dict] = {}
    rc, out, _ = run(["ip", "-4", "neigh", "show", "dev", dev], timeout=5)
    for l in out.splitlines():
        p = l.split()
        if "lladdr" in p and p[-1] not in ("FAILED", "INCOMPLETE"):
            mac = p[p.index("lladdr") + 1].lower()
            seen[mac] = dict(mac=mac, ip=p[0], name="")
    for mac, (ip, name) in leases(dev).items():
        c = seen.setdefault(mac, dict(mac=mac, ip=ip, name=""))
        c["name"] = name
        if not c["ip"]:
            c["ip"] = ip
    if ap:
        rc, out, _ = run(["iw", "dev", dev, "station", "dump"], timeout=5)
        stations = {l.split()[1].lower() for l in out.splitlines() if l.startswith("Station")}
        for mac in stations:
            seen.setdefault(mac, dict(mac=mac, ip="", name=""))
        for c in seen.values():
            c["wifi"] = c["mac"] in stations
        seen = {m: c for m, c in seen.items() if c.get("wifi") or c["ip"]}
    return sorted(seen.values(), key=lambda c: tuple(int(x) for x in c["ip"].split(".")) if c["ip"] else (999,))


# ---- remembered state (what to restore) -----------------------------------

def load_state() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"mode": None, "saved": {}, "nat": []}


def save_state(st: dict) -> None:
    os.makedirs(RUN_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, STATE)


def remember(st: dict, dev: str) -> None:
    """Record the profile active on dev, the first time we touch it."""
    if dev and dev not in st["saved"]:
        st["saved"][dev] = active_uuid(dev)
        save_state(st)


def our_connections() -> list[str]:
    return [r[1] for r in terse("-f", "NAME,UUID", "connection", "show") if len(r) >= 2 and r[0].startswith(PREFIX)]


def nat(action: str, dev: str) -> tuple[bool, str]:
    rc, _, err = run(["systemctl", "--no-ask-password", action, NAT_UNIT.format(dev)], timeout=30)
    return rc == 0, err


def needs_restore() -> bool:
    st = load_state()
    return bool(st.get("mode") or st.get("saved") or st.get("nat") or our_connections())


def restore(log=print) -> list[str]:
    """Undo everything the app changed. Safe to call any time, repeatedly."""
    st = load_state()
    msgs = []
    for uuid in our_connections():
        nm("connection", "delete", uuid, timeout=20)
    for dev in st.get("nat", []):
        ok, err = nat("stop", dev)
        if not ok:
            msgs.append(f"NAT stop on {dev}: {err[:80]}")
    for dev, uuid in st.get("saved", {}).items():
        if uuid and active_uuid(dev) != uuid:
            rc, _, err = nm("connection", "up", uuid, timeout=45)
            msgs.append(f"{dev}: {'restored' if rc == 0 else 'restore failed: ' + nm_error(err)}")
        elif not uuid:
            msgs.append(f"{dev}: left to auto-connect")
    save_state({"mode": None, "saved": {}, "nat": []})
    for m in msgs:
        log(m)
    return msgs


# ---- modes -----------------------------------------------------------------

def _cidr(ip: str, mask: str) -> str:
    return f"{ip.strip()}/{S.mask_to_prefix(mask)}"


def _up(con: str, dev: str, timeout: float = 45) -> tuple[bool, str]:
    rc, _, err = nm("connection", "up", con, timeout=timeout)
    if rc == 0:
        return True, ""
    if not carrier(dev) and dev.startswith(("eth", "en")):
        return True, "Waiting for Ethernet cable"
    return False, nm_error(err)


def _add(*args: str) -> None:
    rc, _, err = nm("connection", "add", "save", "no", *args, timeout=20)
    if rc != 0:
        raise NetError(nm_error(err))


def start_wifi_to_eth(cfg: dict) -> str:
    """Mode 1: share the Wi-Fi uplink to the Ethernet port (NAT, optional DHCP)."""
    devs = devices()
    w, e = wifi_dev(devs), eth_dev(devs)
    if not e:
        raise NetError("No Ethernet port found")
    st = load_state()
    if st.get("mode") == "hotspot":
        # Wi-Fi is the access point right now: turn it back into a client.
        stop_sharing(keep_saved=True)
        uuid = st.get("saved", {}).get(w)
        if uuid:
            nm("connection", "up", uuid, timeout=45)
        devs = devices()
    if not w or not next((d for d in devs if d["dev"] == w and d["state"] == "connected"), None):
        raise NetError("Join a Wi-Fi network first")
    err = S.check_host(cfg["share_ip"], cfg["share_mask"])
    if err:
        raise NetError(err)
    stop_sharing(keep_saved=True)
    st = load_state()
    remember(st, e)
    common = ["type", "ethernet", "ifname", e, "con-name", CON_ETH, "autoconnect", "yes",
              "connection.autoconnect-priority", "100", "ipv6.method", "disabled",
              "ipv4.addresses", _cidr(cfg["share_ip"], cfg["share_mask"])]
    if cfg["share_dhcp"]:
        _add(*common, "ipv4.method", "shared")
    else:
        _add(*common, "ipv4.method", "manual", "ipv4.never-default", "yes")
    st["nat"] = [e]
    st["mode"] = "wifi2eth"
    save_state(st)
    ok2, err = nat("start", e)
    if not ok2:
        restore(log=lambda m: None)
        raise NetError(f"NAT failed: {err[:100]}")
    ok, note = _up(CON_ETH, e)
    if not ok:
        restore(log=lambda m: None)
        raise NetError(note)
    dhcp = "DHCP on" if cfg["share_dhcp"] else "DHCP off"
    return f"Sharing Wi-Fi to Ethernet ({dhcp}). " + (note or "")


def start_hotspot(cfg: dict) -> str:
    """Mode 2: Wi-Fi access point sharing the Ethernet uplink."""
    devs = devices()
    w, e = wifi_dev(devs), eth_dev(devs)
    if not w:
        raise NetError("No Wi-Fi adapter found")
    err = S.check_hotspot(cfg["hs_ssid"], cfg["hs_password"]) or S.check_host(cfg["hs_ip"], "24")
    if err:
        raise NetError(err)
    if not cfg["uplink_dhcp"]:
        err = S.check_host(cfg["uplink_ip"], cfg["uplink_mask"])
        if err:
            raise NetError("Uplink: " + err)
    stop_sharing(keep_saved=True)
    st = load_state()
    remember(st, w)
    notes = []
    if e and not cfg["uplink_dhcp"]:
        remember(st, e)
        args = ["type", "ethernet", "ifname", e, "con-name", CON_UPLINK, "autoconnect", "yes",
                "connection.autoconnect-priority", "100", "ipv6.method", "disabled",
                "ipv4.method", "manual", "ipv4.addresses", _cidr(cfg["uplink_ip"], cfg["uplink_mask"])]
        if S.valid_ip(cfg["uplink_gw"]):
            args += ["ipv4.gateway", cfg["uplink_gw"].strip()]
        dns = [d for d in cfg["uplink_dns"].replace(",", " ").split() if S.valid_ip(d)]
        if dns:
            args += ["ipv4.dns", " ".join(dns)]
        _add(*args)
        ok, note = _up(CON_UPLINK, e)
        if note:
            notes.append(note)
    elif e and not carrier(e):
        notes.append("Plug in the Ethernet uplink")
    elif e:
        nm("device", "connect", e, timeout=30)
    ch = str(cfg["hs_channel"]).strip() or "6"
    _add("type", "wifi", "ifname", w, "con-name", CON_HOTSPOT, "autoconnect", "no",
         "ssid", cfg["hs_ssid"], "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
         "802-11-wireless.channel", ch, "ipv4.method", "shared",
         "ipv4.addresses", f"{cfg['hs_ip'].strip()}/24", "ipv6.method", "disabled",
         "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", cfg["hs_password"],
         "wifi-sec.proto", "rsn", "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp",
         "wifi-sec.pmf", "disable")
    st["nat"] = [w]
    st["mode"] = "hotspot"
    save_state(st)
    ok2, err = nat("start", w)
    if not ok2:
        notes.append(f"NAT helper: {err[:60]}")
    ok, note = _up(CON_HOTSPOT, w, timeout=60)
    if not ok:
        restore(log=lambda m: None)
        raise NetError("Hotspot failed: " + note)
    return f"Hotspot {cfg['hs_ssid']} is on. " + " ".join(notes)


def stop_sharing(keep_saved: bool = False) -> list[str]:
    """Stop whichever mode is running. With keep_saved, the record of the
    original profiles is kept so a later restore() still brings them back."""
    if not keep_saved:
        return restore(log=lambda m: None)
    st = load_state()
    for name in (CON_ETH, CON_HOTSPOT, CON_UPLINK):
        nm("connection", "delete", "id", name, timeout=20)
    for dev in st.get("nat", []):
        nat("stop", dev)
    st["nat"], st["mode"] = [], None
    save_state(st)
    return []


# ---- Wi-Fi client ----------------------------------------------------------

def join_wifi(ssid: str, password: str = "", hidden: bool = False) -> str:
    w = wifi_dev()
    if not w:
        raise NetError("No Wi-Fi adapter found")
    st = load_state()
    if st.get("mode") == "hotspot":
        stop_sharing(keep_saved=True)
    remember(st, w)
    uuid = saved_wifi().get(ssid)
    if uuid:
        if password:
            nm("connection", "modify", uuid, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password)
        rc, _, err = nm("connection", "up", uuid, timeout=45)
    else:
        args = ["device", "wifi", "connect", ssid, "ifname", w]
        if password:
            args += ["password", password]
        if hidden:
            args += ["hidden", "yes"]
        rc, _, err = nm(*args, timeout=45)
    if rc != 0:
        msg = nm_error(err)
        if "Secrets were required" in err or "802-1x" in err or "psk" in err.lower():
            msg = "Wrong password (or unsupported security)"
        raise NetError(msg)
    return f"Joined {ssid}"


def forget_wifi(ssid: str) -> str:
    uuid = saved_wifi().get(ssid)
    if not uuid:
        return f"{ssid} is not saved"
    if uuid in load_state().get("saved", {}).values():
        raise NetError("That network is needed to restore your setup")
    rc, _, err = nm("connection", "delete", uuid)
    if rc != 0:
        raise NetError(nm_error(err))
    return f"Forgot {ssid}"


def wifi_disconnect() -> None:
    w = wifi_dev()
    if w:
        st = load_state()
        remember(st, w)
        nm("device", "disconnect", w)


def status() -> dict:
    devs = devices()
    w, e = wifi_dev(devs), eth_dev(devs)
    st = load_state()
    d = {d_["dev"]: d_ for d_ in devs}
    out = dict(mode=st.get("mode"), wifi=w, eth=e, route=default_route())
    if w:
        out["wifi_state"] = d[w]["state"]
        out["wifi_con"] = d[w]["con"]
        out["wifi_ip"] = ipv4(w)
        out["wifi_link"] = wifi_link(w) if d[w]["state"].startswith("connected") else {}
    if e:
        out["eth_state"] = d[e]["state"]
        out["eth_con"] = d[e]["con"]
        out["eth_ip"] = ipv4(e)
        out["eth_carrier"] = carrier(e)
    side = {"wifi2eth": e, "hotspot": w}.get(st.get("mode"))
    out["clients"] = clients(side, ap=st.get("mode") == "hotspot") if side else []
    return out
