"""Hardware: the GPIO paddle, the GPIO key-out (optocoupler) and a QMX (or
any rig that keys CW from a USB serial line and takes Kenwood-style CAT).

All of it is optional and runs as the normal user: GPIO through libgpiod
(user pi is in the gpio group), the USB serial port through termios (the
dialout group). Nothing is opened until a screen asks for it.
"""
from __future__ import annotations

import fcntl
import glob
import os
import struct
import termios
import time


# ---- GPIO -----------------------------------------------------------------------------

def _chip_for(line: int) -> str | None:
    """The gpiochip whose line N is the SoC's GPIO N (named "GPION")."""
    try:
        import gpiod
    except ImportError:
        return None
    for path in sorted(glob.glob("/dev/gpiochip*")):
        try:
            with gpiod.Chip(path) as c:
                if c.get_line_info(line).name == f"GPIO{line}":
                    return path
        except (OSError, ValueError):
            continue
    return None


class Paddle:
    """Dit and dah contacts to ground on two GPIO inputs with pull-ups."""

    def __init__(self, dit_pin: int, dah_pin: int):
        self.req = None
        self.pins = (dit_pin, dah_pin)
        self.error = ""
        try:
            import gpiod
            from gpiod.line import Bias, Direction
            chip = _chip_for(dit_pin)
            if not chip:
                raise OSError("no GPIO chip")
            self.req = gpiod.request_lines(chip, consumer="askelmer-morse", config={
                self.pins: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP, active_low=True)})
        except Exception as e:  # no gpiod, pins busy, not a Pi: keyboard still works
            self.req = None
            self.error = str(e) or e.__class__.__name__

    @property
    def ok(self) -> bool:
        return self.req is not None

    def read(self) -> tuple[bool, bool]:
        if not self.req:
            return False, False
        try:
            from gpiod.line import Value
            v = self.req.get_values(list(self.pins))
            return v[0] == Value.ACTIVE, v[1] == Value.ACTIVE
        except OSError:
            return False, False

    def close(self) -> None:
        if self.req:
            try:
                self.req.release()
            except Exception:
                pass
            self.req = None


class GpioKey:
    """Key-out: drives the LED of an optocoupler whose transistor closes the
    radio's key line. High = key down. Starts and ends key-up."""

    def __init__(self, pin: int):
        self.req = None
        self.pin = pin
        self.error = ""
        try:
            import gpiod
            from gpiod.line import Direction, Value
            chip = _chip_for(pin)
            if not chip:
                raise OSError("no GPIO chip")
            self.req = gpiod.request_lines(chip, consumer="askelmer-morse-key", config={
                pin: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE)})
        except Exception as e:
            self.req = None
            self.error = str(e) or e.__class__.__name__

    @property
    def ok(self) -> bool:
        return self.req is not None

    def set(self, down: bool) -> None:
        if self.req:
            from gpiod.line import Value
            try:
                self.req.set_value(self.pin, Value.ACTIVE if down else Value.INACTIVE)
            except OSError:
                pass

    def close(self) -> None:
        self.set(False)
        if self.req:
            try:
                self.req.release()
            except Exception:
                pass
            self.req = None


# ---- USB serial rig (QMX) -------------------------------------------------------------

TIOCMBIS = getattr(termios, "TIOCMBIS", 0x5416)
TIOCMBIC = getattr(termios, "TIOCMBIC", 0x5417)
TIOCM_DTR = getattr(termios, "TIOCM_DTR", 0x002)
TIOCM_RTS = getattr(termios, "TIOCM_RTS", 0x004)


def serial_ports() -> list[str]:
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))
    acm = sorted(glob.glob("/dev/ttyACM*"))
    return by_id + [p for p in acm if p not in {os.path.realpath(b) for b in by_id}]


def find_rig(port: str = "auto") -> str | None:
    """The rig's first USB serial port (the QMX's port 1 keys from DTR)."""
    if port and port != "auto":
        return port if os.path.exists(port) else None
    acm = sorted(glob.glob("/dev/ttyACM*"), key=lambda p: int("0" + "".join(c for c in p if c.isdigit())))
    return acm[0] if acm else None


class SerialRig:
    """Kenwood TS-480 style CAT over a USB serial port, plus CW keying on DTR
    (or RTS). Linux raises DTR when a port opens, so it is dropped at once."""

    def __init__(self, path: str, line: str = "DTR"):
        self.path = path
        self.bit = TIOCM_RTS if line == "RTS" else TIOCM_DTR
        self.fd = None
        self.error = ""
        try:
            fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            self.fd = fd
            self._line(False)
            attrs = termios.tcgetattr(fd)
            attrs[0] = 0                                     # iflag
            attrs[1] = 0                                     # oflag
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL   # cflag, no HUPCL
            attrs[3] = 0                                     # lflag
            attrs[4] = attrs[5] = termios.B9600
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            self._line(False)
        except OSError as e:
            self.error = e.strerror or str(e)
            if self.fd is not None:
                os.close(self.fd)
            self.fd = None

    @property
    def ok(self) -> bool:
        return self.fd is not None

    def _line(self, on: bool) -> None:
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, TIOCMBIS if on else TIOCMBIC, struct.pack("I", self.bit))
            except OSError:
                pass

    def set(self, down: bool) -> None:
        """Key down / up on the DTR (or RTS) line."""
        self._line(down)

    def cmd(self, text: str, reply: bool = False, timeout: float = 0.5) -> str:
        if self.fd is None:
            return ""
        try:
            os.read(self.fd, 4096)
        except OSError:
            pass
        try:
            os.write(self.fd, text.encode("ascii", "replace"))
        except OSError as e:
            self.error = e.strerror or str(e)
            return ""
        if not reply:
            return ""
        buf, end = b"", time.monotonic() + timeout
        while time.monotonic() < end and not buf.endswith(b";"):
            try:
                buf += os.read(self.fd, 256)
            except BlockingIOError:
                time.sleep(0.01)
            except OSError:
                break
        return buf.decode("ascii", "replace")

    def frequency(self) -> int | None:
        r = self.cmd("FA;", reply=True)
        digits = "".join(c for c in r if c.isdigit())
        return int(digits) if r.startswith("FA") and digits else None

    def set_speed(self, wpm: int) -> None:
        self.cmd(f"KS{int(wpm):03d};")

    def send_text(self, text: str) -> None:
        """The rig sends the text as CW at its keyer speed (KY command)."""
        clean = "".join(c for c in text.upper() if c.isalnum() or c in " .,?/=")
        # KY takes a limited buffer: send in short chunks
        for i in range(0, len(clean), 24):
            self.cmd(f"KY {clean[i:i + 24]};")
            time.sleep(0.05)

    def stop_text(self) -> None:
        """Stop a KY message: drop to receive."""
        self.cmd("RX;")

    def close(self) -> None:
        if self.fd is not None:
            self._line(False)
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
