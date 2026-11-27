"""Inline tap: bridge the built-in Ethernet port and a USB Ethernet adapter
into one invisible wire (no IP, no spanning tree), then capture on the bridge.

The bridge itself is made by a small root helper run by a systemd unit,
tnt-packet-capture-tap@<adapter>.service (a polkit rule lets the netdev group
start and stop it). The unit is bound to the adapter, so unplugging the
adapter takes the bridge down and gives the built-in port back to
NetworkManager. Wi-Fi is never touched, so SSH over Wi-Fi keeps working.

Stopping a capture does NOT take the bridge down: the two devices on either
side stay connected until you turn the bridge off or unplug the adapter.
"""
from __future__ import annotations

import os
import subprocess
import time

BRIDGE = "br-tnt"
UNIT = "tnt-packet-capture-tap@{}.service"
# The CardputerZero's own Ethernet chip sits on the internal USB hub port 1-1.1.
BUILTIN_USB_PATH = "/usb1/1-1/1-1.1/"


def _wired(name: str) -> bool:
    base = f"/sys/class/net/{name}"
    if not os.path.exists(base + "/device"):
        return False                     # lo, bridges, tunnels
    if os.path.isdir(base + "/wireless") or os.path.isdir(base + "/phy80211"):
        return False
    try:
        return open(base + "/type").read().strip() == "1"   # ARPHRD_ETHER
    except OSError:
        return False


def wired_ports() -> list[str]:
    try:
        return sorted(n for n in os.listdir("/sys/class/net") if _wired(n))
    except OSError:
        return []


def builtin() -> str:
    """The CardputerZero's own Ethernet port."""
    ports = wired_ports()
    for n in ports:
        if BUILTIN_USB_PATH in os.path.realpath(f"/sys/class/net/{n}/device"):
            return n
    return "eth0" if "eth0" in ports or not ports else ports[0]


def adapters() -> list[str]:
    """USB Ethernet adapters plugged in (every wired port but the built-in)."""
    b = builtin()
    return [n for n in wired_ports() if n != b]


def bridge_up() -> bool:
    return os.path.isdir(f"/sys/class/net/{BRIDGE}/bridge")


def bridge_ports() -> list[str]:
    try:
        return sorted(os.listdir(f"/sys/class/net/{BRIDGE}/brif"))
    except OSError:
        return []


def adapter_in_use() -> str:
    b = builtin()
    for p in bridge_ports():
        if p != b:
            return p
    return ""


def default_route_dev() -> str:
    try:
        r = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=5)
        parts = r.stdout.split()
        return parts[parts.index("dev") + 1] if "dev" in parts else ""
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return ""


def why_not(adapter: str) -> str:
    """'' if it's safe to bridge built-in + adapter, else the reason."""
    b = builtin()
    if not adapter:
        return "Plug in a USB Ethernet adapter first."
    if adapter == b:
        return "That's the built-in port."
    if not os.path.exists(f"/sys/class/net/{adapter}"):
        return f"{adapter} is gone."
    route = default_route_dev()
    if route in (b, adapter):
        return (f"{route} carries this device's own network (default route). Bridging it would cut you off. "
                "Connect the CardputerZero to Wi-Fi first.")
    return ""


def _systemctl(verb: str, adapter: str, timeout: float = 25) -> str:
    try:
        r = subprocess.run(["systemctl", "--no-ask-password", verb, UNIT.format(adapter)],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    if r.returncode == 0:
        return ""
    return (r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else \
        f"systemctl {verb} failed ({r.returncode})"


def start(adapter: str) -> None:
    """Bring the bridge up (raises with a readable message on failure)."""
    err = why_not(adapter)
    if err:
        raise RuntimeError(err)
    if bridge_up() and adapter in bridge_ports():
        return
    err = _systemctl("start", adapter)
    if err:
        if "interactive authentication" in err.lower() or "access denied" in err.lower():
            err = "Not allowed to start the bridge. Reinstall the app (it adds a polkit rule)."
        raise RuntimeError(err)
    end = time.monotonic() + 8
    while time.monotonic() < end:
        if bridge_up() and len(bridge_ports()) >= 2:
            return
        time.sleep(0.2)
    raise RuntimeError("The bridge did not come up.")


def stop(adapter: str = "") -> str:
    adapter = adapter or adapter_in_use()
    if not adapter:
        return ""
    return _systemctl("stop", adapter)


def status() -> dict:
    ports = bridge_ports()
    links = {}
    for p in ports:
        try:
            carrier = open(f"/sys/class/net/{p}/carrier").read().strip() == "1"
        except OSError:
            carrier = False
        try:
            speed = int(open(f"/sys/class/net/{p}/speed").read().strip()) if carrier else 0
        except (OSError, ValueError):
            speed = 0
        links[p] = (carrier, speed)
    return {"up": bridge_up(), "ports": ports, "links": links, "builtin": builtin(), "adapters": adapters()}
