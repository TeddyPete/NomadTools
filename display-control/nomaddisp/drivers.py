"""Pick the driver for a display."""
from __future__ import annotations

from .base import Display, Driver
from .lgwebos import LGWebOS
from .pjlink import PJLink
from .roku import Roku
from .samsung import Samsung
from .sony import Sony

DRIVERS = {c.kind: c for c in (PJLink, LGWebOS, Samsung, Sony, Roku)}


def driver(d: Display, timeout: float = 4.0) -> Driver:
    return DRIVERS[d.kind](d, timeout)
