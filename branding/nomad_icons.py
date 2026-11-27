#!/usr/bin/env python3
"""Nomad app icon generator: glossy "rendered" 3D look, one family.

Two concept styles:
  device  - each app is a glossy 3D gadget with a glowing subject (like a
            store render), small compass badge in the corner as the Nomad mark.
  compass - each app is a brushed-metal compass bezel with the app's glowing
            symbol in the glass.

Usage: nomad_icons.py --style device|compass --out DIR [--sheet sheet.png]
Writes DIR/<app>.png (256) and DIR/<app>_100.png (100).
"""
import argparse, math, os
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont

S = 1024  # work size, downsampled at the end
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

APPS = [
    # key, label, accent colour
    ("av-tester", "AV TESTER", (80, 230, 255)),
    ("net-tools", "NET TOOLS", (90, 255, 140)),
    ("wifi-share", "WIFI SHARE", (255, 210, 70)),
    ("packet-capture", "PACKET CAPTURE", (255, 90, 190)),
    ("display-control", "DISPLAY CONTROL", (170, 130, 255)),
    ("mcp", "MCP", (255, 140, 60)),
]


# ---------- helpers ----------
def layer():
    return Image.new("RGBA", (S, S), (0, 0, 0, 0))


def vgrad(w, h, top, bot):
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    return g.resize((w, h))


def rrect_mask(box, r):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, r, fill=255)
    return m


def fill_grad(img, box, r, top, bot):
    x0, y0, x1, y1 = [int(v) for v in box]
    g = vgrad(x1 - x0, y1 - y0, top, bot)
    full = layer()
    full.paste(g, (x0, y0))
    img.paste(full, (0, 0), rrect_mask(box, r))


def shadow(img, box, r, off=(0, 30), blur=40, alpha=170):
    sh = layer()
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle((x0 + off[0], y0 + off[1], x1 + off[0], y1 + off[1]), r, fill=(0, 0, 0, alpha))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))


def gloss(img, box, r, strength=90):
    """Soft white highlight on the top half of a rounded box."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    g = layer()
    grad = Image.new("L", (1, int(h * 0.5)))
    for y in range(grad.height):
        grad.putpixel((0, y), int(strength * (1 - y / grad.height) ** 1.6))
    grad = grad.resize((int(x1 - x0), grad.height))
    white = Image.new("RGBA", grad.size, (255, 255, 255, 255))
    white.putalpha(grad)
    g.paste(white, (int(x0), int(y0)))
    m = ImageChops.multiply(g.getchannel("A"), rrect_mask(box, r))
    g.putalpha(m)
    img.alpha_composite(g)


def rim(img, box, r, col=(255, 255, 255, 70), w=6):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, r, outline=col, width=w)


def glow_draw(img, fn, col, blur=(28, 10), core=True):
    """fn(draw, colour) paints shapes; adds a wide glow, a tight glow, and a core."""
    for b, a in ((blur[0], 200), (blur[1], 255)):
        l = layer()
        fn(ImageDraw.Draw(l), col + (a,))
        img.alpha_composite(l.filter(ImageFilter.GaussianBlur(b)))
    if core:
        l = layer()
        fn(ImageDraw.Draw(l), col + (255,))
        img.alpha_composite(l)
        # whitish hot centre
        l = layer()
        hot = tuple(min(255, c + 150) for c in col)
        fn(ImageDraw.Draw(l), hot + (200,), )
        img.alpha_composite(l.filter(ImageFilter.GaussianBlur(2)))


def background(img, accent):
    pad = 40
    box = (pad, pad, S - pad, S - pad)
    shadow(img, box, 200, off=(0, 18), blur=24, alpha=120)
    fill_grad(img, box, 200, (38, 44, 54), (12, 14, 20))
    # faint accent vignette from below
    v = layer()
    ImageDraw.Draw(v).ellipse((S * 0.1, S * 0.55, S * 0.9, S * 1.15), fill=accent + (55,))
    v = v.filter(ImageFilter.GaussianBlur(120))
    v.putalpha(ImageChops.multiply(v.getchannel("A"), rrect_mask(box, 200)))
    img.alpha_composite(v)
    gloss(img, box, 200, 35)
    rim(img, box, 200, (255, 255, 255, 40), 4)


def device_body(img, box, r=70, depth=36, top=(78, 84, 96), bot=(30, 33, 40)):
    """3D box: darker extrusion down-right, glossy front face."""
    x0, y0, x1, y1 = box
    shadow(img, (x0 + 10, y0 + 30, x1 + 30, y1 + 50), r, off=(0, 0), blur=36, alpha=200)
    for i in range(depth, 0, -2):
        k = 0.45 + 0.25 * (1 - i / depth)
        c = tuple(int(v * k) for v in bot)
        ImageDraw.Draw(img).rounded_rectangle((x0 + i, y0 + i, x1 + i, y1 + i), r, fill=c + (255,))
    fill_grad(img, box, r, top, bot)
    gloss(img, box, r, 80)
    rim(img, box, r, (255, 255, 255, 60), 5)


def screen(img, box, r=30):
    x0, y0, x1, y1 = box
    ImageDraw.Draw(img).rounded_rectangle((x0 - 8, y0 - 8, x1 + 8, y1 + 8), r + 8, fill=(8, 9, 12, 255))
    fill_grad(img, box, r, (16, 24, 30), (4, 6, 9))
    # grid
    g = layer()
    d = ImageDraw.Draw(g)
    for x in range(int(x0), int(x1), 44):
        d.line((x, y0, x, y1), fill=(120, 160, 180, 28), width=2)
    for y in range(int(y0), int(y1), 44):
        d.line((x0, y, x1, y), fill=(120, 160, 180, 28), width=2)
    g.putalpha(ImageChops.multiply(g.getchannel("A"), rrect_mask(box, r)))
    img.alpha_composite(g)


def screen_glass(img, box, r=30):
    gloss(img, box, r, 55)


def knob(img, cx, cy, rad, col):
    shadow(img, (cx - rad, cy - rad, cx + rad, cy + rad), rad, off=(6, 10), blur=10, alpha=180)
    fill_grad(img, (cx - rad, cy - rad, cx + rad, cy + rad), rad, tuple(min(255, c + 60) for c in col), tuple(c // 2 for c in col))
    gloss(img, (cx - rad, cy - rad, cx + rad, cy + rad), rad, 120)


def led(img, cx, cy, rad, col):
    glow_draw(img, lambda d, c: d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=c), col, blur=(18, 6))


def wave_pts(x0, x1, yc, amp, cycles, n=200, phase=0.0):
    return [(x0 + (x1 - x0) * i / n, yc - amp * math.sin(phase + 2 * math.pi * cycles * i / n)) for i in range(n + 1)]


def compass_badge(img, cx, cy, rad, accent):
    """Small Nomad mark: metal ring with a north needle."""
    shadow(img, (cx - rad, cy - rad, cx + rad, cy + rad), rad, off=(4, 10), blur=10, alpha=170)
    fill_grad(img, (cx - rad, cy - rad, cx + rad, cy + rad), rad, (215, 220, 228), (110, 116, 126))
    ir = rad * 0.74
    fill_grad(img, (cx - ir, cy - ir, cx + ir, cy + ir), ir, (22, 26, 34), (8, 10, 14))
    d = ImageDraw.Draw(img)
    n = rad * 0.62
    w = rad * 0.22
    d.polygon([(cx, cy - n), (cx + w, cy), (cx - w, cy)], fill=(255, 80, 70, 255))
    d.polygon([(cx, cy + n), (cx + w, cy), (cx - w, cy)], fill=(230, 232, 236, 255))
    d.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=(40, 40, 40, 255))
    gloss(img, (cx - rad, cy - rad, cx + rad, cy + rad), rad, 110)


# ---------- glyphs (glowing subject drawn in a box) ----------
def g_av(img, box, col):
    x0, y0, x1, y1 = box
    w = x1 - x0
    bars = [(200, 200, 200), (200, 200, 0), (0, 200, 200), (0, 200, 0), (200, 0, 200), (200, 0, 0), (0, 0, 200)]
    bh = (y1 - y0) * 0.30
    bw = w / len(bars)
    d = ImageDraw.Draw(img)
    for i, c in enumerate(bars):
        d.rectangle((x0 + i * bw, y0, x0 + (i + 1) * bw, y0 + bh), fill=tuple(int(v * 0.55) for v in c) + (255,))
    pts = wave_pts(x0 + 10, x1 - 10, y0 + (y1 - y0) * 0.66, (y1 - y0) * 0.22, 1.5)
    glow_draw(img, lambda dd, c: dd.line(pts, fill=c, width=12, joint="curve"), col)


def g_net(img, box, col):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rw, rh = (x1 - x0) * 0.36, (y1 - y0) * 0.32
    nodes = [(cx, cy)] + [(cx + rw * math.cos(a), cy + rh * math.sin(a)) for a in [math.radians(t) for t in (200, 270, 340, 30, 150)]]

    def f(d, c):
        for p in nodes[1:]:
            d.line((nodes[0], p), fill=c, width=9)
        for i, p in enumerate(nodes):
            r = 30 if i == 0 else 20
            d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=c)
    glow_draw(img, f, col)


def g_wifi(img, box, col):
    x0, y0, x1, y1 = box
    cx, by = (x0 + x1) / 2, y1 - 30

    def f(d, c):
        for i, rr in enumerate((70, 140, 210)):
            d.arc((cx - rr, by - rr, cx + rr, by + rr), 225, 315, fill=c, width=26)
        d.ellipse((cx - 22, by - 22, cx + 22, by + 22), fill=c)
    glow_draw(img, f, col)


def g_pcap(img, box, col):
    x0, y0, x1, y1 = box
    rows = 4
    rh = (y1 - y0) / rows
    widths = [(0.05, 0.30, 0.42, 0.70, 0.78, 0.95), (0.10, 0.55, 0.62, 0.90), (0.05, 0.22, 0.30, 0.60, 0.68, 0.85), (0.15, 0.45, 0.52, 0.95)]

    def f(d, c):
        for r, ws in enumerate(widths):
            yy = y0 + r * rh + rh * 0.25
            for a, b in zip(ws[::2], ws[1::2]):
                d.rounded_rectangle((x0 + (x1 - x0) * a, yy, x0 + (x1 - x0) * b, yy + rh * 0.42), 10, fill=c)
    glow_draw(img, f, col, blur=(22, 8))


def g_display(img, box, col):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rr = min(x1 - x0, y1 - y0) * 0.30

    def f(d, c):
        d.arc((cx - rr, cy - rr, cx + rr, cy + rr), 300, 240, fill=c, width=24)
        d.line((cx, cy - rr - 18, cx, cy - 6), fill=c, width=24)
    glow_draw(img, f, col)


def g_mcp(img, box, col):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    s = min(x1 - x0, y1 - y0) * 0.22

    def f(d, c):
        # two linked chain rings = "connect anywhere"
        d.rounded_rectangle((cx - 2.1 * s, cy - s * 0.7, cx + 0.2 * s, cy + s * 0.7), s * 0.7, outline=c, width=22)
        d.rounded_rectangle((cx - 0.2 * s, cy - s * 0.7, cx + 2.1 * s, cy + s * 0.7), s * 0.7, outline=c, width=22)
    glow_draw(img, f, col)


GLYPH = {"av-tester": g_av, "net-tools": g_net, "wifi-share": g_wifi, "packet-capture": g_pcap,
         "display-control": g_display, "mcp": g_mcp}


# ---------- styles ----------
def style_device(key, accent, with_bg=True):
    img = layer()
    if with_bg:
        background(img, accent)
    if key == "display-control":
        # TV on a stand
        d = ImageDraw.Draw(img)
        fill_grad(img, (440, 720, 584, 800), 10, (90, 96, 108), (40, 44, 52))
        fill_grad(img, (330, 790, 694, 830), 20, (110, 116, 128), (40, 44, 52))
        body = (150, 220, 874, 730)
        device_body(img, body, 40, 26)
        scr = (185, 255, 839, 690)
    elif key == "wifi-share":
        body = (210, 560, 814, 790)
        device_body(img, body, 60, 30)
        scr = None
        for i, x in enumerate(range(300, 700, 90)):
            led(img, x, 675, 16, accent if i < 3 else (90, 255, 140))
        g_wifi(img, (262, 170, 762, 560), accent)
    elif key == "net-tools":
        body = (150, 470, 874, 740)
        device_body(img, body, 40, 30)
        d = ImageDraw.Draw(img)
        for i in range(6):
            x = 200 + i * 108
            d.rounded_rectangle((x, 560, x + 84, 660), 8, fill=(6, 7, 9, 255))
            d.rectangle((x + 22, 640, x + 62, 660), fill=(30, 32, 36, 255))
            led(img, x + 14, 540, 9, (90, 255, 140))
            led(img, x + 70, 540, 9, (255, 190, 60) if i % 2 else (90, 255, 140))
        g_net(img, (220, 130, 804, 470), accent)
        scr = None
    else:
        body = (190, 180, 834, 830)
        device_body(img, body, 80, 36)
        scr = (250, 250, 774, 640)
        knob(img, 712, 735, 46, accent if key != "av-tester" else (255, 150, 40))
        for i in range(3):
            led(img, 300 + i * 70, 735, 14, (90, 255, 140) if i == 0 else (60, 70, 80))
    if scr:
        screen(img, scr, 26)
        inner = (scr[0] + 40, scr[1] + 40, scr[2] - 40, scr[3] - 40)
        GLYPH[key](img, inner, accent)
        screen_glass(img, scr, 26)
    return img


# Name shown on the icon (Ted: the app name on the button, no compass badge).
SHORT = {"av-tester": "AV TESTER", "net-tools": "NET TOOLS", "wifi-share": "WIFI SHARE",
         "packet-capture": "PCAP", "display-control": "DISPLAY", "mcp": "MCP"}


def fit_font(text, maxw, start, minsize=60):
    size = start
    while size > minsize:
        f = ImageFont.truetype(FONT, size)
        if f.getlength(text) <= maxw:
            return f
        size -= 4
    return ImageFont.truetype(FONT, minsize)


def text_glow(img, xy, text, font, fill, glow, anchor="mm"):
    l = layer()
    ImageDraw.Draw(l).text(xy, text, font=font, fill=glow + (230,), anchor=anchor)
    img.alpha_composite(l.filter(ImageFilter.GaussianBlur(14)))
    sh = layer()
    ImageDraw.Draw(sh).text((xy[0] + 4, xy[1] + 8), text, font=font, fill=(0, 0, 0, 200), anchor=anchor)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5)))
    ImageDraw.Draw(img).text(xy, text, font=font, fill=fill, anchor=anchor)


def style_labeled(key, accent, name_on_top=False):
    """Device art, scaled down, with NOMAD and the app name as text.
    Default: NOMAD on top, app name across the bottom. name_on_top swaps them."""
    img = layer()
    background(img, accent)
    dev = style_device(key, accent, with_bg=False)
    k = 0.64
    dev = dev.resize((int(S * k), int(S * k)), Image.LANCZOS)
    img.alpha_composite(dev, (int((S - S * k) / 2), 205 if not name_on_top else 235))
    brand = ImageFont.truetype(FONT, 118)
    name = SHORT[key]
    f = fit_font(name, S - 170, 168)
    if name_on_top:
        text_glow(img, (S / 2, 190), name, f, accent + (255,), accent)
        text_glow(img, (S / 2, 878), "NOMAD", brand, (240, 244, 250, 255), accent)
    else:
        text_glow(img, (S / 2, 178), "NOMAD", brand, (240, 244, 250, 255), accent)
        text_glow(img, (S / 2, 868), name, f, accent + (255,), accent)
    return img


def style_compass(key, accent):
    img = layer()
    background(img, accent)
    cx, cy, R = S / 2, S / 2 + 10, 380
    shadow(img, (cx - R, cy - R, cx + R, cy + R), R, off=(0, 34), blur=40, alpha=200)
    fill_grad(img, (cx - R, cy - R, cx + R, cy + R), R, (230, 234, 240), (90, 96, 106))
    r2 = R * 0.86
    fill_grad(img, (cx - r2, cy - r2, cx + r2, cy + r2), r2, (60, 64, 72), (150, 156, 166))
    r3 = R * 0.80
    fill_grad(img, (cx - r3, cy - r3, cx + r3, cy + r3), r3, (22, 26, 34), (6, 8, 12))
    d = ImageDraw.Draw(img)
    for t in range(0, 360, 15):
        a = math.radians(t)
        l1 = r3 * (0.86 if t % 90 else 0.78)
        d.line((cx + l1 * math.sin(a), cy - l1 * math.cos(a), cx + r3 * 0.95 * math.sin(a), cy - r3 * 0.95 * math.cos(a)),
               fill=(200, 205, 215, 200 if t % 90 == 0 else 110), width=8 if t % 90 == 0 else 4)
    # north marker
    d.polygon([(cx, cy - R + 8), (cx + 34, cy - R + 64), (cx - 34, cy - R + 64)], fill=(255, 80, 70, 255))
    inner = (cx - r3 * 0.62, cy - r3 * 0.55, cx + r3 * 0.62, cy + r3 * 0.55)
    GLYPH[key](img, inner, accent)
    gloss(img, (cx - r3, cy - r3, cx + r3, cy + r3), r3, 70)
    gloss(img, (cx - R, cy - R, cx + R, cy + R), R, 60)
    return img


def render(style, key, accent):
    fn = {"device": style_device, "compass": style_compass, "labeled": style_labeled,
          "labeled-top": lambda k, a: style_labeled(k, a, True)}[style]
    img = fn(key, accent)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", choices=["labeled", "labeled-top", "device", "compass"], default="labeled")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sheet")
    ap.add_argument("--only")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tiles = []
    for key, label, accent in APPS:
        if a.only and key != a.only:
            continue
        big = render(a.style, key, accent)
        i256 = big.resize((256, 256), Image.LANCZOS)
        i256.save(os.path.join(a.out, f"{key}.png"))
        big.resize((100, 100), Image.LANCZOS).save(os.path.join(a.out, f"{key}_100.png"))
        tiles.append((label, i256))
    if a.sheet:
        f = ImageFont.truetype(FONT, 18)
        W = 280 * len(tiles) + 20
        sheet = Image.new("RGB", (W, 330), (24, 26, 30))
        d = ImageDraw.Draw(sheet)
        for i, (label, t) in enumerate(tiles):
            sheet.paste(t, (20 + i * 280, 20), t)
            tw = d.textlength("Nomad " + label.title(), font=f)
            d.text((20 + i * 280 + 128 - tw / 2, 290), "Nomad " + label.title().replace("Av ", "AV ").replace("Wifi", "WiFi").replace("Mcp", "MCP"), fill=(230, 230, 230), font=f)
        sheet.save(a.sheet)


if __name__ == "__main__":
    main()
