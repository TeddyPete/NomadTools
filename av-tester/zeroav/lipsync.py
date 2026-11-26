"""Lip-sync (A/V offset) tester.

How it works:
- The HDMI output flashes the screen white for a few frames and, at the
  same moment, sends a short 1 kHz beep in the HDMI audio.
- The CardputerZero's camera (640x480 sensor mode at 200 fps, so one frame
  every 5 ms) watches the screen, and its microphone listens to the
  speakers.
- For each flash we find when the light arrived and when the beep arrived.
  Audio arrival minus video arrival is the A/V offset. Positive means audio
  is late (behind the picture), negative means audio is early.
- About ten flashes at random intervals give a median and a spread.

Our own capture chain has fixed delays (camera readout, audio buffers), so
a one-time calibration on a reference system stores a correction that is
subtracted from every result.

Recommended correction is biased to leave audio about 12 ms late, because
viewers notice early audio much sooner than late audio (ATSC IS-191 allows
+15 / -45 ms, EBU R37 +40 / -60 ms, audio early / late).
"""
from __future__ import annotations

import fcntl
import json
import os
import random
import shutil
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass, field

import numpy as np

RATE = 48000
BEEP_HZ = 1000.0
BEEP_MS = 40
FLASH_FRAMES = 3
BIAS_MS = 12            # leave audio this much late after correcting
IN_SYNC_MS = 8          # within this of the target counts as in sync
CAL_PATH = os.path.expanduser("~/.config/tnt-av-tester/lipsync.json")
WINDOW_S = (-0.1, 0.9)  # search window around each emitted flash/beep

# ---------------------------------------------------------------- analysis


def video_onset(times: np.ndarray, levels: np.ndarray) -> float | None:
    """Time the picture brightness first crosses halfway between its dark
    level and its flash level, interpolated between camera frames."""
    if len(levels) < 6:
        return None
    lo = float(np.percentile(levels, 10))
    hi = float(levels.max())
    if hi - lo < 8:            # brightness hardly changed: no flash seen
        return None
    mid = (lo + hi) / 2
    above = np.nonzero(levels >= mid)[0]
    k = int(above[0])
    if k == 0:
        return None            # flash already on at window start
    y0, y1 = levels[k - 1], levels[k]
    frac = (mid - y0) / (y1 - y0) if y1 != y0 else 0.0
    return float(times[k - 1] + frac * (times[k] - times[k - 1]))


def tone_envelope(x: np.ndarray, rate: int = RATE, hz: float = BEEP_HZ, smooth_ms: float = 1.0) -> np.ndarray:
    """Amplitude of the beep frequency over time (complex demodulation)."""
    n = np.arange(len(x))
    y = x.astype(np.float64) * np.exp(-2j * np.pi * hz * n / rate)
    w = max(1, int(rate * smooth_ms / 1000))
    k = np.ones(w) / w
    return np.abs(np.convolve(y, k, mode="same")) * 2


def audio_onset(t0: float, x: np.ndarray, rate: int = RATE) -> float | None:
    """Time the beep first reaches half its peak level. t0 is the time of
    sample 0."""
    if len(x) < rate // 20:
        return None
    env = tone_envelope(x, rate)
    floor = float(np.percentile(env, 20))
    peak = float(env.max())
    if peak < 4 * floor + 30:   # nothing clearly above the room noise
        return None
    mid = floor + (peak - floor) / 2
    k = int(np.nonzero(env >= mid)[0][0])
    if k == 0:
        return None
    frac = (mid - env[k - 1]) / (env[k] - env[k - 1]) if env[k] != env[k - 1] else 0.0
    return t0 + (k - 1 + frac) / rate


def advice(offset_ms: float) -> list[str]:
    """Plain-English verdict and fix for a measured offset (+ = audio late)."""
    late = offset_ms >= 0
    lines = [f"Audio is {abs(offset_ms):.0f} ms {'late' if late else 'early'}"]
    atsc = -15 <= offset_ms <= 45
    ebu = -40 <= offset_ms <= 60
    lines.append(f"ATSC {'PASS' if atsc else 'FAIL'}   EBU R37 {'PASS' if ebu else 'FAIL'}")
    corr = offset_ms - BIAS_MS
    if abs(corr) <= IN_SYNC_MS:
        lines.append("In sync. No change needed.")
    elif corr > 0:
        lines.append(f"Fix: remove {corr:.0f} ms audio delay")
        lines.append(f"  (or add {corr:.0f} ms video delay)")
    else:
        lines.append(f"Fix: add {-corr:.0f} ms audio delay")
    return lines


def load_calibration() -> float | None:
    try:
        with open(CAL_PATH) as f:
            return float(json.load(f)["offset_ms"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_calibration(offset_ms: float, note: str = "") -> None:
    os.makedirs(os.path.dirname(CAL_PATH), exist_ok=True)
    with open(CAL_PATH, "w") as f:
        json.dump({"offset_ms": round(offset_ms, 2), "when": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "note": note}, f)


# ---------------------------------------------------------------- capture


class Ring:
    """Thread-safe store of (time, value) samples, trimmed to max_s seconds."""

    def __init__(self, max_s: float = 6.0):
        self.max_s = max_s
        self.t: list[float] = []
        self.v: list = []
        self.lock = threading.Lock()

    def add(self, t: float, v) -> None:
        with self.lock:
            self.t.append(t)
            self.v.append(v)
            if self.t[0] < t - self.max_s:
                cut = next(i for i, x in enumerate(self.t) if x >= t - self.max_s)
                del self.t[:cut]
                del self.v[:cut]

    def window(self, a: float, b: float):
        with self.lock:
            idx = [i for i, x in enumerate(self.t) if a <= x <= b]
            return [self.t[i] for i in idx], [self.v[i] for i in idx]

    def last(self):
        with self.lock:
            return (self.t[-1], self.v[-1]) if self.t else (0.0, None)


def _stderr_tail(p: subprocess.Popen) -> str:
    try:
        return (p.stderr.read() or b"").decode(errors="replace").strip().splitlines()[-1][:60]
    except Exception:
        return ""


class Camera:
    """Mean brightness of every camera frame at 200 fps, via rpicam-vid.

    The sensor runs its 640x480 200 fps mode; the ISP scales frames down to
    160x120 so the Pi only moves about 5 MB/s. Exposure and gain are fixed
    so auto-exposure can't dim the flash."""

    W, H = 160, 120

    def __init__(self, fps: int = 200):
        self.fps = fps
        self.ring = Ring()
        self.proc = None
        self.error = ""
        self.frames = 0

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("rpicam-vid") or shutil.which("libcamera-vid"))

    def start(self) -> None:
        exe = shutil.which("rpicam-vid") or shutil.which("libcamera-vid")
        if not exe:
            self.error = "rpicam-vid not found"
            return
        cmd = [exe, "-n", "-t", "0", "--mode", "640:480", "--width", str(self.W), "--height", str(self.H),
               "--framerate", str(self.fps), "--codec", "yuv420", "--shutter", "3000", "--gain", "4",
               "--awbgains", "1,1", "--denoise", "cdn_off", "--flush", "-o", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        y_size = self.W * self.H
        frame_size = y_size * 3 // 2
        f = self.proc.stdout
        buf = bytearray(frame_size)
        view = memoryview(buf)
        while True:
            got = 0
            while got < frame_size:
                n = f.readinto(view[got:])
                if not n:
                    self.error = self.error or ("camera stopped: " + _stderr_tail(self.proc))
                    return
                got += n
            t = time.perf_counter()
            y = np.frombuffer(buf, dtype=np.uint8, count=y_size)
            self.ring.add(t, float(y.mean()))
            self.frames += 1

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Mic:
    """Microphone (or 3.5 mm line in) samples with arrival-time stamps.

    Sample k's time is modelled as c + k / RATE, where c is the earliest
    arrival seen relative to the sample count. That removes the jitter of
    when each chunk happens to be read."""

    CHUNK = 240   # 5 ms

    def __init__(self, device: str = "default", channels: int = 2):
        self.device = device
        self.channels = channels
        self.proc = None
        self.error = ""
        self.lock = threading.Lock()
        self.samples: list[np.ndarray] = []
        self.first_index = 0          # sample index of samples[0][0]
        self.count = 0                # samples read in total
        self.c = None                 # time of sample 0
        self.level = 0.0              # recent peak, 0..1

    def start(self) -> None:
        cmd = ["arecord", "-q", "-D", self.device, "-f", "S16_LE", "-r", str(RATE), "-c", str(self.channels),
               "-t", "raw", "--buffer-time=40000", "--period-time=5000"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        nbytes = self.CHUNK * 2 * self.channels
        f = self.proc.stdout
        keep = int(RATE * 6)
        while True:
            data = b""
            while len(data) < nbytes:
                d = f.read(nbytes - len(data))
                if not d:
                    self.error = self.error or ("mic stopped: " + _stderr_tail(self.proc))
                    return
                data += d
            t = time.perf_counter()
            a = np.frombuffer(data, dtype="<i2").reshape(-1, self.channels)
            mono = a[:, 0]
            if self.channels > 1:  # use the louder channel (the mic may be on one side)
                mono = a[:, int(np.argmax(np.abs(a).max(axis=0)))]
            with self.lock:
                self.count += len(mono)
                cand = t - self.count / RATE
                self.c = cand if self.c is None else min(self.c, cand)
                self.samples.append(mono.copy())
                total = sum(len(s) for s in self.samples)
                while total - len(self.samples[0]) > keep:
                    total -= len(self.samples[0])
                    self.first_index += len(self.samples[0])
                    self.samples.pop(0)
                self.level = 0.9 * self.level + 0.1 * float(np.abs(mono).max()) / 32768

    def window(self, a: float, b: float) -> tuple[float, np.ndarray]:
        with self.lock:
            if self.c is None or not self.samples:
                return 0.0, np.zeros(0)
            x = np.concatenate(self.samples)
            i0 = max(0, int((a - self.c) * RATE) - self.first_index)
            i1 = min(len(x), int((b - self.c) * RATE) - self.first_index)
            if i1 <= i0:
                return 0.0, np.zeros(0)
            return self.c + (self.first_index + i0) / RATE, x[i0:i1]

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class BeepOut:
    """Continuous HDMI audio stream (silence) that can insert a beep.

    The stream is kept full, so the delay from writing a block to hearing
    it stays constant during a run. Each beep's write time is recorded and
    later compared with the flash's present time."""

    BLOCK = 240  # 5 ms

    def __init__(self, device: str):
        self.device = device
        self.proc = None
        self.error = ""
        self._want = threading.Event()
        self.on_beep = None          # callback(t_written) from the audio thread
        self._stop = False
        n = np.arange(int(RATE * BEEP_MS / 1000))
        ramp = np.minimum(1.0, np.minimum(n, n[::-1]) / (RATE * 0.0005))
        tone = (0.5 * 32767 * np.sin(2 * np.pi * BEEP_HZ * n / RATE) * ramp).astype("<i2")
        self.beep = np.repeat(tone[:, None], 2, axis=1).tobytes()
        self.silence = bytes(self.BLOCK * 4)

    def start(self) -> None:
        cmd = ["aplay", "-q", "-D", self.device, "-f", "S16_LE", "-r", str(RATE), "-c", "2", "-t", "raw",
               "--buffer-time=40000", "--period-time=10000"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        try:  # keep the pipe tiny so it adds little (and steady) delay
            fcntl.fcntl(self.proc.stdin.fileno(), 1031, 4096)  # F_SETPIPE_SZ
        except OSError:
            pass
        threading.Thread(target=self._run, daemon=True).start()

    def request(self) -> None:
        self._want.set()

    def _run(self) -> None:
        w = self.proc.stdin
        try:
            while not self._stop:
                if self._want.is_set():
                    self._want.clear()
                    head = self.BLOCK * 4
                    w.write(self.beep[:head])   # beep start is now queued
                    t = time.perf_counter()
                    if self.on_beep:
                        self.on_beep(t)
                    w.write(self.beep[head:])
                else:
                    w.write(self.silence)
        except (BrokenPipeError, OSError, ValueError):
            self.error = self.error or ("audio out stopped: " + _stderr_tail(self.proc))

    def stop(self) -> None:
        self._stop = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            self.proc.terminate()


# ---------------------------------------------------------------- test run


@dataclass
class Event:
    t_beep: float = 0.0         # when the beep was written to the audio stream
    t_flash: float = 0.0        # when the first white frame was presented
    v_lat: float | None = None  # light seen, seconds after t_flash
    a_lat: float | None = None  # beep heard, seconds after t_beep
    raw_ms: float | None = None # a_lat - v_lat, before calibration


@dataclass
class LipSyncTest:
    audio_out: str
    mic_device: str = "default"
    count: int = 10
    events: list[Event] = field(default_factory=list)

    def __post_init__(self):
        self.cam = Camera()
        self.mic = Mic(self.mic_device)
        self.out = BeepOut(self.audio_out)
        self.out.on_beep = self._beeped
        self.state = "idle"      # idle, warmup, running, done, error
        self.next_at = 0.0
        self.flash_left = 0
        self._pending: Event | None = None
        self.cal = load_calibration()
        self.message = ""

    # -- control --
    def start(self) -> None:
        self.events = []
        self.cam.start()
        self.mic.start()
        self.out.start()
        self.state = "warmup"
        self.next_at = time.perf_counter() + 12.0  # give up if not ready by then
        self.message = "Starting camera and mic..."

    def stop(self) -> None:
        self.cam.stop()
        self.mic.stop()
        self.out.stop()
        if self.state not in ("done", "error"):
            self.state = "idle"

    def _beeped(self, t: float) -> None:
        if self._pending is not None:
            self._pending.t_beep = t
            self.flash_left = FLASH_FRAMES   # flash on the next present

    # -- per frame, from the render loop --
    def frame_is_white(self) -> bool:
        """Call once per frame before presenting. True while flashing."""
        now = time.perf_counter()
        err = self.cam.error or self.mic.error or self.out.error
        if err and self.state in ("warmup", "running"):
            self.state, self.message = "error", err
            return False
        if self.state == "warmup":
            # The camera takes 2.5-4 s to start; wait for a steady stream
            # (and the mic), then let exposure settle for a moment.
            ready = self.cam.frames >= 200 and self.mic.c is not None
            if ready:
                self.state = "running"
                self.next_at = now + 0.5
            elif now >= self.next_at:
                self.state = "error"
                self.message = "Camera not delivering frames" if self.cam.frames < 200 else "Mic not delivering sound"
                return False
        if self.state == "running":
            if self._pending is None and len(self.events) < self.count and now >= self.next_at:
                self._pending = Event()
                self.out.request()
            self._analyse(now)
        return self.flash_left > 0

    def presented(self, white: bool) -> None:
        """Call right after each present() with what was shown."""
        if white:
            if self.flash_left == FLASH_FRAMES and self._pending is not None:
                self._pending.t_flash = time.perf_counter()
                self.events.append(self._pending)
                self._pending = None
                self.next_at = time.perf_counter() + random.uniform(1.6, 2.4)
            self.flash_left -= 1

    def _analyse(self, now: float) -> None:
        for e in self.events:
            if e.raw_ms is not None or e.v_lat == -1:
                continue
            if now < e.t_flash + WINDOW_S[1] + 0.1:
                continue
            ts, vs = self.cam.ring.window(e.t_flash + WINDOW_S[0], e.t_flash + WINDOW_S[1])
            tv = video_onset(np.array(ts), np.array(vs)) if ts else None
            t0, x = self.mic.window(e.t_beep + WINDOW_S[0], e.t_beep + WINDOW_S[1])
            ta = audio_onset(t0, x) if len(x) else None
            if tv is None or ta is None:
                e.v_lat = -1   # missed
                self.message = "Missed: " + ("no flash seen" if tv is None else "no beep heard")
                continue
            e.v_lat, e.a_lat = tv - e.t_flash, ta - e.t_beep
            e.raw_ms = (e.a_lat - e.v_lat) * 1000
            self.message = f"#{len(self.good())}: {self.corrected(e.raw_ms):+.0f} ms"
        done = len(self.events) >= self.count and all(
            e.raw_ms is not None or e.v_lat == -1 for e in self.events)
        if done:
            self.state = "done"
            self.stop()

    # -- results --
    def good(self) -> list[float]:
        return [e.raw_ms for e in self.events if e.raw_ms is not None]

    def corrected(self, raw_ms: float) -> float:
        return raw_ms - (self.cal or 0.0)

    def result(self) -> tuple[float, float, int] | None:
        """(median offset ms, spread ms, measurements) after calibration."""
        g = self.good()
        if not g:
            return None
        med = statistics.median(g)
        spread = (max(g) - min(g)) if len(g) > 1 else 0.0
        return self.corrected(med), spread, len(g)

    def calibrate_here(self) -> float | None:
        """Treat this run's raw median as zero offset from now on."""
        g = self.good()
        if len(g) < 3:
            return None
        self.cal = statistics.median(g)
        save_calibration(self.cal, "reference run")
        return self.cal

    def lcd_lines(self) -> list[str]:
        cal = "not calibrated" if self.cal is None else f"cal {self.cal:+.0f} ms"
        if self.state == "idle":
            return ["Aim camera at the screen,", "mic near the speakers.",
                    "Room fairly quiet.", f"Mic level {self.mic.level * 100:.0f}%  ({cal})"]
        if self.state in ("warmup", "running"):
            n, m = len(self.good()), len(self.events)
            lvl = f"Light {self.cam.ring.last()[1] or 0:.0f}  mic {self.mic.level * 100:.0f}%"
            r = self.result()
            res = f"Now {r[0]:+.0f} ms (spread {r[1]:.0f})" if r else "Measuring..."
            return [f"Flash {m}/{self.count}  good {n}", res, lvl, self.message[:40]]
        if self.state == "error":
            return ["Test stopped:", self.message[:40], self.message[40:80], "Enter to retry"]
        r = self.result()
        if not r:
            return ["No good measurements.", "Check camera aim and", "speaker volume.", "Enter to retry"]
        med, spread, n = r
        lines = advice(med)
        lines.insert(1, f"{n} flashes, spread {spread:.0f} ms ({cal})")
        return lines

    def report(self) -> str:
        r = self.result()
        out = [f"TNT AV Tester lip-sync report  {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        if r:
            out += [f"Offset: {r[0]:+.1f} ms (+ = audio late), spread {r[1]:.1f} ms, {r[2]} flashes"]
            out += advice(r[0])
        else:
            out.append("No good measurements.")
        out.append("")
        out.append("Calibration: " + ("none" if self.cal is None else f"{self.cal:+.1f} ms subtracted"))
        out.append("")
        out.append("Each flash (ms): video arrival, audio arrival, offset after calibration")
        for i, e in enumerate(self.events, 1):
            if e.raw_ms is None:
                out.append(f"  {i:2d}: missed")
            else:
                out.append(f"  {i:2d}: {e.v_lat * 1000:7.1f} {e.a_lat * 1000:7.1f}  {self.corrected(e.raw_ms):+7.1f}")
        return "\n".join(out) + "\n"


def probe(seconds: float = 5.0, mic_device: str = "default") -> None:
    """Check camera frame rate and brightness, and mic level, without HDMI."""
    cam, mic = Camera(), Mic(mic_device)
    cam.start()
    mic.start()
    t0 = time.perf_counter()
    while cam.frames == 0 and time.perf_counter() - t0 < 10 and not cam.error:
        time.sleep(0.05)
    print(f"camera started after {time.perf_counter() - t0:.1f} s", flush=True)
    time.sleep(seconds)
    cam.stop()
    mic.stop()
    dt = time.perf_counter() - t0
    ts, vs = cam.ring.window(0, 1e18)
    if len(ts) > 2:
        gaps = np.diff(ts) * 1000
        print(f"camera: {len(ts)} frames in {ts[-1] - ts[0]:.2f} s = {(len(ts) - 1) / (ts[-1] - ts[0]):.1f} fps, "
              f"gap median {np.median(gaps):.1f} ms, max {gaps.max():.1f} ms, "
              f"brightness {min(vs):.0f}-{max(vs):.0f}")
    else:
        print(f"camera: {len(ts)} frames in {dt:.1f} s. {cam.error}")
    _, x = mic.window(0, 1e18)
    if len(x):
        print(f"mic: {len(x) / RATE:.2f} s, peak {int(np.abs(x).max())}/32767, "
              f"rms {float(np.sqrt(np.mean(x.astype(float) ** 2))):.0f}")
    else:
        print(f"mic: no samples. {mic.error}")


if __name__ == "__main__":
    import sys
    probe(float(sys.argv[1]) if len(sys.argv) > 1 else 5.0)
