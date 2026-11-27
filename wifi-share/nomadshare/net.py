"""Network control through NetworkManager (nmcli).

Safety rules this module follows:
- Every connection profile the app creates is in-memory only ("save no")
  and named nomad-share-*. NetworkManager forgets them on reboot, so a reboot
  always brings back the normal network setup.
- Before the app changes an interface, it records which profile was active
  on it (in $XDG_RUNTIME_DIR, also cleared on reboot). restore() removes the
  app's profiles, stops NAT and re-activates what was there before.
- The only root-level steps (NAT, forwarding, device blocks, speed limits,
  port forwards, DHCP reservations) run in a systemd unit,
  nomad-wifi-share-nat@<iface>.service, which is never enabled at boot. The app
  hands it a rules file in /run/nomad-wifi-share-policy; the helper checks
  every value before use.
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import time

from . import settings as S

PREFIX = "nomad-share-"
CON_ETH = PREFIX + "eth"          # mode 1: Ethernet side of Wi-Fi -> Ethernet
CON_HOTSPOT = PREFIX + "hotspot"  # mode 2: the access point
CON_UPLINK = PREFIX + "uplink"    # mode 2: static-IP Ethernet uplink
CON_VLAN = PREFIX + "vlan"        # mode 1 with a VLAN tag: the tagged side
CON_BR = PREFIX + "bridge"        # mode 2 bridge: the bridge itself
CON_BR_ETH = PREFIX + "br-eth"    # mode 2 bridge: Ethernet port in the bridge
CON_LLDP = PREFIX + "lldp"        # short LLDP listen on an idle Ethernet port
CON_WG = PREFIX + "wg"            # WireGuard VPN
MODE_CONS = (CON_ETH, CON_HOTSPOT, CON_UPLINK, CON_VLAN, CON_BR, CON_BR_ETH, CON_LLDP)
BRIDGE_IF = "nomadbr0"
NAT_UNIT = "nomad-wifi-share-nat@{}.service"
POLICY_DIR = "/run/nomad-wifi-share-policy"

MODE_NAMES = {None: "Not sharing", "wifi2eth": "Wi-Fi -> Ethernet", "hotspot": "Ethernet -> Hotspot"}

os.environ["PATH"] = os.environ.get("PATH", "/usr/bin:/bin") + ":/usr/sbin:/sbin"
RUN_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "nomad-wifi-share")
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


def clients(dev: str, ap: bool = False, stations_dev: str | None = None) -> list[dict]:
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
        rc, out, _ = run(["iw", "dev", stations_dev or dev, "station", "dump"], timeout=5)
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


def _con_names() -> set[str]:
    return {r[0] for r in terse("-f", "NAME", "connection", "show") if r}


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
    _clear_policy()
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
    vlan = vlan_id(cfg)
    lan = f"{e}.{vlan}" if vlan else e
    lldp = ["connection.lldp", "enable" if cfg.get("lldp", True) else "disable"]
    ipcfg = ["ipv6.method", "disabled", "ipv4.addresses", _cidr(cfg["share_ip"], cfg["share_mask"])]
    ipcfg += ["ipv4.method", "shared"] if cfg["share_dhcp"] else ["ipv4.method", "manual", "ipv4.never-default", "yes"]
    if vlan:
        # Untagged port profile (no IP, LLDP on) plus the tagged VLAN that is shared.
        _add("type", "ethernet", "ifname", e, "con-name", CON_ETH, "autoconnect", "yes",
             "connection.autoconnect-priority", "100", "ipv4.method", "disabled", "ipv6.method", "disabled", *lldp)
        _add("type", "vlan", "dev", e, "id", str(vlan), "ifname", lan, "con-name", CON_VLAN,
             "autoconnect", "yes", *ipcfg)
    else:
        _add("type", "ethernet", "ifname", e, "con-name", CON_ETH, "autoconnect", "yes",
             "connection.autoconnect-priority", "100", *lldp, *ipcfg)
    st["nat"] = [lan]
    st["mode"] = "wifi2eth"
    st["lan"] = lan
    save_state(st)
    write_policy(lan, cfg)
    ok2, err = nat("start", lan)
    if not ok2:
        restore(log=lambda m: None)
        raise NetError(f"NAT failed: {err[:100]}")
    ok, note = _up(CON_ETH, e)
    if ok and vlan:
        ok, note2 = _up(CON_VLAN, e)
        note = note or note2
    if not ok:
        restore(log=lambda m: None)
        raise NetError(note)
    dhcp = "DHCP on" if cfg["share_dhcp"] else "DHCP off"
    tag = f", VLAN {vlan}" if vlan else ""
    return f"Sharing Wi-Fi to Ethernet ({dhcp}{tag}). " + (note or "")


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
    if cfg.get("hs_bridge"):
        return _start_bridge_hotspot(cfg, w, e)
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
        _add(*args, "connection.lldp", "enable")
        ok, note = _up(CON_UPLINK, e)
        if note:
            notes.append(note)
    elif e and not carrier(e):
        notes.append("Plug in the Ethernet uplink")
    elif e:
        nm("device", "connect", e, timeout=30)
    _add(*_ap_args(cfg, w), "ipv4.method", "shared",
         "ipv4.addresses", f"{cfg['hs_ip'].strip()}/24", "ipv6.method", "disabled")
    st["nat"] = [w]
    st["mode"] = "hotspot"
    st["lan"] = w
    save_state(st)
    write_policy(w, cfg)
    ok2, err = nat("start", w)
    if not ok2:
        notes.append(f"NAT helper: {err[:60]}")
    ok, note = _up(CON_HOTSPOT, w, timeout=60)
    if not ok:
        restore(log=lambda m: None)
        raise NetError("Hotspot failed: " + note)
    return f"Hotspot {cfg['hs_ssid']} is on. " + " ".join(notes)


def _ap_args(cfg: dict, w: str) -> list[str]:
    ch = str(cfg["hs_channel"]).strip() or "6"
    return ["type", "wifi", "ifname", w, "con-name", CON_HOTSPOT, "autoconnect", "no",
            "ssid", cfg["hs_ssid"], "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
            "802-11-wireless.channel", ch,
            "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", cfg["hs_password"],
            "wifi-sec.proto", "rsn", "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp",
            "wifi-sec.pmf", "disable"]


def _start_bridge_hotspot(cfg: dict, w: str, e: str | None) -> str:
    """Mode 2, bridge: the hotspot and the Ethernet port share one network.
    No NAT and no DHCP of ours; Wi-Fi devices get addresses from the real
    network, like plugging them into the switch."""
    if not e:
        raise NetError("Bridge mode needs the Ethernet port")
    stop_sharing(keep_saved=True)
    st = load_state()
    remember(st, w)
    remember(st, e)
    br = ["type", "bridge", "ifname", BRIDGE_IF, "con-name", CON_BR, "autoconnect", "no",
          "bridge.stp", "no", "ipv6.method", "disabled", "connection.lldp", "enable"]
    if cfg["uplink_dhcp"]:
        # Keep the bridge (and the hotspot on it) up even when the wired
        # network's DHCP is slow or missing; NM's default gives up after 45 s.
        br += ["ipv4.method", "auto", "ipv4.dhcp-timeout", "infinity", "ipv4.may-fail", "yes"]
    else:
        br += ["ipv4.method", "manual", "ipv4.addresses", _cidr(cfg["uplink_ip"], cfg["uplink_mask"])]
        if S.valid_ip(cfg["uplink_gw"]):
            br += ["ipv4.gateway", cfg["uplink_gw"].strip()]
        dns = [d for d in cfg["uplink_dns"].replace(",", " ").split() if S.valid_ip(d)]
        if dns:
            br += ["ipv4.dns", " ".join(dns)]
    _add(*br)
    _add("type", "ethernet", "ifname", e, "con-name", CON_BR_ETH, "autoconnect", "no",
         "master", BRIDGE_IF, "slave-type", "bridge")
    _add(*_ap_args(cfg, w), "master", BRIDGE_IF, "slave-type", "bridge")
    st["nat"], st["mode"], st["lan"], st["bridge"] = [], "hotspot", BRIDGE_IF, True
    save_state(st)
    notes = []
    nm("connection", "up", CON_BR, timeout=20)          # may wait for DHCP; carry on
    ok, note = _up(CON_BR_ETH, e)
    if note:
        notes.append(note)
    ok, note = _up(CON_HOTSPOT, w, timeout=60)
    if not ok:
        restore(log=lambda m: None)
        raise NetError("Hotspot failed: " + note)
    return f"Hotspot {cfg['hs_ssid']} is on, bridged to Ethernet (no NAT). " + " ".join(notes)


def stop_sharing(keep_saved: bool = False) -> list[str]:
    """Stop whichever mode is running. With keep_saved, the record of the
    original profiles is kept so a later restore() still brings them back."""
    if not keep_saved:
        return restore(log=lambda m: None)
    st = load_state()
    for name in MODE_CONS:
        if name in _con_names():
            nm("connection", "delete", "id", name, timeout=20)
    for dev in st.get("nat", []):
        nat("stop", dev)
    st["nat"], st["mode"], st["lan"], st["bridge"] = [], None, None, False
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
    side = st.get("lan") or {"wifi2eth": e, "hotspot": w}.get(st.get("mode"))
    out["lan"] = side
    out["lan_ip"] = ipv4(side) if side else []
    # Did NetworkManager drop our mode by itself (e.g. a failed bridge)?
    want = {"wifi2eth": CON_VLAN if side and "." in side else CON_ETH, "hotspot": CON_HOTSPOT}.get(st.get("mode"))
    if want:
        active = {r[0] for r in terse("-f", "NAME", "connection", "show", "--active") if r}
        out["lost"] = want not in active and want not in {d_["con"] for d_ in devs}
    else:
        out["lost"] = False
    if out["lost"]:
        out["clients"] = []
        out["vlan"] = ""
        out["bridge"] = bool(st.get("bridge"))
        out["vpn"] = vpn_state()
        return out
    out["bridge"] = bool(st.get("bridge"))
    if st.get("mode") == "hotspot" and st.get("bridge"):
        out["clients"] = clients(BRIDGE_IF, ap=True, stations_dev=w)
        out["bridge_ip"] = ipv4(BRIDGE_IF)
    else:
        out["clients"] = clients(side, ap=st.get("mode") == "hotspot") if side else []
    out["vlan"] = side.split(".", 1)[1] if side and "." in side else ""
    out["vpn"] = vpn_state()
    return out


# ---- sharing rules (blocks, limits, forwards, reservations, names) ---------

def vlan_id(cfg: dict) -> int:
    v = str(cfg.get("share_vlan", "0")).strip()
    return int(v) if v.isdigit() and 1 <= int(v) <= 4094 else 0


def build_policy(cfg: dict, bridge: bool = False) -> dict:
    """The rules file the root helper loads for the shared side."""
    block, limits, res = [], [], []
    for mac, d in (cfg.get("devices") or {}).items():
        m = S.norm_mac(mac)
        if not m or not isinstance(d, dict):
            continue
        ip = d.get("ip", "") if d.get("reserve") and S.valid_ip(d.get("ip", "")) else ""
        if d.get("block"):
            block.append(m)
        if ip:
            res.append(dict(mac=m, ip=ip.strip(), name=S.hostname(d.get("name", ""))))
        down, up = _mbit(d.get("down")), _mbit(d.get("up"))
        if ip and (down or up):
            limits.append(dict(ip=ip.strip(), down_kbytes=down * 125, up_kbytes=up * 125))
    fwd = []
    for f in cfg.get("forwards") or []:
        port, to_port = S.check_port(f.get("port", "")), S.check_port(f.get("to_port", "") or f.get("port", ""))
        proto = str(f.get("proto", "")).lower()
        if port and to_port and S.valid_ip(f.get("ip", "")) and proto in ("tcp", "udp", "both"):
            fwd.append(dict(proto=proto, port=port, ip=f["ip"].strip(), to_port=to_port))
    dns = [dict(name=d["name"].strip(), ip=d["ip"].strip()) for d in cfg.get("dns_names") or []
           if S.NAME_RE.match(d.get("name", "").strip()) and S.valid_ip(d.get("ip", ""))]
    return dict(nat=not bridge, block=block, limits=limits, forwards=fwd, reservations=res, dns=dns,
                all_down_kbytes=_mbit(cfg.get("limit_all_down")) * 125,
                all_up_kbytes=_mbit(cfg.get("limit_all_up")) * 125)


def _mbit(v) -> int:
    """'10 Mb/s' or '10' -> 10; 'Off', '0' or junk -> 0."""
    digits = ""
    for ch in str(v or "").strip():
        if not ch.isdigit():
            break
        digits += ch
    return min(int(digits), 10000) if digits else 0


def write_policy(dev: str, cfg: dict) -> dict:
    pol = build_policy(cfg)
    path = os.path.join(POLICY_DIR, dev + ".json")
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(pol, f)
        os.chmod(tmp, 0o660)
        os.replace(tmp, path)
    except OSError as e:
        raise NetError(f"Can't write sharing rules ({e.strerror}). Reinstall the app.")
    return pol


def _clear_policy() -> None:
    try:
        for n in os.listdir(POLICY_DIR):
            if n.endswith(".json"):
                os.remove(os.path.join(POLICY_DIR, n))
    except OSError:
        pass


def apply_rules(cfg: dict) -> str:
    """Load changed rules while sharing runs. DHCP reservations and DNS names
    need the DHCP server restarted, which blips the shared side briefly."""
    st = load_state()
    lan = st.get("lan")
    if not st.get("mode") or not lan:
        return "Saved. The rules load when sharing starts."
    if st.get("bridge"):
        return "Saved. Bridge mode passes traffic straight through, so these rules apply in NAT mode only."
    old_path = os.path.join(POLICY_DIR, lan + ".json")
    try:
        old = json.load(open(old_path))
    except (OSError, ValueError):
        old = {}
    new = write_policy(lan, cfg)
    rc, _, err = run(["systemctl", "--no-ask-password", "reload", NAT_UNIT.format(lan)], timeout=30)
    if rc != 0:
        raise NetError(f"Rules not loaded: {err[:100]}")
    dhcp_changed = (old.get("reservations"), old.get("dns")) != (new["reservations"], new["dns"])
    if dhcp_changed:
        con = CON_VLAN if "." in lan else (CON_HOTSPOT if st.get("mode") == "hotspot" else CON_ETH)
        nm("connection", "up", con, timeout=45)
        return "Rules loaded. The DHCP server restarted to pick up reservations and names."
    return "Rules loaded."


# ---- switch info (LLDP) --------------------------------------------------------

def lldp(dev: str | None = None) -> list[dict]:
    """LLDP neighbours NetworkManager heard on dev (needs LLDP on the active profile)."""
    args = ["-t", "-m", "multiline", "device", "lldp", "list"] + (["ifname", dev] if dev else [])
    rc, out, _ = nm(*args, timeout=10)
    nbrs: dict[int, dict] = {}
    for line in out.splitlines():
        k, _, v = line.partition(":")
        if not k.startswith("NEIGHBOR["):
            continue
        idx = int(k[9:k.index("]")])
        field = k[k.index("].") + 2:]
        nbrs.setdefault(idx, {})[field] = v.replace("\\:", ":").strip()
    out_list = []
    for n in nbrs.values():
        out_list.append(dict(
            switch=n.get("SYSTEM-NAME") or n.get("CHASSIS-ID", ""),
            port=n.get("PORT-DESCRIPTION") or n.get("PORT-ID", ""),
            port_id=n.get("PORT-ID", ""),
            vlan=n.get("IEEE-802-1-PVID", "") or n.get("IEEE-802-1-VID", ""),
            vlan_name=n.get("IEEE-802-1-VLAN-NAME", ""),
            mgmt=n.get("MANAGEMENT-ADDRESSES", "") or n.get("MANAGEMENT-ADDRESS", ""),
            desc=n.get("SYSTEM-DESCRIPTION", "")[:120],
            caps=n.get("SYSTEM-CAPABILITIES", ""),
            dev=n.get("DEVICE", dev or "")))
    return out_list


def lldp_listen(seconds: int = 35) -> list[dict]:
    """Bring up a no-IP LLDP-only profile on an idle Ethernet port, listen,
    then put the port back. Switches send LLDP every 30 s."""
    e = eth_dev()
    if not e:
        raise NetError("No Ethernet port found")
    if not carrier(e):
        raise NetError("Plug the Ethernet cable into the switch first")
    found = lldp(e)
    if found:
        return found
    if load_state().get("mode") == "wifi2eth":
        raise NetError("No switch info yet. LLDP needs up to 30 s after the cable goes in.")
    st = load_state()
    remember(st, e)
    try:
        _add("type", "ethernet", "ifname", e, "con-name", CON_LLDP, "autoconnect", "no",
             "ipv4.method", "disabled", "ipv6.method", "disabled", "connection.lldp", "enable")
        nm("connection", "up", CON_LLDP, timeout=20)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            time.sleep(2)
            found = lldp(e)
            if found:
                break
    finally:
        nm("connection", "delete", "id", CON_LLDP, timeout=20)
        uuid = st["saved"].get(e)
        if uuid:
            nm("connection", "up", uuid, timeout=45)
        st = load_state()
        if not st.get("mode"):
            st["saved"].pop(e, None)
            save_state(st)
    return found


# ---- live numbers for the dashboard ------------------------------------------

def iface_bytes(dev: str) -> tuple[int, int]:
    try:
        rx = int(open(f"/sys/class/net/{dev}/statistics/rx_bytes").read())
        tx = int(open(f"/sys/class/net/{dev}/statistics/tx_bytes").read())
        return rx, tx
    except (OSError, ValueError):
        return 0, 0


def eth_speed(dev: str) -> str:
    try:
        sp = int(open(f"/sys/class/net/{dev}/speed").read())
        dup = open(f"/sys/class/net/{dev}/duplex").read().strip()
    except (OSError, ValueError):
        return ""
    if sp <= 0:
        return ""
    return (f"{sp // 1000} Gb/s" if sp >= 1000 else f"{sp} Mb/s") + ("" if dup == "full" else f" {dup}")


def wifi_rate(dev: str) -> str:
    rc, out, _ = run(["iw", "dev", dev, "link"], timeout=5)
    for l in out.splitlines():
        l = l.strip()
        if l.startswith("tx bitrate:"):
            p = l.split()
            return f"{p[2]} Mb/s" if len(p) > 2 else ""
    return ""


def ping(host: str, timeout: float = 1.0) -> float | None:
    """Round trip in ms, or None."""
    rc, out, _ = run(["ping", "-n", "-c", "1", "-W", str(max(1, int(timeout))), host], timeout=timeout + 2)
    for part in out.split():
        if part.startswith("time="):
            try:
                return float(part[5:])
            except ValueError:
                return None
    return None


# ---- WireGuard VPN ---------------------------------------------------------------

def wg_parse(text: str) -> str | None:
    """Error text if this isn't a usable WireGuard config, else None."""
    t = text.replace("\r", "")
    if "[Interface]" not in t or "[Peer]" not in t:
        return "Not a WireGuard config ([Interface] and [Peer] needed)"
    keys = {l.split("=", 1)[0].strip().lower() for l in t.splitlines() if "=" in l}
    for k in ("privatekey", "publickey", "endpoint", "allowedips"):
        if k not in keys:
            return f"WireGuard config is missing {k}"
    if len(t) > 8000:
        return "File is too big for a WireGuard config"
    return None


def wg_save(text: str) -> str:
    err = wg_parse(text)
    if err:
        raise NetError(err)
    os.makedirs(S.CONF_DIR, exist_ok=True)
    tmp = S.WG_CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write(text.replace("\r", ""))
    os.chmod(tmp, 0o600)
    os.replace(tmp, S.WG_CONF)
    return "WireGuard config saved"


def wg_info() -> dict:
    try:
        with open(S.WG_CONF) as f:
            t = f.read()
    except OSError:
        return {}
    info = {}
    for l in t.splitlines():
        k, _, v = l.partition("=")
        k = k.strip().lower()
        if k in ("endpoint", "address", "allowedips", "dns"):
            info[k] = v.strip()
    return info


def vpn_state() -> str:
    for r in terse("-f", "NAME,DEVICE,STATE", "connection", "show", "--active"):
        if len(r) >= 3 and r[0] == CON_WG:
            return "on" if r[2] == "activated" else r[2]
    return ""


def vpn_up() -> str:
    """Bring up WireGuard from the saved config. With AllowedIPs 0.0.0.0/0 the
    Pi and every shared device go out through the VPN."""
    import tempfile
    if not os.path.exists(S.WG_CONF):
        raise NetError("No WireGuard config yet")
    vpn_down()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "nomadwg0.conf")
        with open(S.WG_CONF) as src, open(path, "w") as dst:
            dst.write(src.read())
        os.chmod(path, 0o600)
        rc, _, err = nm("connection", "import", "type", "wireguard", "file", path, timeout=20)
    if rc != 0:
        raise NetError("WireGuard import failed: " + nm_error(err))
    nm("connection", "modify", "nomadwg0", "connection.id", CON_WG, "connection.autoconnect", "no", timeout=10)
    rc, _, err = nm("connection", "up", CON_WG, timeout=30)
    if rc != 0:
        vpn_down()
        raise NetError("VPN didn't start: " + nm_error(err))
    return "VPN on. Shared devices now go out through WireGuard."


def vpn_down() -> str:
    for n in (CON_WG, "nomadwg0"):
        if n in _con_names():
            nm("connection", "delete", "id", n, timeout=20)
    return "VPN off."
