"""ZeroAV tester: HDMI test patterns and tones, run from the keyboard,
with status on the built-in LCD.

Run on the device (from the console, not a desktop session):
    python3 -m zeroav.app
Render every pattern to PNG without a display (for checking patterns):
    python3 -m zeroav.app --render-dir out --size 1920x1080
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

KEYS_HELP = "</> pattern  T tone  I info  M res  Q quit"


def parse_size(s: str) -> tuple[int, int]:
    w, h = s.lower().split("x")
    return int(w), int(h)


def render_all(out_dir: str, size: tuple[int, int]) -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from .patterns import all_patterns, draw_info_overlay
    pygame.init()
    os.makedirs(out_dir, exist_ok=True)
    surf = pygame.Surface(size)
    for i, p in enumerate(all_patterns()):
        p.draw(surf, 30)
        if i == 0:
            draw_info_overlay(surf, [f"{size[0]}x{size[1]}", "sample overlay"])
        fn = os.path.join(out_dir, f"{i:02d}_{p.name.replace(' ', '_').replace('/', '-')}.png")
        pygame.image.save(surf, fn)
        print(fn)
    # LCD status screens, 320x170, used as store screenshots
    from .lcd import LcdPanel
    lcd = LcdPanel(headless=True)
    pats = all_patterns()
    for n, (i, tone) in enumerate([(0, "off"), (5, "tone"), (18, "lr")]):
        p = pats[i]
        lcd.show(p.name, status_lines(size, 60, 60.0, i, len(pats), p.category, tone, -20.0), KEYS_HELP)
        fn = os.path.join(out_dir, f"lcd_{n}.png")
        lcd.save(fn)
        print(fn)


def status_lines(size, refresh, fps, idx, total, category, tone, dbfs) -> list[str]:
    return [
        f"{size[0]}x{size[1]} @ {refresh or '?'} Hz ({fps:.1f})",
        f"Pattern {idx + 1}/{total}  [{category}]",
        f"Tone: {tone}  {dbfs:.0f} dBFS",
    ]


def pick_hdmi_display(pygame) -> int:
    """Index of the largest display that isn't the 320x170 LCD."""
    sizes = pygame.display.get_desktop_sizes()
    best, area = 0, -1
    for i, (w, h) in enumerate(sizes):
        if {w, h} == {320, 170}:
            continue
        if w * h > area:
            best, area = i, w * h
    return best


def no_hdmi(lcd, detail: str) -> None:
    """Explain on the LCD why HDMI output could not start, then exit."""
    print(f"HDMI output unavailable: {detail}", file=sys.stderr, flush=True)
    lcd.show("No HDMI output", ["Connect an HDMI display", "and open the app again.", detail[:40]],
             "Closing in 8 s")
    time.sleep(8)


def run(args) -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
    import pygame
    from .audio import TonePlayer
    from .lcd import LcdPanel
    from .patterns import all_patterns, draw_info_overlay

    pygame.init()
    lcd = LcdPanel()
    # The launcher stops apps with SIGTERM; turn that into a clean quit.
    signal.signal(signal.SIGTERM, lambda *_: pygame.event.post(pygame.event.Event(pygame.QUIT)))
    try:
        pygame.display.init()
        pygame.mouse.set_visible(False)
    except pygame.error as e:
        no_hdmi(lcd, f"Display error: {e}")
        return
    disp = pick_hdmi_display(pygame)
    modes = sorted(set(pygame.display.list_modes(display=disp) or []), reverse=True)
    mode_idx = 0
    size = parse_size(args.size) if args.size else (modes[0] if modes else (1920, 1080))
    if size in modes:
        mode_idx = modes.index(size)

    def open_screen(sz):
        return pygame.display.set_mode(sz, pygame.FULLSCREEN, display=disp, vsync=1)

    try:
        screen = open_screen(size)
    except pygame.error as e:
        no_hdmi(lcd, str(e))
        return
    tones = TonePlayer(args.audio_device)
    patterns = all_patterns()
    idx, frame, show_info = 0, 0, False
    clock = pygame.time.Clock()
    fps_measured, t0, n0 = 0.0, time.monotonic(), 0
    try:
        rates = pygame.display.get_desktop_refresh_rates()
        refresh = rates[disp] if rates else 0
    except AttributeError:
        refresh = 0
    dirty = True

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                tones.stop()
                return
            if ev.type != pygame.KEYDOWN:
                continue
            k, ch = ev.key, (ev.unicode or "").lower()
            if k in (pygame.K_ESCAPE,) or ch == "q":
                tones.stop()
                return
            if k in (pygame.K_RIGHT, pygame.K_DOWN, pygame.K_SPACE) or ch in (".", "/", "n"):
                idx = (idx + 1) % len(patterns)
            elif k in (pygame.K_LEFT, pygame.K_UP) or ch in (",", ";", "p"):
                idx = (idx - 1) % len(patterns)
            elif ch.isdigit() and ch != "0":
                cats = list(dict.fromkeys(p.category for p in patterns))
                c = int(ch) - 1
                if c < len(cats):
                    idx = next(i for i, p in enumerate(patterns) if p.category == cats[c])
            elif ch == "i":
                show_info = not show_info
            elif ch == "t":
                tones.cycle()
            elif ch in ("+", "="):
                tones.dbfs = min(0.0, tones.dbfs + 2)
                if tones.mode:
                    tones.play(tones.mode)
            elif ch == "-":
                tones.dbfs = max(-60.0, tones.dbfs - 2)
                if tones.mode:
                    tones.play(tones.mode)
            elif ch == "m" and modes:
                mode_idx = (mode_idx + 1) % len(modes)
                size = modes[mode_idx]
                screen = open_screen(size)
            dirty = True

        pat = patterns[idx]
        if dirty or pat.animated or show_info:
            pat.draw(screen, frame)
            if show_info:
                draw_info_overlay(screen, [
                    f"{size[0]}x{size[1]}  set {refresh or '?'} Hz  measured {fps_measured:.2f} fps",
                    f"frame {frame}",
                    pat.name,
                ])
            pygame.display.flip()
        frame += 1
        clock.tick(0 if pat.animated or show_info else 30)

        now = time.monotonic()
        if now - t0 >= 1.0:
            fps_measured = (frame - n0) / (now - t0)
            t0, n0 = now, frame
            dirty = True
        if dirty:
            tone = tones.mode or "off"
            lcd.show(pat.name, status_lines(size, refresh, fps_measured, idx, len(patterns),
                                            pat.category, tone, tones.dbfs), KEYS_HELP)
            dirty = False


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", help="HDMI resolution, e.g. 1920x1080 (default: display's preferred)")
    ap.add_argument("--audio-device", default=os.environ.get("ZEROAV_AUDIO"),
                    help="ALSA device for tones (default: pipewire if present, else default)")
    ap.add_argument("--render-dir", help="render all patterns to PNG files here and exit")
    args = ap.parse_args(argv)
    if args.render_dir:
        render_all(args.render_dir, parse_size(args.size or "1920x1080"))
        return
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
