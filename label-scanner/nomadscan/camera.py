"""Live camera frames from the CardputerZero's IMX219 using rpicam-vid.

rpicam-vid streams raw YUV420 frames to a pipe; a reader thread keeps the
newest one. The frame is 1536x816, the same shape as the 320x170 screen, so
the preview shows exactly what gets decoded. Uses no root and no extra
Python packages (numpy is already there for the LCD).
"""
from __future__ import annotations

import ctypes
import os
import shutil
import signal
import subprocess
import threading
import time

import numpy as np

W, H = 1536, 816          # 4.8 x the screen, multiple of 64 so no row padding
FRAME = W * H * 3 // 2
ZOOMS = {1: None, 2: "0.25,0.25,0.5,0.5"}


def _die_with_parent():  # pragma: no cover - runs in the child
    try:
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except OSError:
        pass


def available() -> bool:
    return bool(shutil.which("rpicam-vid") or shutil.which("libcamera-vid"))


class Frame:
    __slots__ = ("seq", "buf", "t")

    def __init__(self, seq: int, buf: bytes, t: float):
        self.seq, self.buf, self.t = seq, buf, t

    @property
    def y(self) -> np.ndarray:
        return np.frombuffer(self.buf, np.uint8, W * H).reshape(H, W)

    def planes(self):
        a = np.frombuffer(self.buf, np.uint8)
        y = a[:W * H].reshape(H, W)
        u = a[W * H:W * H + W * H // 4].reshape(H // 2, W // 2)
        v = a[W * H + W * H // 4:].reshape(H // 2, W // 2)
        return y, u, v

    def rgb_image(self, max_w: int = W):
        """Full colour PIL image (for the saved photo)."""
        from PIL import Image
        y, u, v = self.planes()
        Y = Image.fromarray(y)
        U = Image.fromarray(u).resize((W, H))
        V = Image.fromarray(v).resize((W, H))
        img = Image.merge("YCbCr", (Y, U, V)).convert("RGB")
        if max_w < W:
            img = img.resize((max_w, H * max_w // W))
        return img


_ri = _ci = None


def preview(frame: Frame, out_w: int = 320, out_h: int = 170) -> np.ndarray:
    """RGB array (out_w, out_h, 3) for pygame.surfarray, sampled from the frame."""
    global _ri, _ci
    if _ri is None or len(_ri) != out_h:
        _ri = (np.arange(out_h) * H // out_h).astype(np.intp)
        _ci = (np.arange(out_w) * W // out_w).astype(np.intp)
    y, u, v = frame.planes()
    Y = y[_ri][:, _ci].astype(np.int16)
    U = u[_ri // 2][:, _ci // 2].astype(np.int16) - 128
    V = v[_ri // 2][:, _ci // 2].astype(np.int16) - 128
    r = Y + ((V * 359) >> 8)
    g = Y - ((U * 88 + V * 183) >> 8)
    b = Y + ((U * 454) >> 8)
    rgb = np.stack([r, g, b], axis=-1).clip(0, 255).astype(np.uint8)
    return rgb.swapaxes(0, 1)


class Camera:
    def __init__(self, rotation: int = 0, zoom: int = 1, fps: int = 6):
        self.rotation, self.zoom, self.fps = rotation, zoom, fps
        self.proc: subprocess.Popen | None = None
        self.frame: Frame | None = None
        self.error = ""
        self._seq = 0
        self._t: threading.Thread | None = None
        self._lock = threading.Lock()
        self.on_frame = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def cmd(self) -> list[str]:
        exe = shutil.which("rpicam-vid") or shutil.which("libcamera-vid") or "rpicam-vid"
        c = [exe, "-n", "-t", "0", "--codec", "yuv420", "--width", str(W), "--height", str(H),
             "--framerate", str(self.fps), "--flush", "-o", "-"]
        if self.rotation == 180:
            c += ["--rotation", "180"]
        if ZOOMS.get(self.zoom):
            c += ["--roi", ZOOMS[self.zoom]]
        return c

    def start(self) -> bool:
        if self.running:
            return True
        self.error = ""
        self.frame = None
        try:
            self.proc = subprocess.Popen(self.cmd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         bufsize=0, preexec_fn=_die_with_parent)
        except OSError as e:
            self.error = f"Camera program missing: {e}"
            self.proc = None
            return False
        self._t = threading.Thread(target=self._read, args=(self.proc,), daemon=True)
        self._t.start()
        return True

    def _read(self, proc) -> None:
        buf = bytearray(FRAME)
        view = memoryview(buf)
        while True:
            got = 0
            while got < FRAME:
                try:
                    n = proc.stdout.readinto(view[got:])
                except (OSError, ValueError):
                    n = 0
                if not n:
                    break
                got += n
            if got < FRAME:
                break
            self._seq += 1
            with self._lock:
                self.frame = Frame(self._seq, bytes(buf), time.monotonic())
            if self.on_frame:
                self.on_frame()
        if proc is self.proc:      # ended by itself, not by stop()
            try:
                err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            except (OSError, ValueError):
                err = ""
            self.error = _explain(err)
            if self.on_frame:
                self.on_frame()

    def latest(self) -> Frame | None:
        with self._lock:
            return self.frame

    def wait_frame(self, after_seq: int = 0, timeout: float = 4.0) -> Frame | None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            f = self.latest()
            if f and f.seq > after_seq:
                return f
            if not self.running:
                return f
            time.sleep(0.05)
        return self.latest()

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()

    def restart(self) -> bool:
        self.stop()
        time.sleep(0.2)
        return self.start()


def _explain(err: str) -> str:
    e = err.lower()
    if "no cameras available" in e:
        return "No camera found."
    if "busy" in e or "resource" in e:
        return "Camera is busy (another app is using it)."
    if "cannot allocate" in e or "dma" in e or "cma" in e:
        return "Not enough camera memory. Close other camera apps."
    lines = [l for l in err.strip().splitlines() if "ERROR" in l or "error" in l]
    return (lines[-1][-90:] if lines else "Camera stopped.") if err.strip() else "Camera stopped."
