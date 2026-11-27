"""PJLink class 1 and class 2 (projectors, some flat panels). TCP 4352.

The projector greets with "PJLINK 0" (no password) or "PJLINK 1 <random>"
(password: the first command is prefixed with MD5(random + password)).
"""
from __future__ import annotations

import hashlib
import socket

from .base import DisplayError, Driver

ERRORS = {"ERR1": "Command not supported", "ERR2": "Bad parameter",
          "ERR3": "Not possible right now (warming up or off?)", "ERR4": "Projector failure",
          "ERRA": "Wrong PJLink password"}
POWER = {"0": "off", "1": "on", "2": "cooling", "3": "warming"}
INPUT_TYPES = {"1": "RGB", "2": "Video", "3": "Digital", "4": "Storage", "5": "Network", "6": "Internal"}
ERST_NAMES = ("Fan", "Lamp", "Temperature", "Cover", "Filter", "Other")
ERST_LEVEL = {"0": "OK", "1": "Warning", "2": "ERROR"}


def input_label(code: str) -> str:
    return f"{INPUT_TYPES.get(code[:1], 'Input')} {code[1:]}"


class PJLink(Driver):
    kind = "pjlink"
    default_port = 4352
    caps = frozenset({"power", "input", "mute", "avmute", "info", "volume"})

    def __init__(self, d, timeout=4.0):
        super().__init__(d, timeout)
        self._class = None

    # ---- transport ----
    def session(self, cmds: list[str]) -> list[str]:
        """Send commands ("%1POWR ?") on one connection, return the replies
        (the part after '=')."""
        try:
            s = socket.create_connection((self.d.host, self.port), self.timeout)
        except OSError as e:
            raise DisplayError(f"No answer from {self.d.host} ({e.__class__.__name__})")
        s.settimeout(self.timeout)
        f = s.makefile("rb")
        try:
            hello = self._line(f)
            if not hello.upper().startswith("PJLINK"):
                raise DisplayError(f"Not a PJLink device: {hello[:30]}")
            parts = hello.split()
            if len(parts) >= 2 and parts[1].upper() == "ERRA":
                raise DisplayError(ERRORS["ERRA"])
            prefix = ""
            if len(parts) >= 3 and parts[1] == "1":
                if not self.d.secret:
                    raise DisplayError("Projector needs a PJLink password")
                prefix = hashlib.md5((parts[2] + self.d.secret).encode()).hexdigest()
            out = []
            for i, c in enumerate(cmds):
                s.sendall(((prefix if i == 0 else "") + c + "\r").encode())
                r = self._line(f)
                if r.upper().startswith("PJLINK ERRA"):
                    raise DisplayError(ERRORS["ERRA"])
                if "=" not in r:
                    raise DisplayError(f"Odd reply: {r[:30]}")
                head, val = r.split("=", 1)
                if head[2:6].upper() != c[2:6].upper():
                    raise DisplayError(f"Odd reply: {r[:30]}")
                out.append(val.strip())
            return out
        except socket.timeout:
            raise DisplayError("Projector stopped answering")
        except OSError as e:
            raise DisplayError(f"Connection lost ({e.__class__.__name__})")
        finally:
            try:
                s.close()
            except OSError:
                pass

    @staticmethod
    def _line(f) -> str:
        b = bytearray()
        while True:
            c = f.read(1)
            if not c:
                if b:
                    break
                raise DisplayError("Connection closed")
            if c == b"\r":
                break
            if c != b"\n":
                b += c
            if len(b) > 512:
                break
        return b.decode("latin-1").strip()

    def query(self, cmd: str, cls: int = 1) -> str:
        return self.session([f"%{cls}{cmd}"])[0]

    def do(self, cmd: str, cls: int = 1) -> str:
        r = self.query(cmd, cls)
        if r.upper() in ERRORS:
            raise DisplayError(ERRORS[r.upper()])
        return r

    @property
    def pclass(self) -> int:
        if self._class is None:
            try:
                r = self.query("CLSS ?")
                self._class = 2 if r.strip() == "2" else 1
            except DisplayError:
                self._class = 1
        return self._class

    # ---- driver ----
    def status(self):
        r = self.session(["%1POWR ?", "%1INPT ?", "%1AVMT ?", "%1ERST ?"])
        p, inp, av, er = r
        st = {"power": POWER.get(p, "unknown"), "input": "", "mute": None, "avmute": None}
        if inp.upper() not in ERRORS:
            st["input"] = input_label(inp)
        if av.upper() not in ERRORS and len(av) == 2:
            st["avmute"] = av in ("31", "11")
            st["mute"] = av in ("31", "21")
        if er.upper() not in ERRORS and len(er) == 6 and er != "000000":
            st["errors"] = ", ".join(f"{n} {ERST_LEVEL.get(v, v)}" for n, v in zip(ERST_NAMES, er) if v != "0")
        return st

    def power(self, on):
        self.do(f"POWR {1 if on else 0}")
        return "Power on sent (warming up)" if on else "Power off sent (cooling down)"

    def inputs(self):
        r = self.do("INST ?")
        codes = r.split()
        names = {}
        if self.pclass == 2 and codes:
            try:
                replies = self.session([f"%2INNM ?{c}" for c in codes])
                names = {c: n for c, n in zip(codes, replies) if n and n.upper() not in ERRORS}
            except DisplayError:
                pass
        return [(c, f"{names[c]} ({input_label(c)})" if c in names else input_label(c)) for c in codes]

    def set_input(self, input_id):
        self.do(f"INPT {input_id}", 2 if input_id[1:].isalpha() else 1)
        return f"Input {input_label(input_id)}"

    def _avmt(self, kind: str, on):
        # kind "2" = audio, "1" = video, "3" = both
        if on is None:
            cur = self.do("AVMT ?")
            on = not (cur in (kind + "1", "31"))
        self.do(f"AVMT {kind}{1 if on else 0}")
        return on

    def mute(self, on=None):
        on = self._avmt("2", on)
        return "Audio muted" if on else "Audio unmuted"

    def avmute(self, on=None):
        on = self._avmt("3", on)
        return "Picture and sound muted" if on else "Picture and sound back"

    def volume(self, step):
        if self.pclass < 2:
            raise DisplayError("Volume needs PJLink class 2")
        for _ in range(abs(step)):
            self.do(f"SVOL {1 if step > 0 else 0}", 2)
        return "Volume up" if step > 0 else "Volume down"

    def info(self):
        out = super().info()
        cmds = ["%1NAME ?", "%1INF1 ?", "%1INF2 ?", "%1INFO ?", "%1CLSS ?", "%1LAMP ?", "%1ERST ?"]
        r = self.session(cmds)
        ok = lambda v: v and v.upper() not in ERRORS
        for label, v in zip(("Name", "Maker", "Model", "Info", "PJLink class"), r[:5]):
            if ok(v):
                out.append((label, v))
        if ok(r[5]):
            nums = r[5].split()
            lamps = [f"{nums[i]} h{'' if nums[i + 1] == '1' else ' (off)'}" for i in range(0, len(nums) - 1, 2)]
            out.append(("Lamp hours", ", ".join(lamps)))
        if ok(r[6]) and len(r[6]) == 6:
            for n, v in zip(ERST_NAMES, r[6]):
                out.append((n, ERST_LEVEL.get(v, v)))
        if self.pclass == 2:
            r2 = self.session(["%2SNUM ?", "%2SVER ?", "%2FILT ?", "%2IRES ?", "%2RRES ?"])
            for label, v in zip(("Serial", "Software", "Filter hours", "Input signal", "Native res."), r2):
                if ok(v):
                    out.append((label, v))
        return out


def search(timeout: float = 1.5) -> dict[str, str]:
    """PJLink class 2 UDP search: {ip: mac}."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", 4352))     # replies go to port 4352
        except OSError:
            return found
        s.settimeout(0.3)
        from .wol import broadcasts
        for b in broadcasts():
            try:
                s.sendto(b"%2SRCH\r", (b, 4352))
            except OSError:
                pass
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, (ip, _) = s.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            t = data.decode("latin-1").strip()
            if t.upper().startswith("%2ACKN="):
                found[ip] = t.split("=", 1)[1].strip().lower()
    finally:
        s.close()
    return found
