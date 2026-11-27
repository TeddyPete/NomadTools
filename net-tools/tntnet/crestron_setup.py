"""Crestron batch tools: NVX first-time setup and settings capture.

* Find Crestron gear with autodiscovery (UDP 41794) and check over SSH
  whether each one still needs its first administrator account (factory
  default: log in as "Crestron" with a blank password and the device asks
  for a new user name and password).
* Create that account on the ones that need it (only after the user
  confirms on screen; the password is typed on the keyboard, never saved).
* Settings capture: log in to each device (REST API over HTTPS, the console
  as a fallback) and write a CSV plus the raw JSON to the site's reports.
"""
from __future__ import annotations

import csv
import http.cookiejar
import io
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request

from . import av, reports, util

CREATE_RX = re.compile(r"(?i)(create|new)\s+(a\s+)?(new\s+)?(administrator|admin|user)|"
                       r"(enter|choose)\s+(a\s+|the\s+)?(new\s+)?user\s*name|administrator account")
PROMPT_RX = r"(?m)^[\w\-\.]+>\s*$"


# ---------------------------------------------------------------- discovery

def discover(out, iface: str = "", nvx_only: bool = False) -> list[dict]:
    i = util.best_iface(iface or None)
    ips = [i.ip] if i and i.ip else [x.ip for x in util.interfaces() if x.ip]
    out.dim("Crestron autodiscovery (UDP 41794)...")
    found = av.crestron_discover(ips, 4.0, lambda: out.stopped)
    devs = []
    for ip, d in sorted(found.items(), key=lambda kv: tuple(int(x) for x in kv[0].split("."))):
        if nvx_only and "NVX" not in d["model"].upper():
            continue
        devs.append(dict(d, ip=ip))
    return devs


def probe(ip: str) -> str:
    """'needs setup', 'secured', 'auth off' or 'no ssh'. Never sends a
    password or creates anything: it only looks at what the login shows."""
    c = util.LineClient()
    try:
        try:
            c.open_ssh(ip, "Crestron", "", timeout=6)
        except Exception as e:
            if "Authentication" in type(e).__name__ or "auth" in str(e).lower():
                return "secured"
            return "no ssh"
        text = c.read_until([CREATE_RX.pattern, PROMPT_RX, r"(?i)password\s*:"], 6, quiet=2)
        if CREATE_RX.search(text):
            return "needs setup"
        if re.search(PROMPT_RX, text):
            return "auth off"
        return "secured"
    except Exception:
        return "no ssh"
    finally:
        c.close()


def scan(out, iface: str = "", nvx_only: bool = True) -> list[dict]:
    devs = discover(out, iface, nvx_only)
    if not devs:
        out.warn("No NVX found." if nvx_only else "No Crestron devices found.")
        return []
    out.replace_last(f"{len(devs)} found. Checking which need setup...", (140, 140, 150))
    for d in devs:
        if out.stopped:
            break
        d["state"] = probe(d["ip"])
    out.replace_last(f"{len(devs)} {'NVX' if nvx_only else 'Crestron'} device(s)", (140, 140, 150))
    colors = {"needs setup": (255, 190, 60), "secured": (110, 230, 120), "auth off": (255, 95, 95)}
    for d in devs:
        st = d.get("state", "?")
        out.item(f"{d['ip']:15} {st}\n  {d['model'][:20]} {d['host'][:16]}", None,
                 colors.get(st, (235, 235, 235)))
    n = sum(1 for d in devs if d.get("state") == "needs setup")
    if n:
        out.warn(f"{n} need their first admin account. Use 'Set up new NVX'.")
    if any(d.get("state") == "auth off" for d in devs):
        out.warn("'auth off' = no login at all. Turn authentication on in its web page.")
    return devs


# ---------------------------------------------------------------- first-time setup

def create_admin(ip: str, user: str, password: str, log) -> bool:
    """Answer the factory first-login prompts with a new admin account."""
    c = util.LineClient()
    try:
        c.open_ssh(ip, "Crestron", "", timeout=8)
        text = c.read_until([CREATE_RX.pattern, PROMPT_RX], 8, quiet=2)
        if not CREATE_RX.search(text):
            log(f"{ip}: no setup prompt, left alone")
            return False
        sent_user = False
        pw_count = 0
        t0 = time.monotonic()
        buf = text
        while time.monotonic() - t0 < 30:
            tail = buf[-200:]
            if not sent_user and re.search(r"(?i)user\s*name\s*:?\s*$|user\s*:?\s*$", tail):
                c.send(user + "\r\n")
                sent_user = True
                buf = ""
            elif re.search(r"(?i)password\s*:?\s*$", tail) and pw_count < 2:
                c.send(password + "\r\n")
                pw_count += 1
                buf = ""
            elif re.search(PROMPT_RX, tail) or re.search(r"(?i)(created|success)", tail):
                break
            elif re.search(r"(?i)(fail|invalid|not match|does not meet|error)", tail):
                log(f"{ip}: device said: {tail.strip()[-80:]}")
                return False
            more = c.read_until([r"(?i)(user\s*name|user|password)\s*:?\s*$", PROMPT_RX,
                                 r"(?i)(created|success|fail|invalid|not match|error)"], 6, quiet=1.5)
            if not more:
                break
            buf += more
    except Exception as e:
        log(f"{ip}: {e}")
        return False
    finally:
        c.close()
    # check the new login really works
    time.sleep(2)
    v = util.LineClient()
    try:
        v.open_ssh(ip, user, password, timeout=8)
        ok = bool(re.search(PROMPT_RX, v.read_until(PROMPT_RX, 8)))
    except Exception:
        ok = False
    finally:
        v.close()
    return ok


# ---------------------------------------------------------------- settings capture

class Rest:
    """CresNext REST over HTTPS with the /userlogin.html cookie login."""

    def __init__(self, ip: str):
        self.ip = ip
        self.jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                              urllib.request.HTTPSHandler(context=ctx))

    def login(self, user: str, password: str) -> bool:
        base = f"https://{self.ip}"
        self.op.open(base + "/userlogin.html", timeout=8).read()
        track = next((c.value for c in self.jar if c.name == "TRACKID"), "")
        data = urllib.parse.urlencode({"login": user, "passwd": password}).encode()
        req = urllib.request.Request(base + "/userlogin.html", data=data, method="POST", headers={
            "Origin": base, "Referer": base + "/userlogin.html",
            "Content-Type": "application/x-www-form-urlencoded", "Cookie": f"TRACKID={track}"})
        try:
            self.op.open(req, timeout=8).read()
        except urllib.error.HTTPError as e:
            if e.code not in (302, 303):
                return False
        return any(c.name in ("userstr", "AuthByPasswd") for c in self.jar)

    def get(self, path: str) -> dict:
        try:
            with self.op.open(f"https://{self.ip}{path}", timeout=10) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return {}

    def logout(self) -> None:
        try:
            self.op.open(f"https://{self.ip}/logout", timeout=4).read()
        except Exception:
            pass


REST_PATHS = ["/Device/DeviceInfo", "/Device/Ethernet", "/Device/DeviceSpecific",
              "/Device/StreamTransmit", "/Device/StreamReceive", "/Device/SystemVersions",
              "/Device/NetworkAdapters"]


def flatten(obj, prefix: str = "", out: dict | None = None) -> dict:
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if v is not None:
                flatten(v, f"{prefix}[{i}]", out)
    else:
        out[prefix] = obj
    return out


def pick(flat: dict, *names) -> str:
    """First non-empty value whose key ends with one of names (case-insensitive)."""
    low = {k.lower(): v for k, v in flat.items()}
    for n in names:
        n = n.lower()
        for k, v in low.items():
            if (k.endswith("." + n) or k == n) and v not in (None, "", "0.0.0.0"):
                return str(v)
    return ""


COLUMNS = ["IP", "Hostname", "Model", "Mode", "Firmware", "Serial", "MAC", "DHCP", "Subnet", "Gateway",
           "Multicast address", "Stream URL", "Device ID", "Status"]


def row_from(d: dict, flat: dict, status: str) -> dict:
    mode = pick(flat, "DeviceMode", "Mode")
    return {
        "IP": d["ip"],
        "Hostname": pick(flat, "HostName", "Hostname") or d.get("host", ""),
        "Model": pick(flat, "Model", "ModelName") or d.get("model", ""),
        "Mode": mode,
        "Firmware": pick(flat, "DeviceVersion", "FirmwareVersion", "Version") or d.get("fw", ""),
        "Serial": pick(flat, "SerialNumber"),
        "MAC": pick(flat, "MacAddress") or d.get("mac", ""),
        "DHCP": pick(flat, "IsDhcpEnabled", "DhcpEnabled"),
        "Subnet": pick(flat, "SubnetMask"),
        "Gateway": pick(flat, "DefaultGateway", "StaticDefaultGateway"),
        "Multicast address": pick(flat, "MulticastAddress"),
        "Stream URL": pick(flat, "StreamLocation", "StreamUrl", "StreamURL"),
        "Device ID": pick(flat, "DeviceId", "DeviceID", "Id"),
        "Status": status,
    }


CONSOLE_CMDS = ["VER", "HOSTNAME", "IPCONFIG", "SERIALNUMBER"]


def console_capture(ip: str, user: str, password: str) -> dict:
    c = util.LineClient()
    flat = {}
    try:
        c.open_ssh(ip, user, password, timeout=8)
        c.read_until(PROMPT_RX, 8)
        for cmd in CONSOLE_CMDS:
            c.send(cmd + "\r\n")
            t = c.read_until(PROMPT_RX, 10)
            flat[f"console.{cmd}"] = t.strip()
        t = flat.get("console.IPCONFIG", "")
        for key, rx in (("SubnetMask", r"Subnet Mask[ .:]+([\d.]+)"), ("DefaultGateway", r"Default Gateway[ .:]+([\d.]+)"),
                        ("MacAddress", r"MAC Address[ .:]+([0-9A-Fa-f.:\-]+)"), ("IsDhcpEnabled", r"DHCP[ .:]+(\w+)")):
            m = re.search(rx, t, re.I)
            if m:
                flat[key] = m.group(1)
        m = re.search(r"Host Name[ .:]+(\S+)", flat.get("console.HOSTNAME", "") + "\n" + t, re.I)
        if m:
            flat["HostName"] = m.group(1)
        m = re.search(r"(\S+)\s+Cntrl Eng\s+\[v([\d.]+)", flat.get("console.VER", ""))
        if m:
            flat["Model"], flat["DeviceVersion"] = m.group(1), m.group(2)
    finally:
        c.close()
    return flat


def capture(out, cfg, devs: list[dict], user: str, password: str, label: str) -> str:
    rows, raw = [], {}
    for n, d in enumerate(devs, 1):
        if out.stopped:
            break
        ip = d["ip"]
        out.dim(f"{n}/{len(devs)} {ip} ...")
        flat, status = {}, ""
        try:
            r = Rest(ip)
            if r.login(user, password):
                for p in REST_PATHS:
                    flatten(r.get(p), "", flat)
                r.logout()
                status = "OK (REST)"
        except Exception:
            pass
        if not flat:
            try:
                flat = console_capture(ip, user, password)
                status = "OK (console)"
            except Exception as e:
                status = f"failed: {str(e)[:40]}"
        row = row_from(d, flat, status or "login failed")
        rows.append(row)
        raw[ip] = flat
        color = (110, 230, 120) if status.startswith("OK") else (255, 95, 95)
        out.replace_last(f"{ip:15} {row['Status']}", color)
        out.dim(f"  {row['Hostname'][:16]} {row['Model'][:14]}")
        if row["Multicast address"] or row["Mode"]:
            out.dim(f"  {row['Mode']} {row['Multicast address']}")
    if not rows:
        return ""
    d = reports.site_dir(cfg)
    os.makedirs(d, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = os.path.join(d, f"{stamp}-{reports.clean(label)}")
    with open(base + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with open(base + ".json", "w") as f:
        json.dump(raw, f, indent=1, default=str)
    out.ok(f"Saved {os.path.basename(base)}.csv (+ .json)")
    out.dim("Download it from Site & reports > Download reports.")
    return base + ".csv"


def csv_text(rows: list[dict]) -> str:
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return s.getvalue()
