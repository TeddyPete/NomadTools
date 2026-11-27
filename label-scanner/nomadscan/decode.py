"""Read a frame: barcodes/QR codes with zbar, printed text with tesseract.

Both are the Debian packages (python3-zbar, tesseract-ocr), run as the
normal user. Barcodes take a fraction of a second; OCR a few seconds on
the CardputerZero, so it runs only when you take a shot.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import numpy as np

try:
    import zbar as _zbar  # python3-zbar
except ImportError:  # pragma: no cover
    _zbar = None

_scanner = None


def have_zbar() -> bool:
    return _zbar is not None or bool(shutil.which("zbarimg"))


def have_ocr() -> bool:
    return bool(shutil.which("tesseract"))


def _tmpdir() -> str:
    d = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return d if os.access(d, os.W_OK) else tempfile.gettempdir()


def barcodes(gray: np.ndarray) -> list[tuple[str, str]]:
    """[(symbology, text)] for every barcode / QR code in a grayscale frame."""
    global _scanner
    gray = np.ascontiguousarray(gray, dtype=np.uint8)
    h, w = gray.shape
    if _zbar is not None:
        if _scanner is None:
            _scanner = _zbar.ImageScanner()
            _scanner.parse_config("enable")
        img = _zbar.Image(w, h, "Y800", gray.tobytes())
        _scanner.scan(img)
        out = []
        for s in img:
            data = s.data if isinstance(s.data, str) else s.data.decode("utf-8", "replace")
            out.append((str(s.type), data))
        return _uniq(out)
    if shutil.which("zbarimg"):
        from PIL import Image
        p = os.path.join(_tmpdir(), "nomad-scan-z.png")
        Image.fromarray(gray).save(p)
        try:
            r2 = subprocess.run(["zbarimg", "-q", p], capture_output=True, text=True, timeout=10)
        finally:
            os.unlink(p)
        out = []
        for line in r2.stdout.splitlines():
            sym, _, data = line.partition(":")
            if data:
                out.append((sym, data))
        return _uniq(out)
    return []


def _uniq(items):
    seen, out = set(), []
    for it in items:
        if it[1] not in seen:
            seen.add(it[1])
            out.append(it)
    return out


def prep_for_ocr(gray: np.ndarray) -> np.ndarray:
    """Stretch the contrast (labels are often grey on silver)."""
    g = gray.astype(np.float32)
    lo, hi = np.percentile(g, 2), np.percentile(g, 98)
    if hi - lo < 10:
        return gray
    return ((g - lo) * (255.0 / (hi - lo))).clip(0, 255).astype(np.uint8)


def ocr(gray: np.ndarray, timeout: float = 40) -> str:
    """Printed text on the label (tesseract, sparse text mode)."""
    if not have_ocr():
        return ""
    from PIL import Image
    p = os.path.join(_tmpdir(), "nomad-scan-ocr.png")
    Image.fromarray(prep_for_ocr(gray)).save(p)
    env = dict(os.environ, OMP_THREAD_LIMIT="4")
    try:
        r = subprocess.run(["tesseract", p, "stdout", "--psm", "11", "-l", "eng"],
                           capture_output=True, text=True, timeout=timeout, env=env)
        return r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""
    finally:
        try:
            os.unlink(p)
        except OSError:
            pass


def sharpness(gray: np.ndarray) -> float:
    """Focus score (variance of a Laplacian on a 1/4 size copy). Higher is sharper."""
    g = gray[::4, ::4].astype(np.float32)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var())
