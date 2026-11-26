#!/usr/bin/env python3
"""TNT brand icons: "TNT" on top, three sticks of dynamite with a lit fuse
in the middle, the app's short name at the bottom.

Drawn at 8x and scaled down so edges stay clean at the launcher's 100 px.

    python3 branding/make_icons.py            # write all app icons
    python3 branding/make_icons.py --preview  # also write branding/preview.png
    add --plain for the no-dynamite style (big TNT + name)

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
TNT_RED = (230, 40, 40)
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


def _stick(draw, x_right, cy, length, dia, bands):
    """One horizontal stick drawn in 3D: body, round left end, paper end
    facing right. x_right/cy is the centre of the visible right end."""
    r = dia / 2
    ex = dia * 0.26                      # half-width of the end ellipses
    lx = x_right - length
    draw.ellipse((lx - ex, cy - r, lx + ex, cy + r), fill=STICK_LO)
    draw.rectangle((lx, cy - r, x_right, cy + r), fill=STICK)
    draw.rectangle((lx, cy - r * 0.62, x_right, cy - r * 0.30), fill=STICK_HI)
    draw.rectangle((lx, cy + r * 0.48, x_right, cy + r), fill=STICK_LO)
    for f in bands:
        bx = lx + length * f
        draw.rectangle((bx, cy - r, bx + length * 0.07, cy + r), fill=BAND)
    draw.ellipse((x_right - ex, cy - r, x_right + ex, cy + r),
                 fill=STICK_END, outline=STICK_LO, width=max(1, int(dia * 0.05)))
    draw.ellipse((x_right - ex * 0.25, cy - r * 0.22, x_right + ex * 0.25,
                  cy + r * 0.22), fill=(200, 160, 110))


def _dynamite(draw, x0, y0, w, h, wifi=False):
    """Classic 3D bundle in box (x0, y0, w, h): three horizontal sticks
    stacked as a triangle (two at the bottom, one on top), fuse out of the
    top stick's end, spark at its tip. wifi=True adds Wi-Fi arcs."""
    dia = h / 2.15
    # oblique depth axis: back of the bundle sits up and to the right
    dx, dy = 0.46 * dia, -0.39 * dia
    length = w * 0.70 - dx
    xr = x0 + length + dia * 0.3          # right-end centre, front stick
    by = y0 + h - dia / 2                 # centre y, front bottom stick
    bands = (0.22, 0.62)
    # back-bottom, then top, then front-bottom (painter's order)
    _stick(draw, xr + dx, by + dy, length, dia, bands)
    tx, ty = xr + dx / 2, by + dy / 2 - 0.866 * dia
    _stick(draw, tx, ty, length, dia, bands)
    _stick(draw, xr, by, length, dia, bands)
    # fuse: out of the top stick's paper end, curling up and right
    fx, fy = tx, ty
    pts = []
    for i in range(41):
        t = i / 40
        px = fx + w * 0.16 * t
        py = fy - h * 0.30 * t * t + h * 0.05 * math.sin(t * math.pi)
        pts.append((px, py))
    draw.line(pts, fill=FUSE, width=int(h * 0.06), joint="curve")
    ex, ey = pts[-1]
    sp = h * 0.20
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
        lw = h * 0.075
        for r in (h * 0.30, h * 0.47, h * 0.64):
            draw.arc((ex - r, ey - r, ex + r, ey + r), aim - half, aim + half,
                     fill=WIFI_ARC, width=int(lw))


def _wifi_symbol(draw, cx, top, h, colour):
    """Upright Wi-Fi symbol (dot + three arcs) filling height h."""
    r_max = h * 0.95
    by = top + h                      # centre of the arcs (the dot)
    lw = h * 0.16
    d = h * 0.13
    draw.ellipse((cx - d, by - d * 2, cx + d, by), fill=colour)
    for k in (0.42, 0.70, 0.98):
        r = r_max * k
        draw.arc((cx - r, by - d - r, cx + r, by - d + r), -135, -45,
                 fill=colour, width=int(lw))


def icon_plain(short, colour, size, bars=False, wifi=False):
    """No-dynamite style: big TNT on top, app name below."""
    n = size * S
    im = Image.new("RGB", (n, n), BG)
    d = ImageDraw.Draw(im)
    stroke = 0
    if bars:
        bw = n / len(BARS)
        for k, c in enumerate(BARS):
            c = tuple(int(v * BARS_DIM) for v in c)
            d.rectangle((k * bw, 0, (k + 1) * bw, n), fill=c)
        stroke = int(n * 0.02)
    pad = n * 0.06
    if wifi:
        _text(d, "TNT", n / 2, pad, n - 2 * pad, n * 0.30, TNT_RED, stroke)
        _wifi_symbol(d, n / 2, n * 0.38, n * 0.26, WIFI_ARC)
        _text(d, short, n / 2, n * 0.70, n - 2 * pad, n * 0.24, colour, stroke)
    else:
        _text(d, "TNT", n / 2, pad, n - 2 * pad, n * 0.46, TNT_RED,
              stroke or int(n * 0.012))
        _text(d, short, n / 2, n * 0.58, n - 2 * pad, n * 0.32, colour, stroke)
    return im.resize((size, size), Image.LANCZOS)


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
    dyn_top = pad + tnt_h + n * 0.06
    dyn_h = n * 0.44
    dyn_w = n * (0.66 if wifi else 0.80)
    shift = n * (0.12 if wifi else 0.0)  # make room on the right for arcs
    _dynamite(d, (n - dyn_w) / 2 - shift, dyn_top, dyn_w, dyn_h, wifi)
    name_top = dyn_top + dyn_h + n * 0.02
    _text(d, short, n / 2, name_top, n - 2 * pad, n - pad - name_top, colour,
          stroke)
    return im.resize((size, size), Image.LANCZOS)


def main():
    out = {}
    for app, (short, colour) in APPS.items():
        bars = app == "av-tester"
        wifi = app == "wifi-share"
        fn = icon_plain if "--plain" in sys.argv else icon
        out[app] = (fn(short, colour, 256, bars, wifi),
                    fn(short, colour, 100, bars, wifi))
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
        pv.save(os.path.join(HERE, "preview-plain.png" if "--plain" in sys.argv
                             else "preview.png"))
        print("wrote preview")


if __name__ == "__main__":
    main()
