#!/usr/bin/env python3
"""TNT brand icons: "TNT" on top, three sticks of dynamite with a lit fuse
in the middle, the app's short name at the bottom.

Drawn at 8x and scaled down so edges stay clean at the launcher's 100 px.

    python3 branding/make_icons.py            # write all app icons
    python3 branding/make_icons.py --preview  # also write branding/preview.png

Writes <app>/packaging/icon.png (256, store) and icon_100.png (launcher).
Needs Pillow and DejaVu Sans Bold (fonts-dejavu-core).
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# app folder -> (short name, name colour)
APPS = {
    "av-tester": ("AV TEST", (255, 255, 255)),  # colour-bars background
    "net-tools": ("NET", (120, 220, 120)),
    "wifi-share": ("WIFI", (255, 200, 60)),
    "pcap-capture": ("PCAP", (255, 140, 200)),
}

BG = (16, 18, 26)
BARS = [(192, 192, 192), (192, 192, 0), (0, 192, 192), (0, 192, 0),
        (192, 0, 192), (192, 0, 0), (0, 0, 192)]  # SMPTE-style top bars
BARS_DIM = 0.62  # darken bars so text and dynamite stay readable
TNT_TXT = (255, 255, 255)
STICK = (206, 32, 32)
STICK_HI = (240, 80, 70)
STICK_LO = (140, 18, 18)
BAND = (30, 24, 22)
FUSE = (235, 220, 190)
SPARK = (255, 210, 60)
SPARK_HOT = (255, 255, 220)
WIFI_ARC = (255, 200, 60)
STICK_END = (245, 215, 170)

S = 8  # supersample factor


def _fit_font(draw, text, max_w, max_h):
    size = max_h
    while size > 4:
        f = ImageFont.truetype(FONT, size)
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if r - l <= max_w and b - t <= max_h:
            return f
        size -= 1
    return ImageFont.truetype(FONT, 4)


def _text(draw, text, cx, top, max_w, max_h, fill, stroke=0):
    f = _fit_font(draw, text, max_w - 2 * stroke, max_h - 2 * stroke)
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    draw.text((cx - (l + r) / 2, top - t + (max_h - (b - t)) / 2), text,
              font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))


def _star(draw, cx, cy, r_out, r_in, points, fill):
    pts = []
    for k in range(points * 2):
        r = r_out if k % 2 == 0 else r_in
        a = math.pi * k / points - math.pi / 2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    draw.polygon(pts, fill=fill)


def _dynamite(draw, x0, y0, w, h, wifi=False):
    """Classic bundle: three horizontal sticks stacked in box (x0, y0, w, h),
    tied with two bands, fuse out of the right end of the middle stick and a
    spark at its tip. wifi=True adds Wi-Fi arcs radiating out of the spark."""
    body_w = w * 0.74
    sh = h / 3.0                 # stick height
    gap = sh * 0.06
    cap = sh * 0.42              # depth of the rounded end caps
    for k in range(3):
        top = y0 + k * sh + gap / 2
        bot = top + sh - gap
        lx, rx = x0, x0 + body_w
        draw.rounded_rectangle((lx, top, rx, bot), radius=(bot - top) / 2,
                               fill=STICK)
        th = bot - top
        # highlight along the top, shadow along the bottom
        draw.rounded_rectangle((lx + cap * 0.6, top + th * 0.14,
                                rx - cap * 0.6, top + th * 0.32),
                               radius=th * 0.09, fill=STICK_HI)
        draw.rectangle((lx + cap * 0.6, bot - th * 0.20, rx - cap * 0.6,
                        bot - th * 0.04), fill=STICK_LO)
        # paper end showing on the right
        draw.ellipse((rx - cap * 1.1, top + th * 0.06, rx - th * 0.04,
                      bot - th * 0.06), fill=STICK_END)
    # two binding bands around the bundle
    for frac in (0.28, 0.66):
        bx = x0 + body_w * frac
        bw = body_w * 0.07
        draw.rectangle((bx, y0 - h * 0.02, bx + bw, y0 + h + h * 0.02),
                       fill=BAND)
    # fuse: out of the middle stick's right end, curling up and right
    fx, fy = x0 + body_w - cap * 0.55, y0 + h / 2
    room_w = x0 + w - fx
    pts = []
    for i in range(41):
        t = i / 40
        px = fx + room_w * 0.50 * t
        py = fy - h * 0.42 * t * t + h * 0.06 * math.sin(t * math.pi)
        pts.append((px, py))
    draw.line(pts, fill=FUSE, width=int(h * 0.075), joint="curve")
    ex, ey = pts[-1]
    sp = h * 0.24
    _star(draw, ex, ey, sp * 0.95, sp * 0.36, 8, SPARK)
    _star(draw, ex, ey, sp * 0.55, sp * 0.22, 8, SPARK_HOT)
    for a, d in ((-150, 1.35), (-40, 1.45), (25, 1.25), (-95, 1.5)):
        rr = sp * d
        px = ex + rr * math.cos(math.radians(a))
        py = ey + rr * math.sin(math.radians(a))
        dot = sp * 0.13
        draw.ellipse((px - dot, py - dot, px + dot, py + dot), fill=SPARK)
    if wifi:
        aim, half = -10, 36  # out to the right of the spark
        lw = h * 0.09
        for r in (h * 0.36, h * 0.56, h * 0.76):
            draw.arc((ex - r, ey - r, ex + r, ey + r), aim - half, aim + half,
                     fill=WIFI_ARC, width=int(lw))


def icon(short, colour, size, bars=False, wifi=False):
    n = size * S
    im = Image.new("RGB", (n, n), BG)
    d = ImageDraw.Draw(im)
    stroke = 0
    if bars:
        bw = n / len(BARS)
        for k, c in enumerate(BARS):
            c = tuple(int(v * BARS_DIM) for v in c)
            d.rectangle((k * bw, 0, (k + 1) * bw, n), fill=c)
        stroke = int(n * 0.018)
    pad = n * 0.05
    # rows: TNT 22%, dynamite 50%, name 24% (plus small gaps)
    tnt_h = n * 0.20
    _text(d, "TNT", n / 2, pad, n - 2 * pad, tnt_h, TNT_TXT, stroke)
    dyn_top = pad + tnt_h + n * 0.10
    dyn_h = n * 0.38
    dyn_w = n * (0.66 if wifi else 0.80)
    shift = n * (0.12 if wifi else 0.0)  # make room on the right for arcs
    _dynamite(d, (n - dyn_w) / 2 - shift, dyn_top, dyn_w, dyn_h, wifi)
    name_top = dyn_top + dyn_h + n * 0.025
    _text(d, short, n / 2, name_top, n - 2 * pad, n - pad - name_top, colour,
          stroke)
    return im.resize((size, size), Image.LANCZOS)


def main():
    out = {}
    for app, (short, colour) in APPS.items():
        bars = app == "av-tester"
        wifi = app == "wifi-share"
        out[app] = (icon(short, colour, 256, bars, wifi),
                    icon(short, colour, 100, bars, wifi))
        pk = os.path.join(ROOT, app, "packaging")
        if os.path.isdir(pk) and "--preview-only" not in sys.argv:
            out[app][0].save(os.path.join(pk, "icon.png"))
            out[app][1].save(os.path.join(pk, "icon_100.png"))
            print("wrote", app)
    if "--preview" in sys.argv or "--preview-only" in sys.argv:
        # top: store size; bottom: launcher size at 1:1 and zoomed 2x
        W = 20 + len(out) * 276
        pv = Image.new("RGB", (W, 440), (230, 230, 230))
        for k, (big, small) in enumerate(out.values()):
            x = 20 + k * 276
            pv.paste(big, (x, 10))
            pv.paste(small, (x, 330))
            pv.paste(small.resize((150, 150), Image.LANCZOS), (x + 106, 280))
        pv.save(os.path.join(HERE, "preview.png"))
        print("wrote preview")


if __name__ == "__main__":
    main()
