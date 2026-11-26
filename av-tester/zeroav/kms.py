"""Direct HDMI output through Linux KMS "dumb" framebuffers (no GPU/GL).

Why: the CardputerZero's GPU memory pool (CMA) is 64 MB. Drawing through
SDL's GL renderer at 1080p uses about 60 MB of it (GL back buffers, the
V3D binner pool, textures), leaving almost nothing, and an allocation
failure crashes the app inside the GPU driver.

Test patterns are static images, so they don't need a GPU. Here we ask the
kernel for two plain framebuffers in memory the display can scan out,
copy each pattern into one with the CPU, and flip between them on vblank.
At 1080p that is 2 x 8 MB = 16 MB of CMA, leaving about 45 MB free.

Keyboard input still comes through SDL, using its "evdev" video driver,
which reads the keyboard but never touches the display.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import fcntl
import mmap
import os
import select
import struct
import time

import numpy as np
import pygame

from .patterns import MovingBox, Pattern
from .sdlmodes import Mode, drmModeConnector, drmModeModeInfo, drmModeRes, exact_hz, DRM_MODE_FLAG_INTERLACE


def _iowr(nr: int, size: int) -> int:
    return (3 << 30) | (size << 16) | (ord("d") << 8) | nr


DRM_IOCTL_SET_MASTER = (ord("d") << 8) | 0x1E
DRM_IOCTL_MODE_CREATE_DUMB = _iowr(0xB2, 32)
DRM_IOCTL_MODE_MAP_DUMB = _iowr(0xB3, 16)
DRM_IOCTL_MODE_DESTROY_DUMB = _iowr(0xB4, 4)
DRM_MODE_PAGE_FLIP_EVENT = 0x01
DRM_EVENT_FLIP_COMPLETE = 0x02
DRM_VBLANK_RELATIVE = 0x1
DRM_VBLANK_SECONDARY = 0x20000000


class drmModeConnectorFull(ctypes.Structure):
    _fields_ = drmModeConnector._fields_ + [
        ("count_props", ctypes.c_int), ("props", ctypes.POINTER(ctypes.c_uint32)),
        ("prop_values", ctypes.POINTER(ctypes.c_uint64)),
        ("count_encoders", ctypes.c_int), ("encoders", ctypes.POINTER(ctypes.c_uint32))]


class drmModeEncoder(ctypes.Structure):
    _fields_ = [("encoder_id", ctypes.c_uint32), ("encoder_type", ctypes.c_uint32),
                ("crtc_id", ctypes.c_uint32), ("possible_crtcs", ctypes.c_uint32),
                ("possible_clones", ctypes.c_uint32)]


def cma_free_kb() -> tuple[int, int]:
    """(CmaFree, CmaTotal) in kB from /proc/meminfo, or (-1, -1)."""
    free = total = -1
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("CmaFree:"):
                    free = int(line.split()[1])
                elif line.startswith("CmaTotal:"):
                    total = int(line.split()[1])
    except OSError:
        pass
    return free, total


def _libdrm():
    name = ctypes.util.find_library("drm") or "libdrm.so.2"
    drm = ctypes.CDLL(name, use_errno=True)
    drm.drmModeGetResources.restype = ctypes.POINTER(drmModeRes)
    drm.drmModeGetConnector.restype = ctypes.POINTER(drmModeConnectorFull)
    drm.drmModeGetConnector.argtypes = [ctypes.c_int, ctypes.c_uint32]
    drm.drmModeFreeConnector.argtypes = [ctypes.POINTER(drmModeConnectorFull)]
    drm.drmModeFreeResources.argtypes = [ctypes.POINTER(drmModeRes)]
    drm.drmModeGetEncoder.restype = ctypes.POINTER(drmModeEncoder)
    drm.drmModeGetEncoder.argtypes = [ctypes.c_int, ctypes.c_uint32]
    drm.drmModeFreeEncoder.argtypes = [ctypes.POINTER(drmModeEncoder)]
    drm.drmModeAddFB.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint8,
                                 ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.POINTER(ctypes.c_uint32)]
    drm.drmModeRmFB.argtypes = [ctypes.c_int, ctypes.c_uint32]
    drm.drmModeSetCrtc.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                   ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int,
                                   ctypes.POINTER(drmModeModeInfo)]
    drm.drmModePageFlip.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_void_p]
    drm.drmWaitVBlank.argtypes = [ctypes.c_int, ctypes.c_void_p]
    return drm


class _Buffer:
    def __init__(self, fd: int, drm, w: int, h: int):
        req = bytearray(struct.pack("<IIIIIIQ", h, w, 32, 0, 0, 0, 0))
        fcntl.ioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, req)
        _, _, _, _, self.handle, self.pitch, self.size = struct.unpack("<IIIIIIQ", req)
        self.fd, self.drm, self.w, self.h = fd, drm, w, h
        fb = ctypes.c_uint32()
        if drm.drmModeAddFB(fd, w, h, 24, 32, self.pitch, self.handle, ctypes.byref(fb)) != 0:
            self._destroy_dumb()
            raise OSError(ctypes.get_errno(), "drmModeAddFB failed")
        self.fb = fb.value
        m = bytearray(struct.pack("<IIQ", self.handle, 0, 0))
        fcntl.ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, m)
        offset = struct.unpack("<IIQ", m)[2]
        self.map = mmap.mmap(fd, self.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=offset)
        # (h, pitch/4) uint32 view, each pixel 0x00RRGGBB
        self.px = np.frombuffer(self.map, dtype=np.uint32).reshape(h, self.pitch // 4)[:, :w]
        self.boxes: list[tuple[int, int, int, int]] = []   # rects drawn by the moving box

    def _destroy_dumb(self) -> None:
        try:
            fcntl.ioctl(self.fd, DRM_IOCTL_MODE_DESTROY_DUMB, bytearray(struct.pack("<I", self.handle)))
        except OSError:
            pass

    def free(self) -> None:
        self.px = None
        try:
            self.map.close()
        except (BufferError, ValueError):
            pass
        self.drm.drmModeRmFB(self.fd, self.fb)
        self._destroy_dumb()


class KmsOutput:
    """Same interface as output.HdmiOutput, without the GPU."""

    accelerated = False
    kind = "direct KMS"

    def __init__(self, card: int | None = None):
        if card is None:
            card = int(os.environ.get("SDL_KMSDRM_DEVICE_INDEX", "0") or 0)
        self.drm = _libdrm()
        self.fd = os.open(f"/dev/dri/card{card}", os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.ioctl(self.fd, DRM_IOCTL_SET_MASTER)
        except OSError as e:
            os.close(self.fd)
            raise OSError(e.errno, "HDMI is in use by another program (DRM master)") from e
        self._find_pipe()
        self.bufs: list[_Buffer] = []
        self.front = 0
        self.size = (0, 0)
        self.mode_set = True
        self.pages = 1
        self._shown = None        # what the front buffer shows
        self._pat_surf = None     # current static pattern, kept in RAM for overlay restore
        self._pat_key = None
        self._ovl_rect = None

    # ---- setup ----
    def _find_pipe(self) -> None:
        drm, fd = self.drm, self.fd
        res = drm.drmModeGetResources(fd)
        if not res:
            raise OSError("drmModeGetResources failed")
        try:
            crtcs = [res.contents.crtcs[i] for i in range(res.contents.count_crtcs)]
            for i in range(res.contents.count_connectors):
                c = drm.drmModeGetConnector(fd, res.contents.connectors[i])
                if not c:
                    continue
                cc = c.contents
                if cc.connection == 1 and cc.count_modes > 0:
                    self.connector_id = cc.connector_id
                    self.drm_modes = [drmModeModeInfo.from_buffer_copy(cc.modes[j]) for j in range(cc.count_modes)]
                    crtc_id = 0
                    if cc.encoder_id:
                        e = drm.drmModeGetEncoder(fd, cc.encoder_id)
                        if e:
                            crtc_id = e.contents.crtc_id
                            drm.drmModeFreeEncoder(e)
                    if not crtc_id:
                        for k in range(cc.count_encoders):
                            e = drm.drmModeGetEncoder(fd, cc.encoders[k])
                            if not e:
                                continue
                            poss = e.contents.possible_crtcs
                            drm.drmModeFreeEncoder(e)
                            for n, cid in enumerate(crtcs):
                                if poss & (1 << n):
                                    crtc_id = cid
                                    break
                            if crtc_id:
                                break
                    drm.drmModeFreeConnector(c)
                    if not crtc_id:
                        raise OSError("no display controller for HDMI")
                    self.crtc_id = crtc_id
                    self.pipe = crtcs.index(crtc_id)
                    return
                drm.drmModeFreeConnector(c)
        finally:
            drm.drmModeFreeResources(res)
        raise OSError("no HDMI display connected")

    def modes(self) -> list[Mode]:
        """Every mode the display offers, exact refresh, largest first."""
        seen = {}
        for i, m in enumerate(self.drm_modes):
            mode = Mode(m.hdisplay, m.vdisplay, exact_hz(m), bool(m.flags & DRM_MODE_FLAG_INTERLACE), i)
            seen.setdefault((mode.w, mode.h, round(mode.hz, 2), mode.interlaced), mode)
        return sorted(seen.values(), key=lambda t: (t.w * t.h, not t.interlaced, t.hz), reverse=True)

    def preferred_index(self) -> int:
        for i, m in enumerate(self.drm_modes):
            if m.type & 0x8:   # DRM_MODE_TYPE_PREFERRED
                return i
        return 0

    def open(self, mode) -> None:
        if isinstance(mode, Mode) and mode.index is not None and mode.index < len(self.drm_modes):
            mi = self.drm_modes[mode.index]
        else:
            w, h = mode.size if isinstance(mode, Mode) else mode
            cands = [m for m in self.drm_modes if (m.hdisplay, m.vdisplay) == (w, h)]
            mi = cands[0] if cands else self.drm_modes[self.preferred_index()]
        self._free_buffers()
        w, h = mi.hdisplay, mi.vdisplay
        # The desktop's buffers can take a moment to be released after it
        # stops, so retry, and fall back to one buffer if two won't fit.
        self.bufs = []
        for attempt in range(10):
            try:
                while len(self.bufs) < 2:
                    self.bufs.append(_Buffer(self.fd, self.drm, w, h))
                break
            except OSError as e:
                if attempt == 9:
                    if not self.bufs:
                        raise OSError(e.errno, f"not enough GPU memory for {w}x{h} "
                                               f"(CMA free {cma_free_kb()[0] // 1024} MB)") from e
                    print(f"KMS: only one framebuffer fits ({e}); motion may tear",
                          file=__import__("sys").stderr, flush=True)
                    self.bufs.append(self.bufs[0])
                    break
                time.sleep(0.3)
        for b in self.bufs:
            b.px[:] = 0
        conn = ctypes.c_uint32(self.connector_id)
        mi_c = drmModeModeInfo.from_buffer_copy(mi)
        if self.drm.drmModeSetCrtc(self.fd, self.crtc_id, self.bufs[0].fb, 0, 0, ctypes.byref(conn), 1,
                                   ctypes.byref(mi_c)) != 0:
            err = ctypes.get_errno()
            self._free_buffers()
            raise OSError(err, f"could not set HDMI mode {w}x{h}: {os.strerror(err)}")
        self.front = 0
        self.size = (w, h)
        self.hz = exact_hz(mi)
        self._mode_info = mi_c
        self._shown = ("black",)
        self._pat_surf = self._pat_key = self._ovl_rect = None

    def _free_buffers(self) -> None:
        for b in {id(b): b for b in self.bufs}.values():
            b.free()
        self.bufs = []

    def close(self) -> None:
        self._free_buffers()
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    # ---- presenting ----
    def _wait_vblank(self) -> None:
        req = ctypes.create_string_buffer(24)
        t = DRM_VBLANK_RELATIVE
        if self.pipe == 1:
            t |= DRM_VBLANK_SECONDARY
        elif self.pipe > 1:
            t |= (self.pipe << 1) & 0x3E
        struct.pack_into("<II", req, 0, t, 1)
        if self.drm.drmWaitVBlank(self.fd, req) != 0:
            time.sleep(1 / 60)

    def _flip(self, i: int) -> None:
        """Show buffer i from the next vblank, and wait for it."""
        if i == self.front or self.bufs[i] is self.bufs[self.front]:
            self._wait_vblank()
            self.front = i
            return
        if self.drm.drmModePageFlip(self.fd, self.crtc_id, self.bufs[i].fb, DRM_MODE_PAGE_FLIP_EVENT, None) != 0:
            # flip refused: switch on the next vblank instead
            conn = ctypes.c_uint32(self.connector_id)
            mi = drmModeModeInfo.from_buffer_copy(self._mode_info)
            self._wait_vblank()
            self.drm.drmModeSetCrtc(self.fd, self.crtc_id, self.bufs[i].fb, 0, 0, ctypes.byref(conn), 1,
                                    ctypes.byref(mi))
            self.front = i
            self._wait_vblank()
            return
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if not r:
                break
            data = os.read(self.fd, 1024)
            done = False
            while len(data) >= 8:
                typ, ln = struct.unpack_from("<II", data)
                if typ == DRM_EVENT_FLIP_COMPLETE:
                    done = True
                data = data[max(ln, 8):]
            if done:
                break
        self.front = i

    def _copy(self, surf: pygame.Surface, buf: _Buffer, area=None) -> None:
        """Copy a 32-bit surface (or the part `area` of it) into a buffer."""
        if surf.get_bitsize() != 32:
            surf = _to32(surf)
        w, h = surf.get_size()
        src = np.frombuffer(surf.get_buffer(), dtype=np.uint32).reshape(h, surf.get_pitch() // 4)[:, :w]
        if area is None:
            buf.px[:h, :w] = src[: buf.h, : buf.w]
        else:
            x, y, aw, ah = area
            buf.px[y:y + ah, x:x + aw] = src[y:y + ah, x:x + aw]

    def _show_surface(self, surf: pygame.Surface, key) -> None:
        if self._shown == key:
            self._wait_vblank()
            return
        back = 1 - self.front
        self._copy(surf, self.bufs[back])
        self.bufs[back].boxes = []
        self._flip(back)
        self._shown = key
        self._ovl_rect = None

    # ---- the HdmiOutput interface ----
    def frame(self, pat: Pattern, frame: int, overlay: list[str] | None) -> None:
        if isinstance(pat, MovingBox):
            self._moving_box(pat, frame)
            if overlay:
                self._overlay(overlay, self.bufs[self.front], restore=False)
            return
        key = ("pattern", id(pat), self.size)
        if self._pat_key != key:
            surf = pygame.Surface(self.size, 0, 32)
            pat.draw(surf, 0)
            self._pat_surf, self._pat_key = surf, key
        if self._shown != key:
            self._show_surface(self._pat_surf, key)
        if overlay:
            self._overlay(overlay, self.bufs[self.front], restore=True)
        elif self._ovl_rect:
            self._copy(self._pat_surf, self.bufs[self.front], self._ovl_rect)
            self._ovl_rect = None
        self._wait_vblank()

    def _overlay(self, lines: list[str], buf: _Buffer, restore: bool) -> None:
        key = tuple(lines)
        if restore and self._ovl_rect and getattr(self, "_ovl_key", None) == key:
            return
        w, h = self.size
        font = pygame.font.Font(None, max(16, h // 30))
        lh = font.get_linesize() + 2
        box = pygame.Surface((w * 3 // 5, lh * 3), 0, 32)
        for i, t in enumerate(lines[:3]):
            box.blit(font.render(t, True, (255, 255, 255)), (4, i * lh))
        x, y = w // 40, h // 40
        bw, bh = box.get_size()
        src = np.frombuffer(box.get_buffer(), dtype=np.uint32).reshape(bh, box.get_pitch() // 4)[:, :bw]
        buf.px[y:y + bh, x:x + bw] = src
        self._ovl_rect, self._ovl_key = (x, y, bw, bh), key

    def _moving_box(self, pat: MovingBox, frame: int) -> None:
        w, h = self.size
        back = 1 - self.front
        b = self.bufs[back]
        if self._shown != "box":
            b.px[:] = 0
            self.bufs[self.front].px[:] = 0
            for bb in self.bufs:
                bb.boxes = []
            self._shown = "box"
        for (x, y, bw, bh) in b.boxes:          # erase what this buffer showed 2 frames ago
            b.px[y:y + bh, x:x + bw] = 0
        size = h // 6
        travel = w - size
        pos = (frame * pat.px) % (2 * travel)
        x = pos if pos < travel else 2 * travel - pos
        y = h // 2 - size // 2
        b.px[y:y + size, x:x + size] = 0x00FFFFFF
        cell = w // 10
        sy = h - h // 20
        b.px[sy:h, (frame % 10) * cell:(frame % 10) * cell + cell] = 0x00FF0000
        b.boxes = [(x, y, size, size), ((frame % 10) * cell, sy, cell, h - sy)]
        self._flip(back)

    def solid(self, white: bool) -> None:
        """Lip-sync flash: buffer 1 = white, buffer 0 = black, flip between."""
        if self._shown not in ("solid",):
            self.bufs[0].px[:] = 0
            self.bufs[1].px[:] = 0x00FFFFFF
            self._shown = "solid"
            self._pat_key = None
            self._flip(0)
        self._flip(1 if white else 0)

    def text_page(self, title: str, sections: list[tuple[str, list[str]]], page: int) -> None:
        from .output import layout_text_page
        key = ("page", title, tuple((t, tuple(b)) for t, b in sections), page, self.size)
        if self._shown != key:
            surf, self.pages = layout_text_page(self.size, title, sections, page)
            self._show_surface(surf, key)
        else:
            self._wait_vblank()

    def surface_page(self, surf: pygame.Surface, key) -> None:
        key = ("surf", key)
        if self._shown == key:
            self._wait_vblank()
            return
        big = pygame.transform.scale(surf, self.size)
        if big.get_bitsize() != 32:
            big = _to32(big)
        self._show_surface(big, key)


def _to32(surf: pygame.Surface) -> pygame.Surface:
    out = pygame.Surface(surf.get_size(), 0, 32)
    out.blit(surf, (0, 0))
    return out
