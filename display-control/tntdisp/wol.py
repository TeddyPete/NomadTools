"""Wake-on-LAN magic packets (no root needed)."""
from __future__ import annotations

import ipaddress
import re
import socket
import subprocess


def norm_mac(mac: str) -> str | None:
    h = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(h) != 12:
        return None
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)).lower()


def broadcasts() -> list[str]:
    """255.255.255.255 plus the directed broadcast of every IPv4 interface."""
    out = ["255.255.255.255"]
    try:
        txt = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        txt = ""
    for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", txt):
        net = ipaddress.IPv4Interface(m.group(1)).network
        if not net.is_loopback and net.prefixlen < 31:
            out.append(str(net.broadcast_address))
    return out


def wake(mac: str, host: str = "") -> str:
    m = norm_mac(mac)
    if not m:
        raise ValueError(f"Bad MAC address: {mac or '(none)'}")
    pkt = b"\xff" * 6 + bytes.fromhex(m.replace(":", "")) * 16
    targets = broadcasts()
    if host:
        targets.append(host)            # some TVs only listen unicast
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sent = 0
    try:
        for _ in range(3):
            for t in targets:
                for port in (9, 7):
                    try:
                        s.sendto(pkt, (t, port))
                        sent += 1
                    except OSError:
                        pass
    finally:
        s.close()
    if not sent:
        raise OSError("Could not send (no network?)")
    return f"Wake-on-LAN sent to {m}"
