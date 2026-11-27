"""What every display driver offers.

A driver talks to one display. Methods raise DisplayError with a short,
readable message (it goes straight onto the 320x170 screen).

caps (what the UI offers for this display):
  power    on / off
  input    list and switch inputs
  volume   up / down (and level when the display reports it)
  mute     audio mute on / off
  avmute   picture + sound mute (projector shutter, "picture off")
  picture  picture modes
  message  show a short message on the screen
  info     model, hours, errors ...
"""
from __future__ import annotations

from dataclasses import dataclass, field


class DisplayError(Exception):
    pass


@dataclass
class Display:
    """One saved display (also what discovery returns)."""
    name: str
    kind: str                 # pjlink | lg | samsung | sony | roku
    host: str
    port: int = 0             # 0 = the protocol default
    mac: str = ""             # for Wake-on-LAN
    room: str = ""
    secret: str = ""          # PJLink password, Sony PSK, LG client key, Samsung token
    model: str = ""
    id: str = ""              # stable id inside the saved list
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "name", "kind", "host", "port", "mac", "room",
                                              "secret", "model", "extra")}

    @classmethod
    def from_dict(cls, d: dict) -> "Display":
        keys = ("id", "name", "kind", "host", "port", "mac", "room", "secret", "model", "extra")
        return cls(**{k: d[k] for k in keys if k in d})


KIND_NAMES = {
    "pjlink": "PJLink projector",
    "lg": "LG webOS TV",
    "samsung": "Samsung TV",
    "sony": "Sony Bravia",
    "roku": "Roku TV",
}
KIND_SHORT = {"pjlink": "PJL", "lg": "LG", "samsung": "SAM", "sony": "SONY", "roku": "ROKU"}
SECRET_LABEL = {"pjlink": "PJLink password", "sony": "Pre-shared key", "lg": "Client key",
                "samsung": "Token"}


class Driver:
    kind = ""
    caps: frozenset = frozenset()
    default_port = 0
    needs_pairing = False        # LG / Samsung: the TV asks once to allow us

    def __init__(self, d: Display, timeout: float = 4.0):
        self.d = d
        self.timeout = timeout

    @property
    def port(self) -> int:
        return self.d.port or self.default_port

    # Each returns a short text for the screen, or raises DisplayError.
    def status(self) -> dict:
        """{"power": on|off|warming|cooling|standby|unknown, "input": str,
        "volume": int|None, "mute": bool|None, ...}"""
        raise DisplayError("Not supported")

    def power(self, on: bool) -> str:
        raise DisplayError("Not supported")

    def inputs(self) -> list[tuple[str, str]]:
        """[(input_id, label)]"""
        raise DisplayError("Not supported")

    def set_input(self, input_id: str) -> str:
        raise DisplayError("Not supported")

    def volume(self, step: int) -> str:
        raise DisplayError("Not supported")

    def mute(self, on: bool | None = None) -> str:
        """on=None toggles."""
        raise DisplayError("Not supported")

    def avmute(self, on: bool | None = None) -> str:
        raise DisplayError("Not supported")

    def picture_modes(self) -> tuple[list[str], str]:
        """(modes, current)"""
        raise DisplayError("Not supported")

    def set_picture(self, mode: str) -> str:
        raise DisplayError("Not supported")

    def message(self, text: str) -> str:
        raise DisplayError("Not supported")

    def info(self) -> list[tuple[str, str]]:
        return [("Type", KIND_NAMES.get(self.kind, self.kind)), ("Address", f"{self.d.host}:{self.port}")]

    def pair(self) -> str:
        """Ask the TV to allow this device (LG / Samsung). Returns text; may
        update self.d.secret, the caller saves it."""
        return "No pairing needed"
