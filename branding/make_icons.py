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
    "av-tester": ("AV", (255, 255, 255)),  # colour-bars background
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
    """Three upright sticks in box (x0, y0, w, h), fuse and spark above.
    wifi=True adds Wi-Fi arcs radiating out of the lit fuse."""
    spark_h = h * 0.30
    sy0 = y0 + spark_h          # top of sticks
    sw = w / 3.0
    gap = sw * 0.08
    rad = sw * 0.22
    for k in range(3):
        lx = x0 + k * sw + gap / 2
        rx = lx + sw - gap
        # middle stick sits a little higher, like a bundle
        top = sy0 + (0 if k == 1 else h * 0.05)
        bot = y0 + h
        draw.rounded_rectangle((lx, top, rx, bot), radius=rad, fill=STICK)
        # shading: highlight stripe left, shadow right
        hw = (rx - lx)
        draw.rounded_rectangle((lx + hw * 0.14, top + rad * 0.6,
                                lx + hw * 0.32, bot - rad * 0.6),
                               radius=hw * 0.09, fill=STICK_HI)
        draw.rectangle((rx - hw * 0.18, top + rad, rx - 1, bot - rad),
                       fill=STICK_LO)
    # two binding bands across the bundle
    for frac in (0.22, 0.70):
        by = sy0 + (y0 + h - sy0) * frac
        bh = h * 0.07
        draw.rectangle((x0, by, x0 + w, by + bh), fill=BAND)
    # fuse: from top of middle stick curving up and right
    fx, fy = x0 + w / 2, sy0
    pts = []
    for i in range(41):
        t = i / 40
        px = fx + w * 0.30 * t + w * 0.06 * math.sin(t * math.pi)
        py = fy - spark_h * 0.62 * t - spark_h * 0.12 * math.sin(t * math.pi * 2)
        pts.append((px, py))
    draw.line(pts, fill=FUSE, width=int(w * 0.055), joint="curve")
    ex, ey = pts[-1]
    # spark burst at the fuse end
    _star(draw, ex, ey, spark_h * 0.46, spark_h * 0.18, 8, SPARK)
    _star(draw, ex, ey, spark_h * 0.28, spark_h * 0.11, 8, SPARK_HOT)
    for a, d in ((-150, 0.78), (-35, 0.85), (20, 0.70), (-95, 0.88)):
        rr = spark_h * d
        px = ex + rr * math.cos(math.radians(a))
        py = ey + rr * math.sin(math.radians(a))
        dot = spark_h * 0.07
        draw.ellipse((px - dot, py - dot, px + dot, py + dot), fill=SPARK)
    if wifi:
        aim, half = 8, 38  # pointing out to the right
        lw = w * 0.08
        for r in (w * 0.28, w * 0.45, w * 0.62):
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
    dyn_top = pad + tnt_h + n * 0.03
    dyn_h = n * 0.47
    dyn_w = n * 0.56
    shift = n * (0.15 if wifi else 0.06)  # make room on the right for arcs
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
