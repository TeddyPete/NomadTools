"""Shared GPS time and location for the Nomad and Ask Elmer apps.

Plug a USB GPS (u-blox, BU-353 and the like) into the CardputerZero and every
app that carries this module sees the same fix. There is no service to
install and nothing runs as root:

* The first app that wants a fix takes a lock and reads the GPS (NMEA over
  USB serial). It writes the fix once a second to a small JSON file in the
  user's runtime folder, /run/user/<uid>/nomad-gps/fix.json.
* Other apps only read that file. When the reading app quits, the next one
  takes over.
* The last good fix is kept in ~/.config/nomad-gps/last.json, so the
  location is still there after a reboot without the GPS.

Only ports that say they are a GPS are opened automatically (by name or USB
id), so a radio's CAT or keying port is never touched. Another port can be
named in ~/.config/nomad-gps/config.json: {"port": "/dev/ttyUSB0", "baud": 4800}.

The M5Stack Cap LoRa-1262 has a GNSS receiver (ATGM336H) on the CardputerZero's
own serial port, /dev/ttyS0 at 115200, powered from the EXT 5 V output. It is
used when {"cap": true} is in config.json (set_cap(True), the apps' Settings),
or when the 5 V output is already on. Switching the 5 V output needs no root:
the gpio group may write /sys/class/leds/ext_5v_out/brightness.

    gps = nomadgps.shared()
    gps.fix()        # {"lat", "lon", "alt", "sats", "utc", "grid", ...} or None
    gps.location()   # (lat, lon, "GPS" | "last GPS fix") or None
    gps.utc()        # time.time(), corrected by the GPS clock when there is a fix
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time

FRESH_S = 5.0          # a fix file older than this is stale
GPS_WORDS = ("gps", "gnss", "u-blox", "ublox", "u_blox", "sirf", "globalsat", "navisys", "gns_", "g-mouse")
GPS_USB_IDS = {"1546"}  # u-blox vendor id
CAP_PORT, CAP_BAUD = "/dev/ttyS0", 115200
CAP_POWER = "/sys/class/leds/ext_5v_out/brightness"


def _runtime_dir() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base or not os.path.isdir(base):
        base = f"/tmp/nomad-gps-{os.getuid()}"
    return os.path.join(base, "nomad-gps")


def _config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "nomad-gps")


def _write_json(path: str, d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(d, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def _read_json(path: str) -> dict | None:
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def to_grid(lat: float, lon: float) -> str:
    lon += 180
    lat += 90
    a = chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
    b = str(int(lon % 20 // 2)) + str(int(lat % 10))
    c = chr(97 + int(lon % 2 * 12)) + chr(97 + int(lat % 1 * 24))
    return a + b + c


# ---- NMEA ------------------------------------------------------------------------------

def _checksum_ok(line: str) -> bool:
    if "*" not in line:
        return True
    body, _, cs = line[1:].partition("*")
    x = 0
    for ch in body:
        x ^= ord(ch)
    try:
        return x == int(cs[:2], 16)
    except ValueError:
        return False


def _deg(v: str, hemi: str, width: int) -> float | None:
    if not v:
        return None
    try:
        d = float(v[:width]) + float(v[width:]) / 60
    except ValueError:
        return None
    return -d if hemi in ("S", "W") else d


def parse_nmea(line: str, fix: dict) -> bool:
    """Update fix from one NMEA sentence. True when it changed position or time."""
    line = line.strip()
    if not line.startswith("$") or not _checksum_ok(line):
        return False
    f = line[1:].split("*")[0].split(",")
    kind = f[0][2:]
    if kind == "RMC" and len(f) >= 10:
        if f[1] and f[9] and len(f[9]) == 6 and len(f[1]) >= 6:
            try:
                import calendar
                d, mo, y = int(f[9][:2]), int(f[9][2:4]), 2000 + int(f[9][4:6])
                h, mi, s = int(f[1][:2]), int(f[1][2:4]), float(f[1][4:])
                fix["utc"] = calendar.timegm((y, mo, d, h, mi, 0, 0, 0, 0)) + s
                fix["utc_at"] = time.time()
            except ValueError:
                pass
        fix["valid"] = f[2] == "A"
        if fix["valid"]:
            lat, lon = _deg(f[3], f[4], 2), _deg(f[5], f[6], 3)
            if lat is not None and lon is not None:
                fix["lat"], fix["lon"] = lat, lon
                try:
                    fix["knots"] = float(f[7] or 0)
                except ValueError:
                    pass
        return True
    if kind == "GGA" and len(f) >= 10:
        try:
            fix["quality"] = int(f[6] or 0)
            fix["sats"] = int(f[7] or 0)
            if f[9]:
                fix["alt"] = float(f[9])
        except ValueError:
            pass
        return True
    return False


# ---- finding the GPS ---------------------------------------------------------------------

def _usb_info(dev: str) -> str:
    """Manufacturer, product and vendor id of a tty's USB device, lower case."""
    name = os.path.basename(os.path.realpath(dev))
    p = os.path.realpath(f"/sys/class/tty/{name}/device")
    out = []
    for _ in range(6):
        for leaf in ("manufacturer", "product", "idVendor"):
            try:
                out.append(open(os.path.join(p, leaf)).read().strip())
            except OSError:
                pass
        if out:
            break
        p = os.path.dirname(p)
    return " ".join(out).lower()


def config() -> dict:
    return _read_json(os.path.join(_config_dir(), "config.json")) or {}


def cap_power() -> bool | None:
    """Is the EXT 5 V output (which powers a Cap) on? None when there is no such switch."""
    try:
        return open(CAP_POWER).read().strip() not in ("", "0")
    except OSError:
        return None


def set_cap(enabled: bool) -> str:
    """Use (or stop using) a Cap LoRa-1262's GNSS. Turns the 5 V output on when enabling.
    Returns a short status for the screen."""
    cfg = config()
    cfg["cap"] = bool(enabled)
    _write_json(os.path.join(_config_dir(), "config.json"), cfg)
    if not enabled:
        return "Cap GNSS off"
    if not os.path.exists(CAP_PORT):
        return "No serial port for a Cap"
    if cap_power() is False:
        try:
            with open(CAP_POWER, "w") as fh:
                fh.write("1")
        except OSError:
            return "Cap GNSS on, but 5 V out could not be switched"
    return "Cap GNSS on"


def _cap_wanted(cfg: dict) -> bool:
    return os.path.exists(CAP_PORT) and (bool(cfg.get("cap")) or (cfg.get("cap") is None and cap_power() is True))


def gps_ports() -> list:
    """Serial ports that identify as a GPS, the one named in config.json, and a Cap's GNSS."""
    cfg = config()
    ports = [cfg["port"]] if cfg.get("port") else []
    if _cap_wanted(cfg):
        ports.append(CAP_PORT)
    for p in sorted(glob.glob("/dev/serial/by-id/*")):
        low = p.lower()
        if any(w in low for w in GPS_WORDS) or "1546" in low:
            ports.append(p)
    for p in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")):
        info = _usb_info(p)
        if any(w in info for w in GPS_WORDS) or any(i in info.split() for i in GPS_USB_IDS):
            ports.append(p)
    seen, out = set(), []
    for p in ports:
        rp = os.path.realpath(p)
        if rp not in seen and os.path.exists(rp):
            seen.add(rp)
            out.append(p)
    return out


def _open_serial(path: str, baud: int):
    import termios
    fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[0] = termios.IGNPAR
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    speed = getattr(termios, f"B{baud}", termios.B9600)
    attrs[4] = attrs[5] = speed
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


# ---- the shared reader ---------------------------------------------------------------------

class Gps:
    def __init__(self):
        self.fix_path = os.path.join(_runtime_dir(), "fix.json")
        self.lock_path = os.path.join(_runtime_dir(), "reader.lock")
        self.last_path = os.path.join(_config_dir(), "last.json")
        self._lock_fd = None
        self.reading = False      # this process owns the GPS
        self.port = None
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="nomad-gps")
        self._thread.start()

    def close(self) -> None:
        self._stop = True

    # -- what apps call --
    def fix(self) -> dict | None:
        """The live fix (fresh and valid), or None."""
        d = _read_json(self.fix_path)
        if not d or time.time() - d.get("written", 0) > FRESH_S or not d.get("valid"):
            return None
        if d.get("lat") is not None and d.get("lon") is not None:
            d["grid"] = to_grid(d["lat"], d["lon"])
        return d

    def status(self) -> str:
        d = _read_json(self.fix_path)
        if not d or time.time() - d.get("written", 0) > FRESH_S:
            return "No GPS"
        if not d.get("valid"):
            return f"GPS: searching, {d.get('sats', 0)} sats"
        return f"GPS fix, {d.get('sats', 0)} sats"

    def last(self) -> dict | None:
        return _read_json(self.last_path)

    def location(self):
        """(lat, lon, source) from the live GPS or the last fix, else None."""
        d = self.fix()
        if d:
            return d["lat"], d["lon"], "GPS"
        d = self.last()
        if d and d.get("lat") is not None:
            return d["lat"], d["lon"], "last GPS fix"
        return None

    def utc(self) -> float:
        """Seconds since the epoch, from the GPS clock when there is a fix."""
        d = _read_json(self.fix_path)
        now = time.time()
        if d and d.get("utc") and now - d.get("written", 0) <= FRESH_S:
            return d["utc"] + (now - d.get("utc_at", now))
        return now

    def clock_offset(self) -> float | None:
        """GPS time minus this computer's clock, seconds, or None."""
        d = _read_json(self.fix_path)
        if d and d.get("utc") and time.time() - d.get("written", 0) <= FRESH_S:
            return d["utc"] - d.get("utc_at", time.time())
        return None

    # -- the reader thread --
    def _try_lock(self) -> bool:
        import fcntl
        try:
            os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def _unlock(self) -> None:
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None
        self.reading = False

    def _run(self) -> None:
        while not self._stop:
            if self._lock_fd is None and not self._try_lock():
                time.sleep(3)          # another app is reading the GPS
                continue
            ports = gps_ports()
            if not ports:
                self._unlock()          # let another app look later
                time.sleep(5)
                continue
            self.reading = True
            for p in ports:
                if self._stop:
                    break
                self._read_port(p)
            self._unlock()
            time.sleep(2)

    def _read_port(self, path: str) -> None:
        cfg = config()
        if path == CAP_PORT:
            bauds = [CAP_BAUD, 9600]
        elif cfg.get("baud") and path == cfg.get("port"):
            bauds = [int(cfg["baud"])]
        else:
            bauds = [9600, 4800, 38400]
        for baud in bauds:
            try:
                fd = _open_serial(path, baud)
            except (OSError, ValueError, ImportError):
                return
            self.port = path
            fix: dict = {"port": path, "valid": False}
            buf, heard, start, last_write, last_save = b"", False, time.time(), 0.0, 0.0
            try:
                while not self._stop:
                    try:
                        chunk = os.read(fd, 1024)
                        if not chunk:
                            time.sleep(0.1)
                    except BlockingIOError:
                        chunk = b""
                        time.sleep(0.1)
                    except OSError:
                        return            # unplugged
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if parse_nmea(line.decode("ascii", "replace"), fix):
                            heard = True
                    buf = buf[-4096:]
                    now = time.time()
                    if not heard and now - start > 4:
                        break             # no NMEA at this speed
                    if heard and now - last_write >= 1:
                        fix["written"] = now
                        _write_json(self.fix_path, fix)
                        last_write = now
                        if fix.get("valid") and fix.get("lat") is not None and now - last_save > 60:
                            _write_json(self.last_path, {"lat": fix["lat"], "lon": fix["lon"],
                                                         "alt": fix.get("alt"), "at": now})
                            last_save = now
            finally:
                os.close(fd)
            if heard:
                return


_shared: Gps | None = None


def shared() -> Gps:
    global _shared
    if _shared is None:
        _shared = Gps()
    return _shared
