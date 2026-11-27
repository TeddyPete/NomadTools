"""Desktop live viewer: a window on the HDMI desktop that follows the running
capture (or the last one): a scrolling packet list, protocol stats, top
senders, and details + hex of a clicked packet.

The CardputerZero keyboard also types into whatever desktop window has
focus, so this window ignores the keyboard. Its packet-list filter is set
from the small screen (Filter > Desktop view filter) and read from the
settings file; the mouse scrolls the list and picks a packet.

Filter words must all match (case-insensitive) a packet's source,
destination, protocol or info; a word starting with ! must not match.
Example:  ptp !follow_up      dante 192.168.1.20      41794
"""
from __future__ import annotations

import os
import socket
import time

PID_NAME = "viewer.pid"


def live_wayland_socket(rt: str, pref: str = "") -> str:
    try:
        names = [n for n in os.listdir(rt) if n.startswith("wayland-") and not n.endswith(".lock")]
    except OSError:
        return ""
    names.sort(key=lambda n: (n != pref, n))
    for n in names:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(0.5)
        try:
            c.connect(os.path.join(rt, n))
            return n
        except OSError:
            pass
        finally:
            c.close()
    return ""


def hdmi_connected() -> bool:
    import glob
    for p in glob.glob("/sys/class/drm/card*-HDMI-A-*/status"):
        try:
            if open(p).read().strip() == "connected":
                return True
        except OSError:
            pass
    return False


def desktop_ready() -> bool:
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return hdmi_connected() and bool(live_wayland_socket(rt))


def _pidfile() -> str:
    from . import capture as C
    return os.path.join(C.state_dir(), PID_NAME)


def running_pid() -> int | None:
    try:
        pid = int(open(_pidfile()).read().strip())
        os.kill(pid, 0)
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if b"--viewer" not in f.read():
                return None
        return pid
    except (OSError, ValueError):
        return None


def launch() -> bool:
    """Open the viewer window on the desktop if HDMI + desktop are up and it
    isn't open yet. Returns True if it is (now) running."""
    import subprocess
    import sys
    if running_pid():
        return True
    if not desktop_ready():
        return False
    env = dict(os.environ)
    rt = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env.update(SDL_VIDEODRIVER="wayland", LIBGL_ALWAYS_SOFTWARE="1", XDG_RUNTIME_DIR=rt,
               WAYLAND_DISPLAY=live_wayland_socket(rt, env.get("WAYLAND_DISPLAY", "")))
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = pkg_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    subprocess.Popen([sys.executable, "-m", "nomadcap", "--viewer"], env=env, cwd=pkg_dir,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return True


def match(row, words) -> bool:
    if not words:
        return True
    text = f"{row[2]} {row[3]} {row[4]} {row[6]}".lower()
    for w in words:
        if w.startswith("!"):
            if w[1:] and w[1:] in text:
                return False
        elif w not in text:
            return False
    return True


def hexdump(data: bytes, width: int = 16, limit: int = 256) -> list[str]:
    out = []
    for i in range(0, min(len(data), limit), width):
        chunk = data[i:i + width]
        hx = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{i:04x}  {hx:<{width * 3}} {asc}")
    if len(data) > limit:
        out.append(f"... {len(data) - limit} more bytes")
    return out


# colors
BG = (12, 14, 20)
PANEL = (20, 24, 34)
FG = (230, 232, 236)
DIM = (140, 150, 165)
GREEN = (18, 120, 52)
SEL = (30, 90, 200)
RED = (230, 70, 60)
WARN = (255, 200, 90)
PROTO_COLORS = {"PTP": (120, 170, 255), "PTP (L2)": (120, 170, 255), "Dante audio": (110, 220, 120),
                "Dante ctl": (180, 230, 140), "mDNS": (230, 180, 255), "ARP": (255, 200, 90),
                "IGMP": (255, 150, 90), "DHCP": (255, 120, 160)}


def main() -> int:
    import pygame

    from . import capture as C
    from . import pcapread
    from . import settings as S

    os.makedirs(C.state_dir(), exist_ok=True)
    with open(_pidfile(), "w") as f:
        f.write(str(os.getpid()))
    pygame.display.init()
    pygame.font.init()
    try:
        pygame.key.stop_text_input()
    except pygame.error:
        pass
    sizes = pygame.display.get_desktop_sizes() or [(1280, 720)]
    dw, dh = max(sizes, key=lambda s: s[0] * s[1])
    win = pygame.display.set_mode((min(1600, dw - 40), min(900, dh - 80)), pygame.RESIZABLE)
    pygame.display.set_caption("Nomad Packet Capture - live view")
    mono_path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    mk = lambda p, s: pygame.font.Font(p if os.path.exists(p) else None, s)  # noqa: E731
    fm, fb, fs = mk(mono_path, 15), mk(bold_path, 18), mk(mono_path, 13)
    lh = fm.get_linesize() + 2

    reader = pcapread.Reader()
    cur_file = None
    follow = True
    top = 0                 # index into filtered rows when not following
    picked = None           # packet number
    cache: dict = {}
    words: list[str] = []
    last_cfg = 0.0
    st: dict = {}
    clock = pygame.time.Clock()
    t_open = time.monotonic()
    list_bottom, shown = 0, []
    shot = os.environ.get("NOMAD_VIEWER_SHOT")      # tests: save one frame and exit

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                try:
                    os.remove(_pidfile())
                except OSError:
                    pass
                return 0
            if ev.type == pygame.MOUSEWHEEL:
                follow = False
                top = max(0, top - ev.y * 3)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                win_w, win_h = win.get_size()
                if ev.pos[1] < 34 and ev.pos[0] > win_w - 160:
                    follow = not follow
                elif 34 + lh <= ev.pos[1] < list_bottom:
                    i = (ev.pos[1] - 34 - lh) // lh
                    if 0 <= i < len(shown):
                        picked = shown[i][0]
                        follow = False
            if ev.type == pygame.VIDEORESIZE:
                win = pygame.display.get_surface()
        now = time.monotonic()
        if now - last_cfg > 1.0:
            last_cfg = now
            st = C.read_state()
            vf = (S.load().get("view_filter") or "").lower().split()
            if vf != words:
                words, top = vf, 0
            files = st.get("files") or []
            f = files[-1] if files else (st.get("job") or {}).get("file")
            if f and f != cur_file and os.path.exists(f):
                reader.reset()
                cur_file, picked, cache = f, None, {}
        reader.poll(cur_file)

        rows = [r for r in reader.rows if match(r, words)]
        win = pygame.display.get_surface()
        W, H = win.get_size()
        side = max(300, W // 4)
        lw = W - side
        detail_h = max(160, H // 3)
        list_bottom = H - detail_h
        nrows = max(1, (list_bottom - 34 - lh) // lh)
        if follow:
            top = max(0, len(rows) - nrows)
        top = min(top, max(0, len(rows) - nrows))
        shown = rows[top:top + nrows]

        win.fill(BG)
        # title bar
        win.fill(GREEN, (0, 0, W, 34))
        job = st.get("job") or {}
        if st.get("running"):
            el = int(st.get("elapsed", 0))
            stat = f"● REC {job.get('iface', '')}"
            if job.get("tap"):
                stat += f" (inline tap: built-in ⇄ {job['tap']})"
            stat += f"   {el // 60:02d}:{el % 60:02d}   {st.get('packets', 0):,} pkts   " \
                    f"{st.get('pps', 0):.0f} pkt/s   drops {st.get('drops', 0):,}"
        elif job:
            stat = f"Stopped ({st.get('error') or st.get('reason') or ''})   {st.get('packets', 0):,} pkts"
        else:
            stat = "No capture yet. Start one on the CardputerZero."
        win.blit(fb.render("Nomad Packet Capture   " + stat, True, (255, 255, 255)), (10, 6))
        btn = "Following ▼" if follow else "Paused (click)"
        win.blit(fb.render(btn, True, (210, 255, 215)), (W - 150, 6))
        # packet list
        cols = [("No.", 60), ("Time", 90), ("Source", 170), ("Destination", 170), ("Protocol", 120),
                ("Len", 50), ("Info", 0)]
        x = 8
        win.fill(PANEL, (0, 34, lw, lh))
        for name, w in cols:
            win.blit(fm.render(name, True, DIM), (x, 35))
            x += w
        t0 = reader.rows[0][1] if reader.rows else 0
        y = 34 + lh
        for r in shown:
            n, ts, src, dst, proto, ln, info, _ = r
            if n == picked:
                win.fill(SEL, (0, y, lw, lh))
            img = cache.get(n)
            if img is None:
                img = pygame.Surface((lw, lh), pygame.SRCALPHA)
                xx = 8
                color = PROTO_COLORS.get(proto, FG)
                for (name, w), val in zip(cols, (str(n), f"{ts - t0:9.3f}", src, dst, proto, str(ln), info)):
                    img.blit(fm.render(val[:max(4, (w or 400) // 9)], True,
                                       color if name in ("Protocol", "Info") else FG), (xx, 0))
                    xx += w
                cache[n] = img
                if len(cache) > 3000:
                    cache.clear()
            win.blit(img, (0, y))
            y += lh
        if words:
            win.blit(fs.render(f"filter: {' '.join(words)}   {len(rows):,} of {len(reader.rows):,} shown",
                               True, WARN), (8, list_bottom - lh))
        # details
        win.fill(PANEL, (0, list_bottom, lw, detail_h))
        pk = next((r for r in reader.rows if r[0] == picked), None)
        if pk:
            n, ts, src, dst, proto, ln, info, data = pk
            lines = [f"Packet {n}   {time.strftime('%H:%M:%S', time.localtime(ts))}.{int(ts % 1 * 1e6):06d}"
                     f"   {ln} bytes on wire, {len(data)} saved",
                     f"{proto}: {src} → {dst}   {info}", ""] + hexdump(data)
        else:
            lines = ["Click a packet to see its details.", "",
                     "Filter this list from the CardputerZero: Filter > Desktop view filter.",
                     "Open the saved .pcap in Wireshark for full decoding."]
        yy = list_bottom + 6
        for l in lines:
            if yy > H - lh:
                break
            win.blit(fs.render(l, True, FG if pk else DIM), (8, yy))
            yy += fs.get_linesize()
        # side: protocols and senders
        win.fill(PANEL, (lw, 34, side, H - 34))
        sx, yy = lw + 12, 42
        win.blit(fb.render("Protocols" + (" (sample)" if reader.skipped else ""), True, WARN), (sx, yy))
        yy += 28
        tot = sum(reader.protos.values()) or 1
        for p, c in reader.protos.most_common(14):
            frac = c / tot
            win.fill((40, 48, 66), (sx, yy + 2, side - 24, lh - 4))
            win.fill(PROTO_COLORS.get(p, (90, 110, 150)), (sx, yy + 2, int((side - 24) * frac), lh - 4))
            win.blit(fm.render(f"{p[:16]:16} {frac * 100:4.0f}% {c:,}", True, FG), (sx + 4, yy))
            yy += lh
        yy += 12
        win.blit(fb.render("Top senders", True, WARN), (sx, yy))
        yy += 28
        for ip, c in reader.talkers.most_common(10):
            if yy > H - lh:
                break
            win.blit(fm.render(f"{ip:16} {c:,}", True, FG), (sx, yy))
            yy += lh
        pygame.display.flip()
        if shot and now - t_open > 1.5:
            picked = picked or (shown[len(shown) // 2][0] if shown else None)
            if now - t_open > 2.5:
                pygame.image.save(win, shot)
                return 0
        clock.tick(4 if now - t_open > 2 else 10)
