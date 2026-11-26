"""HDMI display modes with exact refresh rates.

pygame only lists sizes, so 1080p60, 1080p50 and 1080p24 all look like
"1920x1080". SDL knows each mode's refresh rate, but only as a whole
number, so 59.94 and 60 both read "60". So:

- SDL (the copy pygame already loaded) lists the modes and switches to one.
- libdrm gives the exact timing of each mode (pixel clock and totals),
  which turns "60" into 60.00 or 59.94 and "24" into 24.00 or 23.98.

If either library can't be reached, callers fall back to plain sizes.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
from dataclasses import dataclass

SDL_WINDOW_FULLSCREEN = 0x00000001
DRM_MODE_FLAG_INTERLACE = 1 << 4


class SDL_DisplayMode(ctypes.Structure):
    _fields_ = [("format", ctypes.c_uint32), ("w", ctypes.c_int), ("h", ctypes.c_int),
                ("refresh_rate", ctypes.c_int), ("driverdata", ctypes.c_void_p)]


@dataclass(frozen=True)
class Mode:
    w: int
    h: int
    hz: float                 # exact when known (59.94), else SDL's whole number
    interlaced: bool = False
    index: int | None = None  # SDL mode index on the display

    @property
    def size(self) -> tuple[int, int]:
        return (self.w, self.h)

    @property
    def label(self) -> str:
        hz = f"{self.hz:.2f}".rstrip("0").rstrip(".") if self.hz else "?"
        return f"{self.w}x{self.h}{'i' if self.interlaced else 'p'}{hz}"


def _loaded_sdl_path() -> str | None:
    """The SDL2 library this process already has loaded (pygame's copy)."""
    try:
        with open("/proc/self/maps") as f:
            for line in f:
                p = line.split()[-1]
                if "libSDL2-2" in p and p.startswith("/") and "_image" not in p:
                    return p
    except OSError:
        pass
    return None


def _load():
    for name in (_loaded_sdl_path(), "libSDL2-2.0.so.0", ctypes.util.find_library("SDL2")):
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        lib.SDL_GetWindowFromID.restype = ctypes.c_void_p
        lib.SDL_GetWindowFromID.argtypes = [ctypes.c_uint32]
        lib.SDL_GetWindowDisplayIndex.argtypes = [ctypes.c_void_p]
        lib.SDL_GetNumDisplayModes.argtypes = [ctypes.c_int]
        lib.SDL_GetDisplayMode.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(SDL_DisplayMode)]
        lib.SDL_SetWindowDisplayMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(SDL_DisplayMode)]
        lib.SDL_GetWindowDisplayMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(SDL_DisplayMode)]
        lib.SDL_SetWindowFullscreen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.SDL_GetCurrentVideoDriver.restype = ctypes.c_char_p
        return lib
    return None


_lib = None


def lib():
    global _lib
    if _lib is None:
        _lib = _load() or False
    return _lib or None


# ---- libdrm: exact timings of the HDMI connector's modes ----

class drmModeModeInfo(ctypes.Structure):
    _fields_ = [("clock", ctypes.c_uint32),
                ("hdisplay", ctypes.c_uint16), ("hsync_start", ctypes.c_uint16),
                ("hsync_end", ctypes.c_uint16), ("htotal", ctypes.c_uint16), ("hskew", ctypes.c_uint16),
                ("vdisplay", ctypes.c_uint16), ("vsync_start", ctypes.c_uint16),
                ("vsync_end", ctypes.c_uint16), ("vtotal", ctypes.c_uint16), ("vscan", ctypes.c_uint16),
                ("vrefresh", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("type", ctypes.c_uint32),
                ("name", ctypes.c_char * 32)]


class drmModeRes(ctypes.Structure):
    _fields_ = [("count_fbs", ctypes.c_int), ("fbs", ctypes.POINTER(ctypes.c_uint32)),
                ("count_crtcs", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_uint32)),
                ("count_connectors", ctypes.c_int), ("connectors", ctypes.POINTER(ctypes.c_uint32)),
                ("count_encoders", ctypes.c_int), ("encoders", ctypes.POINTER(ctypes.c_uint32)),
                ("min_width", ctypes.c_uint32), ("max_width", ctypes.c_uint32),
                ("min_height", ctypes.c_uint32), ("max_height", ctypes.c_uint32)]


class drmModeConnector(ctypes.Structure):
    _fields_ = [("connector_id", ctypes.c_uint32), ("encoder_id", ctypes.c_uint32),
                ("connector_type", ctypes.c_uint32), ("connector_type_id", ctypes.c_uint32),
                ("connection", ctypes.c_int), ("mmWidth", ctypes.c_uint32), ("mmHeight", ctypes.c_uint32),
                ("subpixel", ctypes.c_int), ("count_modes", ctypes.c_int),
                ("modes", ctypes.POINTER(drmModeModeInfo))]


def exact_hz(m) -> float:
    """Refresh (field rate for interlaced) from a mode's clock and totals."""
    if not m.htotal or not m.vtotal:
        return float(m.vrefresh)
    hz = m.clock * 1000.0 / (m.htotal * m.vtotal)
    if m.flags & DRM_MODE_FLAG_INTERLACE:
        hz *= 2
    return hz


def drm_modes(card_index: int | None = None) -> list[tuple[int, int, float, bool, float]]:
    """(w, h, exact Hz, interlaced, pixel clock MHz) for each mode of the
    first connected connector, in the kernel's order (the order SDL's
    kmsdrm driver indexes them in). Read-only; needs no DRM master."""
    if card_index is None:
        card_index = int(os.environ.get("SDL_KMSDRM_DEVICE_INDEX", "0") or 0)
    name = ctypes.util.find_library("drm") or "libdrm.so.2"
    try:
        drm = ctypes.CDLL(name)
    except OSError:
        return []
    drm.drmModeGetResources.restype = ctypes.POINTER(drmModeRes)
    drm.drmModeGetConnector.restype = ctypes.POINTER(drmModeConnector)
    drm.drmModeGetConnector.argtypes = [ctypes.c_int, ctypes.c_uint32]
    drm.drmModeFreeConnector.argtypes = [ctypes.POINTER(drmModeConnector)]
    drm.drmModeFreeResources.argtypes = [ctypes.POINTER(drmModeRes)]
    try:
        fd = os.open(f"/dev/dri/card{card_index}", os.O_RDWR | os.O_CLOEXEC)
    except OSError:
        return []
    out: list[tuple[int, int, float, bool, float]] = []
    try:
        res = drm.drmModeGetResources(fd)
        if not res:
            return []
        try:
            for i in range(res.contents.count_connectors):
                c = drm.drmModeGetConnector(fd, res.contents.connectors[i])
                if not c:
                    continue
                try:
                    if c.contents.connection == 1 and c.contents.count_modes > 0:
                        for j in range(c.contents.count_modes):
                            m = c.contents.modes[j]
                            out.append((m.hdisplay, m.vdisplay, exact_hz(m),
                                        bool(m.flags & DRM_MODE_FLAG_INTERLACE), m.clock / 1000.0))
                        return out
                finally:
                    drm.drmModeFreeConnector(c)
        finally:
            drm.drmModeFreeResources(res)
    finally:
        os.close(fd)
    return out


def list_modes(display: int) -> list[Mode]:
    """Every mode of a display with its refresh rate, largest and fastest
    first. Empty if SDL can't be reached."""
    L = lib()
    if not L:
        return []
    kms = (L.SDL_GetCurrentVideoDriver() or b"").decode() == "kmsdrm"
    exact = drm_modes() if kms else []
    seen: dict[tuple, Mode] = {}
    m = SDL_DisplayMode()
    for i in range(max(0, L.SDL_GetNumDisplayModes(display))):
        if L.SDL_GetDisplayMode(display, i, ctypes.byref(m)) != 0:
            continue
        hz, inter = float(m.refresh_rate), False
        if kms and m.driverdata:
            # SDL's kmsdrm driverdata is {int mode_index} into the connector's list
            k = ctypes.cast(m.driverdata, ctypes.POINTER(ctypes.c_int))[0]
            if 0 <= k < len(exact) and exact[k][:2] == (m.w, m.h):
                hz, inter = exact[k][2], exact[k][3]
        mode = Mode(m.w, m.h, hz, inter, i)
        key = (m.w, m.h, round(hz, 2), inter)
        seen.setdefault(key, mode)
    return sorted(seen.values(), key=lambda t: (t.w * t.h, not t.interlaced, t.hz), reverse=True)


def set_mode(window_id: int, display: int, mode: Mode) -> bool:
    """Switch a fullscreen pygame Window to an exact mode, refresh included."""
    L = lib()
    if not L or mode.index is None:
        return False
    win = L.SDL_GetWindowFromID(window_id)
    if not win:
        return False
    m = SDL_DisplayMode()
    if L.SDL_GetDisplayMode(display, mode.index, ctypes.byref(m)) != 0:
        return False
    if L.SDL_SetWindowDisplayMode(win, ctypes.byref(m)) != 0:
        return False
    return L.SDL_SetWindowFullscreen(win, SDL_WINDOW_FULLSCREEN) == 0


def current_refresh(window_id: int) -> int | None:
    L = lib()
    if not L:
        return None
    win = L.SDL_GetWindowFromID(window_id)
    m = SDL_DisplayMode()
    if win and L.SDL_GetWindowDisplayMode(win, ctypes.byref(m)) == 0:
        return m.refresh_rate
    return None
