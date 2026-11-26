"""Info pulls after a login, per brand.

Nothing here saves a login: the caller decides that from the login form.
Crestron ERRLOG is deliberately not pulled."""
from __future__ import annotations

import json
import re
import socket
import time
from collections import defaultdict

from . import oui, scan, util
from .ui import DIM

CRESTRON_CMDS = ["VER", "IPCONFIG", "PROGCOMMENTS", "UPTIME", "IPTABLE"]


def _show(out, cmd: str, text: str) -> None:
    out.head(cmd)
    lines = [l for l in text.replace("\r", "").split("\n")]
    # drop the echoed command and the trailing prompt
    if lines and cmd.strip().lower() in lines[0].strip().lower():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.match(r"^\S*[>#]\s*$", lines[-1].strip()):
        lines.pop()
    for l in lines:
        out.line(l.rstrip())


# ------------------------------------------------------------------ Crestron

CR_PROMPT = r"(?m)^[\w\-\.]+>\s*$"


def crestron(out, ip: str, user: str = "", password: str = "", mode: str = "SSH") -> None:
    c = util.LineClient()
    try:
        if mode == "SSH":
            out.dim(f"SSH to {ip} as {user or '(blank)'}...")
            try:
                c.open_ssh(ip, user, password)
            except Exception as e:
                out.bad(f"SSH failed: {e}")
                if util.tcp_open(ip, 41795, 1.5):
                    out.warn("Trying the console port 41795 (older gear without login)...")
                    c.close()
                    return crestron(out, ip, user, password, "Console 41795")
                return
        else:
            out.dim(f"Console port 41795 on {ip}...")
            c.telnet(ip, 41795)
            c.send("\r\n")
        text = c.read_until([CR_PROMPT, r"(?i)(login|username|user name)\s*:", r"(?i)password\s*:"], 6)
        if re.search(r"(?i)(login|username|user name)\s*:\s*$", text):
            c.send(user + "\r\n")
            text = c.read_until([r"(?i)password\s*:", CR_PROMPT], 5)
        if re.search(r"(?i)password\s*:\s*$", text):
            c.send(password + "\r\n")
            text = c.read_until([CR_PROMPT, r"(?i)(fail|invalid|denied)"], 6)
        m = re.search(r"(?m)^([\w\-\.]+)>\s*$", text)
        if not m:
            out.bad("No Crestron prompt. Login failed or not a Crestron console.")
            out.dim(text.strip()[-200:])
            return
        out.ok(f"Connected: prompt {m.group(1)}>")
        for cmd in CRESTRON_CMDS:
            if out.stopped:
                break
            c.send(cmd + "\r\n")
            text = c.read_until(CR_PROMPT, 12)
            _show(out, cmd, text)
            if cmd == "IPTABLE":
                iptable_summary(out, text)
        out.dim("(ERRLOG is not pulled automatically; use the terminal if you need it)")
    except OSError as e:
        out.bad(f"Connection failed: {e}")
    finally:
        c.close()


def parse_iptable(text: str) -> list[dict]:
    """Rows of a Crestron IPTABLE: CIP_ID |Type |Status |DevID |Port |IP Address/SiteName"""
    rows = []
    for l in text.replace("\r", "").split("\n"):
        if "|" not in l or not re.search(r"(?i)\b(online|offline)\b", l):
            continue
        parts = [p.strip() for p in l.split("|")]
        status = next((p for p in parts if p.upper() in ("ONLINE", "OFFLINE")), "")
        addr = parts[-1] if parts else ""
        rows.append({"id": parts[0], "type": parts[1] if len(parts) > 1 else "",
                     "online": status.upper() == "ONLINE", "addr": addr})
    return rows


def iptable_summary(out, text: str) -> None:
    rows = parse_iptable(text)
    if not rows:
        return
    on = [r for r in rows if r["online"]]
    off = [r for r in rows if not r["online"]]
    out.head(f"IP table: {len(on)} online, {len(off)} offline")
    for r in off:
        ip = r["addr"]
        reach = ""
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
            ok = "bytes from" in util.run(["ping", "-c", "1", "-W", "1", ip], 3)
            reach = "  (answers ping)" if ok else "  (no ping)"
        out.bad(f"OFFLINE  IP ID {r['id']:>4}  {r['type'][:6]:6} {ip}{reach}")
    for r in on:
        out.ok(f"online   IP ID {r['id']:>4}  {r['type'][:6]:6} {r['addr']}")


# ------------------------------------------------------------------ Extron

EXTRON_CMDS = [("Model / part", "N"), ("Firmware", "Q"), ("Firmware (all)", "*Q"), ("Info", "I"),
               ("Unit name", "\x1bCN\r"), ("MAC address", "\x1bCH\r"), ("IP address", "\x1bCI\r"),
               ("Subnet", "\x1bCS\r"), ("Gateway", "\x1bCG\r"), ("DHCP", "\x1bDH\r"), ("Date/time", "\x1bCT\r")]


def extron(out, ip: str, user: str = "", password: str = "", mode: str = "Telnet") -> None:
    c = util.LineClient()
    try:
        if mode == "SSH 22023":
            out.dim(f"SSH 22023 to {ip}...")
            c.open_ssh(ip, user or "admin", password, port=22023)
        else:
            out.dim(f"Telnet to {ip}:23...")
            c.telnet(ip, 23)
        ban = c.read_until([r"(?i)password\s*:", r"Extron Electronics.*\n"], 5, quiet=1.5)
        if re.search(r"(?i)password\s*:", ban):
            if not password:
                out.bad("The device asks for a password.")
                return
            c.send(password + "\r")
            ban2 = c.read_until([r"(?i)(login (administrator|user))", r"(?i)password", r"E\d\d"], 5, quiet=1.0)
            if re.search(r"(?i)password\s*:", ban2) or "E10" in ban2:
                out.bad("Password refused.")
                return
            ban += ban2
        for l in ban.strip().splitlines():
            if l.strip():
                out.info(l.strip())
        for label, cmd in EXTRON_CMDS:
            if out.stopped:
                break
            c.send(cmd)
            r = c.read_until([r"\n"], 2.5, quiet=0.6).strip()
            if r.startswith("E1") or r.startswith("E0") and len(r) <= 4:
                r += "  (not supported)"
            out.line(f"{label:16} {r}")
    except Exception as e:
        out.bad(f"Connection failed: {e}")
    finally:
        c.close()


# ------------------------------------------------------------------ Q-SYS

def qsys(out, ip: str, user: str = "", password: str = "", mode: str = "QRC 1710") -> None:
    try:
        s = socket.create_connection((ip, 1710), timeout=4)
    except OSError as e:
        out.bad(f"QRC port 1710 not reachable: {e}")
        return
    s.settimeout(0.5)
    buf = b""

    def call(method, params, mid):
        nonlocal buf
        s.sendall(json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": mid}).encode() + b"\0")
        end = time.monotonic() + 5
        while time.monotonic() < end:
            while b"\0" in buf:
                part, buf = buf.split(b"\0", 1)
                try:
                    j = json.loads(part)
                except ValueError:
                    continue
                if j.get("method") == "EngineStatus":
                    show_status(j.get("params", {}), "EngineStatus")
                if j.get("id") == mid:
                    return j
            try:
                chunk = s.recv(8192)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
        return {}

    def show_status(r, head="StatusGet"):
        out.head(head)
        for k in ("Platform", "State", "DesignName", "DesignCode", "IsRedundant", "IsEmulator"):
            if k in r:
                out.line(f"{k:12} {r[k]}")
        st = r.get("Status", {})
        if st:
            code = st.get("Code", "")
            txt = st.get("String", "")
            (out.ok if code == 0 else out.warn)(f"{'Status':12} {code} {txt}")

    try:
        if user:
            r = call("Logon", {"User": user, "Password": password}, 1)
            if "error" in r:
                out.bad(f"Logon failed: {r['error'].get('message', r['error'])}")
                return
            out.ok("Logged on")
        r = call("StatusGet", 0, 2)
        if "error" in r:
            out.bad(f"StatusGet: {r['error'].get('message', r['error'])}")
            if not user:
                out.warn("This core may need a login (Q-SYS Administrator user with QRC access).")
            return
        show_status(r.get("result", {}))
        r = call("Component.GetComponents", 0, 3)
        comps = r.get("result") or []
        if comps:
            out.head(f"Named components ({len(comps)})")
            types = defaultdict(int)
            for cpt in comps:
                types[cpt.get("Type", "?")] += 1
            for t, n in sorted(types.items(), key=lambda x: -x[1])[:15]:
                out.line(f"{n:4} x {t}")
    finally:
        s.close()


# ------------------------------------------------------------------ Biamp

BIAMP_CMDS = ["DEVICE get hostname", "DEVICE get version", "DEVICE get serialNumber",
              "DEVICE get networkStatus", "DEVICE get activeFaultList", "DEVICE get knownRedundantDeviceStates"]


def biamp(out, ip: str, user: str = "", password: str = "", mode: str = "SSH") -> None:
    c = util.LineClient()
    try:
        if mode == "SSH":
            out.dim(f"SSH to {ip} as {user or 'default'}...")
            c.open_ssh(ip, user or "default", password)
        else:
            out.dim(f"Telnet (TTP) to {ip}:23...")
            c.telnet(ip, 23)
        ban = c.read_until([r"Welcome to the Tesira Text Protocol Server.*\n", r"(?i)login:"], 6, quiet=1.5)
        if re.search(r"(?i)login:", ban):
            c.send((user or "default") + "\r\n")
            c.read_until(r"(?i)password:", 3)
            c.send(password + "\r\n")
            ban = c.read_until(r"Welcome.*\n", 5, quiet=1.5)
        if "Tesira" not in ban:
            out.warn("No Tesira welcome banner; trying anyway")
        else:
            out.ok("Connected to Tesira Text Protocol")
        for cmd in BIAMP_CMDS:
            if out.stopped:
                break
            c.send(cmd + "\r\n")
            r = c.read_until([r"(?m)^(\+OK|-ERR).*$"], 6)
            _show(out, cmd, r)
    except Exception as e:
        out.bad(f"Connection failed: {e}")
    finally:
        c.close()


# ------------------------------------------------------------------ Shure

SHURE_GETS = ["MODEL", "DEVICE_ID", "FW_VER", "SERIAL_NUM", "IP_ADDR_NET_AUDIO_PRIMARY",
              "IP_SUBNET_NET_AUDIO_PRIMARY", "NA_DEVICE_NAME", "PRESET", "DEVICE_AUDIO_MUTE", "BATT_RUN_TIME"]


def shure(out, ip: str, user: str = "", password: str = "", mode: str = "TCP 2202") -> None:
    try:
        s = socket.create_connection((ip, 2202), timeout=4)
    except OSError as e:
        out.bad(f"Shure command port 2202 not reachable: {e}")
        out.dim("Third-party control may be off in Shure Designer / the web page.")
        return
    s.settimeout(0.6)
    got = 0
    try:
        for g in SHURE_GETS:
            if out.stopped:
                break
            s.sendall(f"< GET {g} >\r\n".encode())
            data = b""
            end = time.monotonic() + 1.5
            while time.monotonic() < end:
                try:
                    chunk = s.recv(4096)
                except socket.timeout:
                    if data:
                        break
                    continue
                if not chunk:
                    break
                data += chunk
            reps = re.findall(r"< REP [^>]* >", data.decode("latin-1", "replace"))
            for r in reps[:4]:
                inner = r[6:-2].strip()
                out.line(inner)
                got += 1
            if not reps:
                out.dim(f"{g}: no reply")
        if not got:
            out.warn("No replies. This model may use different command names.")
    finally:
        s.close()


# ------------------------------------------------------------------ Netgear AV Line

NG_PROMPT = r"(?m)^\(?[\w\-\+ ]*\)?\s*[>#]\s*$"


def netgear(out, ip: str, user: str = "", password: str = "", mode: str = "SSH") -> None:
    c = util.LineClient()
    try:
        if mode == "SSH":
            out.dim(f"SSH to {ip} as {user or 'admin'}...")
            c.open_ssh(ip, user or "admin", password)
        else:
            out.dim(f"Telnet to {ip}:23...")
            c.telnet(ip, 23)
        text = c.read_until([NG_PROMPT, r"(?i)user(name)?\s*:\s*$", r"(?i)password\s*:\s*$"], 8)
        if re.search(r"(?i)user(name)?\s*:\s*$", text):
            c.send((user or "admin") + "\r\n")
            text = c.read_until([r"(?i)password\s*:\s*$", NG_PROMPT], 5)
        if re.search(r"(?i)password\s*:\s*$", text):
            c.send(password + "\r\n")
            text = c.read_until([NG_PROMPT, r"(?i)(fail|invalid|denied)"], 6)
        if not re.search(NG_PROMPT, text):
            out.bad("No switch prompt; login failed?")
            out.dim(text.strip()[-200:])
            return
        if not re.search(r"#\s*$", text.strip()):
            c.send("enable\r\n")
            t = c.read_until([r"#\s*$", r"(?i)password\s*:\s*$"], 4)
            if re.search(r"(?i)password\s*:\s*$", t):
                c.send(password + "\r\n")
                c.read_until([r"#\s*$", r">\s*$"], 4)
        c.send("terminal length 0\r\n")
        c.read_until(NG_PROMPT, 4)

        def cmd(x, wait=15):
            c.send(x + "\r\n")
            return c.read_until(NG_PROMPT, wait)

        ver = cmd("show version")
        mgmt = cmd("show ip management")
        status = cmd("show interfaces status all", 20)
        poe = cmd("show poe port info all", 20)
        if "Invalid" in poe or "%" in poe[:80]:
            poe = cmd("show poe port all", 20)
        macs = cmd("show mac-addr-table", 25)
        if "Invalid" in macs:
            macs = cmd("show mac address-table", 25)
    except Exception as e:
        out.bad(f"Connection failed: {e}")
        return
    finally:
        c.close()

    def field(text, *names):
        for n in names:
            m = re.search(rf"(?im)^\s*{n}[ .]*\s+(.+)$", text)
            if m:
                return m.group(1).strip()
        return ""

    out.head("Switch")
    out.line(f"Model     {field(ver, 'Machine Model', 'Machine Type', 'System Description')}")
    out.line(f"Serial    {field(ver, 'Serial Number')}")
    out.line(f"Firmware  {field(ver, 'Software Version')}")
    out.ok(f"IP        {field(mgmt, 'IP Address') or ip}  mask {field(mgmt, 'Subnet Mask')}  gw {field(mgmt, 'Default Gateway')}")
    out.line(f"Mgmt VLAN {field(mgmt, 'Management VLAN ID')}  config {field(mgmt, 'Current Network Configuration Protocol', 'Network Configuration Protocol Current')}")

    PORT = r"(\d+/\d+(?:/\d+)?)"
    ports: dict[str, dict] = defaultdict(lambda: {"link": "", "speed": "", "poe": "", "watts": "", "macs": []})
    for l in status.splitlines():
        m = re.match(rf"^\s*{PORT}\s+(.*)$", l)
        if not m:
            continue
        rest = m.group(2)
        d = ports[m.group(1)]
        d["link"] = "Up" if re.search(r"\bUp\b", rest) else "Down" if re.search(r"\bDown\b", rest) else ""
        sp = re.findall(r"\b(10G|2\.5G|5G|1000|100|10)\s+(Full|Half)\b", rest)
        if sp:
            d["speed"] = f"{sp[-1][0]} {sp[-1][1]}"
    for l in poe.splitlines():
        m = re.match(rf"^\s*{PORT}\s+(.*)$", l)
        if not m:
            continue
        rest = m.group(2)
        d = ports[m.group(1)]
        st = re.search(r"(Delivering Power|Searching|Disabled|Fault|Overload|Short|Off|Disable|Enable)", rest, re.I)
        d["poe"] = st.group(1) if st else ""
        nums = re.findall(r"\b\d+\.\d+\b", rest)
        if nums:
            d["watts"] = nums[0]
    for l in macs.splitlines():
        m = re.match(rf"^\s*(\d+)\s+([0-9A-Fa-f]{{2}}(?:[:\-][0-9A-Fa-f]{{2}}){{5}})\s+{PORT}", l)
        if m:
            ports[m.group(3)]["macs"].append((m.group(2).replace("-", ":").lower(), m.group(1)))

    def pkey(p):
        return tuple(int(x) for x in p.split("/"))

    out.head("Ports: link  speed  PoE  W  devices")
    for p in sorted(ports, key=pkey):
        d = ports[p]
        if not d["link"] and not d["macs"] and not d["poe"]:
            continue
        color = None
        line = f"{p:7} {d['link'] or '-':4} {d['speed'] or '':9} {d['poe'][:10]:10} {d['watts'] or '':6}"
        if d["link"] == "Up":
            out.ok(line)
        else:
            out.dim(line)
        for mac, vlan in d["macs"][:8]:
            v = oui.vendor(mac)
            nm = scan.name_for_mac(mac)
            ipx = scan.ip_for_mac(mac)
            out.line(f"         {mac} v{vlan} {v[:20]} {ipx} {nm if nm != ipx else ''}".rstrip())
        if len(d["macs"]) > 8:
            out.dim(f"         ... {len(d['macs']) - 8} more MACs (uplink?)")
    if not ports:
        out.warn("Couldn't read the port tables; raw output follows.")
    out.head("Raw: show interfaces status all")
    for l in status.splitlines()[1:]:
        out.dim(l)
    out.head("Raw: PoE")
    for l in poe.splitlines()[1:]:
        out.dim(l)
    if not scan.KNOWN:
        out.dim("Tip: run IP scan first so MACs are matched to device names.")


BRANDS = {
    "Crestron": (crestron, ["SSH", "Console 41795"], "admin"),
    "Extron": (extron, ["Telnet", "SSH 22023"], "admin"),
    "Q-SYS": (qsys, ["QRC 1710"], ""),
    "Biamp": (biamp, ["SSH", "Telnet"], "default"),
    "Shure": (shure, ["TCP 2202"], ""),
    "Netgear": (netgear, ["SSH", "Telnet"], "admin"),
}
