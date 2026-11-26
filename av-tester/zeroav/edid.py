"""Read the connected display's EDID and turn it into plain English.

The EDID is the block of data every HDMI display sends to say who made it
and what it can show and play. Linux exposes it at
/sys/class/drm/card*-HDMI-A-*/edid. This module decodes the parts an AV
tech cares about: maker, model, serial, build date, screen size, native
resolution, every video mode, audio formats, speakers, HDR, color depth
and HDMI capabilities. No extra packages are needed.

    python3 -m zeroav.edid            # print the connected display's EDID
    python3 -m zeroav.edid file.bin   # decode a saved EDID file
"""
from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass, field

# Fastest pixel clock the CardputerZero's HDMI (Pi VC4, BCM2837) can send.
MAX_PIXEL_MHZ = 162.0

# PNP IDs of common display and AV makers, used when the system's
# pnp.ids list (hwdata package) isn't installed.
VENDORS = {
    "AAC": "AcerView", "ACI": "Asus", "ACR": "Acer", "AOC": "AOC", "AUO": "AU Optronics",
    "AUS": "Asus", "BNQ": "BenQ", "BOE": "BOE", "CMN": "Chimei Innolux", "CMO": "Chi Mei",
    "CPQ": "Compaq", "CRS": "Crestron", "DEL": "Dell", "DON": "Denon", "ELO": "Elo Touch",
    "EIZ": "Eizo", "ENC": "Eizo", "EPI": "Envision", "EPS": "Epson", "EXT": "Extron",
    "FUS": "Fujitsu", "GBT": "Gigabyte", "GGL": "Google", "GSM": "LG Electronics",
    "HEC": "Hisense", "HIT": "Hitachi", "HPN": "HP", "HSD": "HannStar", "HWP": "HP",
    "HRE": "Haier", "IVM": "Iiyama", "JVC": "JVC", "KDS": "Korea Data Systems",
    "LEN": "Lenovo", "LGD": "LG Display", "LPL": "LG Philips", "MAX": "Maxdata",
    "MEI": "Panasonic", "MED": "Medion", "MSI": "MSI", "MTC": "Mitac", "NEC": "NEC",
    "NOK": "Nokia", "NVD": "Nvidia", "ONK": "Onkyo", "OPT": "Optoma", "PHL": "Philips",
    "PIO": "Pioneer", "PNR": "Planar", "QDS": "Quanta Display", "RAT": "Rationalizer",
    "RHT": "Red Hat (virtual)", "SAM": "Samsung", "SAN": "Sanyo", "SDC": "Samsung Display",
    "SEC": "Seiko Epson", "SGI": "SGI", "SHP": "Sharp", "SII": "Silicon Image",
    "SKG": "Skyworth", "SNY": "Sony", "SPT": "Sceptre", "STN": "Samsung", "TCL": "TCL",
    "TOS": "Toshiba", "TSB": "Toshiba", "TTE": "TTE (TCL)", "VIZ": "Vizio",
    "VSC": "ViewSonic", "VTK": "Vivitek", "YMH": "Yamaha", "MRN": "Marantz",
    "NEX": "Nexgen", "BRM": "Barco", "CHR": "Christie", "DPL": "Digital Projection",
    "INF": "InFocus", "MIT": "Mitsubishi", "MEL": "Mitsubishi", "RIC": "Ricoh",
    "SYN": "Synaptics", "ATN": "Atlona", "KRM": "Kramer", "AMX": "AMX", "BMD": "Blackmagic",
    "AJA": "AJA", "PLY": "Polycom", "CSO": "California Institute (Cisco)", "LTM": "Lightware",
    "ITE": "ITE Tech", "MST": "MStar", "RTK": "Realtek", "XMI": "Xiaomi", "VES": "Vestel",
}

ESTABLISHED = [  # byte 35 bit 7 .. byte 37 bit 7
    (720, 400, 70), (720, 400, 88), (640, 480, 60), (640, 480, 67), (640, 480, 72),
    (640, 480, 75), (800, 600, 56), (800, 600, 60), (800, 600, 72), (800, 600, 75),
    (832, 624, 75), (1024, 768, 87), (1024, 768, 60), (1024, 768, 70), (1024, 768, 75),
    (1280, 1024, 75), (1152, 870, 75),
]

# CTA-861 video codes: VIC -> (width, height, Hz, interlaced, pixel clock MHz)
_V = {}


def _add(vics, w, h, hz, i, mhz):
    for v in vics:
        _V[v] = (w, h, hz, i, mhz)


for _vics, _m in [
    ((1,), (640, 480, 60, 0, 25.175)), ((2, 3), (720, 480, 60, 0, 27)), ((4,), (1280, 720, 60, 0, 74.25)),
    ((5,), (1920, 1080, 60, 1, 74.25)), ((6, 7), (1440, 480, 60, 1, 27)), ((8, 9), (1440, 240, 60, 0, 27)),
    ((10, 11), (2880, 480, 60, 1, 54)), ((12, 13), (2880, 240, 60, 0, 54)), ((14, 15), (1440, 480, 60, 0, 54)),
    ((16,), (1920, 1080, 60, 0, 148.5)), ((17, 18), (720, 576, 50, 0, 27)), ((19,), (1280, 720, 50, 0, 74.25)),
    ((20,), (1920, 1080, 50, 1, 74.25)), ((21, 22), (1440, 576, 50, 1, 27)), ((23, 24), (1440, 288, 50, 0, 27)),
    ((25, 26), (2880, 576, 50, 1, 54)), ((27, 28), (2880, 288, 50, 0, 54)), ((29, 30), (1440, 576, 50, 0, 54)),
    ((31,), (1920, 1080, 50, 0, 148.5)), ((32,), (1920, 1080, 24, 0, 74.25)), ((33,), (1920, 1080, 25, 0, 74.25)),
    ((34,), (1920, 1080, 30, 0, 74.25)), ((35, 36), (2880, 480, 60, 0, 108)), ((37, 38), (2880, 576, 50, 0, 108)),
    ((39,), (1920, 1080, 50, 1, 72)), ((40,), (1920, 1080, 100, 1, 148.5)), ((41,), (1280, 720, 100, 0, 148.5)),
    ((42, 43), (720, 576, 100, 0, 54)), ((44, 45), (1440, 576, 100, 1, 54)), ((46,), (1920, 1080, 120, 1, 148.5)),
    ((47,), (1280, 720, 120, 0, 148.5)), ((48, 49), (720, 480, 120, 0, 54)), ((50, 51), (1440, 480, 120, 1, 54)),
    ((52, 53), (720, 576, 200, 0, 108)), ((54, 55), (1440, 576, 200, 1, 108)), ((56, 57), (720, 480, 240, 0, 108)),
    ((58, 59), (1440, 480, 240, 1, 108)), ((60, 65), (1280, 720, 24, 0, 59.4)), ((61, 66), (1280, 720, 25, 0, 74.25)),
    ((62, 67), (1280, 720, 30, 0, 74.25)), ((63, 78), (1920, 1080, 120, 0, 297)), ((64, 77), (1920, 1080, 100, 0, 297)),
    ((68,), (1280, 720, 50, 0, 74.25)), ((69,), (1280, 720, 60, 0, 74.25)), ((70,), (1280, 720, 100, 0, 148.5)),
    ((71,), (1280, 720, 120, 0, 148.5)), ((72,), (1920, 1080, 24, 0, 74.25)), ((73,), (1920, 1080, 25, 0, 74.25)),
    ((74,), (1920, 1080, 30, 0, 74.25)), ((75,), (1920, 1080, 50, 0, 148.5)), ((76,), (1920, 1080, 60, 0, 148.5)),
    ((79,), (1680, 720, 24, 0, 59.4)), ((80,), (1680, 720, 25, 0, 59.4)), ((81,), (1680, 720, 30, 0, 59.4)),
    ((82,), (1680, 720, 50, 0, 82.5)), ((83,), (1680, 720, 60, 0, 99)), ((84,), (1680, 720, 100, 0, 165)),
    ((85,), (1680, 720, 120, 0, 198)), ((86,), (2560, 1080, 24, 0, 99)), ((87,), (2560, 1080, 25, 0, 90)),
    ((88,), (2560, 1080, 30, 0, 118.8)), ((89,), (2560, 1080, 50, 0, 185.625)), ((90,), (2560, 1080, 60, 0, 198)),
    ((91,), (2560, 1080, 100, 0, 371.25)), ((92,), (2560, 1080, 120, 0, 495)),
    ((93, 103), (3840, 2160, 24, 0, 297)), ((94, 104), (3840, 2160, 25, 0, 297)), ((95, 105), (3840, 2160, 30, 0, 297)),
    ((96, 106), (3840, 2160, 50, 0, 594)), ((97, 107), (3840, 2160, 60, 0, 594)),
    ((98,), (4096, 2160, 24, 0, 297)), ((99,), (4096, 2160, 25, 0, 297)), ((100,), (4096, 2160, 30, 0, 297)),
    ((101,), (4096, 2160, 50, 0, 594)), ((102,), (4096, 2160, 60, 0, 594)),
    ((108, 109), (1280, 720, 48, 0, 90)), ((110,), (1680, 720, 48, 0, 99)), ((111, 112), (1920, 1080, 48, 0, 148.5)),
    ((113,), (2560, 1080, 48, 0, 198)), ((114, 116), (3840, 2160, 48, 0, 594)), ((115,), (4096, 2160, 48, 0, 594)),
    ((117, 119), (3840, 2160, 100, 0, 1188)), ((118, 120), (3840, 2160, 120, 0, 1188)),
    ((121,), (5120, 2160, 24, 0, 396)), ((122,), (5120, 2160, 25, 0, 396)), ((123,), (5120, 2160, 30, 0, 396)),
    ((124,), (5120, 2160, 48, 0, 742.5)), ((125,), (5120, 2160, 50, 0, 742.5)), ((126,), (5120, 2160, 60, 0, 742.5)),
    ((127,), (5120, 2160, 100, 0, 1485)),
]:
    _add(_vics, *_m)

AUDIO_FORMATS = {
    1: "LPCM", 2: "Dolby Digital (AC-3)", 3: "MPEG-1", 4: "MP3", 5: "MPEG-2", 6: "AAC",
    7: "DTS", 8: "ATRAC", 9: "DSD (SACD)", 10: "Dolby Digital Plus", 11: "DTS-HD",
    12: "Dolby TrueHD / Atmos (MAT)", 13: "DST", 14: "WMA Pro",
}
AUDIO_RATES = ["32", "44.1", "48", "88.2", "96", "176.4", "192"]
SPEAKERS = ["Front L/R", "LFE (sub)", "Front center", "Rear L/R", "Rear center",
            "Front L/R center", "Rear L/R center", "Front L/R wide", "Top front L/R",
            "Top center", "Top front center"]
INTERFACES = {1: "DVI", 2: "HDMI-a", 3: "HDMI-b", 4: "MDDI", 5: "DisplayPort"}


@dataclass
class VideoMode:
    w: int
    h: int
    hz: float
    interlaced: bool = False
    mhz: float = 0.0
    source: str = ""        # "native", "CTA", "detailed", "standard", "established"
    native: bool = False

    @property
    def label(self) -> str:
        hz = f"{self.hz:.2f}".rstrip("0").rstrip(".")
        return f"{self.w}x{self.h}{'i' if self.interlaced else 'p'} @ {hz} Hz"

    @property
    def too_fast(self) -> bool:
        return self.mhz > MAX_PIXEL_MHZ + 0.5


@dataclass
class EdidInfo:
    raw: bytes
    connector: str = ""
    vendor_id: str = ""
    vendor: str = ""
    product_code: int = 0
    serial_number: int = 0
    serial_text: str = ""
    name: str = ""
    week: int = 0
    year: int = 0
    model_year: bool = False
    version: str = ""
    digital: bool = True
    interface: str = ""
    bit_depth: int = 0
    width_cm: int = 0
    height_cm: int = 0
    gamma: float = 0.0
    range_text: str = ""
    preferred: VideoMode | None = None
    modes: list[VideoMode] = field(default_factory=list)
    audio: list[str] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)
    hdr: list[str] = field(default_factory=list)
    hdr_luminance: str = ""
    colorimetry: list[str] = field(default_factory=list)
    color_formats: list[str] = field(default_factory=list)
    deep_color: list[str] = field(default_factory=list)
    hdmi: list[str] = field(default_factory=list)
    underscan: bool | None = None
    checksum_ok: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def diagonal_in(self) -> float:
        if self.width_cm and self.height_cm:
            return (self.width_cm ** 2 + self.height_cm ** 2) ** 0.5 / 2.54
        return 0.0


def _pnp_name(code: str) -> str:
    for path in ("/usr/share/hwdata/pnp.ids", "/usr/share/misc/pnp.ids"):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line[:3] == code:
                        return line[3:].strip()
        except OSError:
            continue
    return VENDORS.get(code, "")


def _dtd(b: bytes) -> VideoMode | None:
    clk = b[0] | b[1] << 8
    if not clk:
        return None
    ha = b[2] | (b[4] >> 4) << 8
    hb = b[3] | (b[4] & 0xF) << 8
    va = b[5] | (b[7] >> 4) << 8
    vb = b[6] | (b[7] & 0xF) << 8
    inter = bool(b[17] & 0x80)
    mhz = clk / 100.0
    total = (ha + hb) * (va + vb)
    hz = mhz * 1e6 / total if total else 0
    if inter:
        va *= 2
        hz *= 2
    return VideoMode(ha, va, round(hz, 3), inter, mhz, "detailed")


def _descriptor(info: EdidInfo, b: bytes) -> None:
    tag = b[3]
    text = bytes(b[5:18]).split(b"\n")[0].decode("ascii", "replace").strip()
    if tag == 0xFC:
        info.name = (info.name + " " + text).strip() if info.name else text
    elif tag == 0xFF:
        info.serial_text = text
    elif tag == 0xFD:
        vmin, vmax, hmin, hmax, clk = b[5], b[6], b[7], b[8], b[9] * 10
        if b[4] & 0x02:
            vmax += 255
        if b[4] & 0x01:
            vmin += 255
        if b[4] & 0x08:
            hmax += 255
        if b[4] & 0x04:
            hmin += 255
        info.range_text = f"{vmin}-{vmax} Hz vertical, {hmin}-{hmax} kHz horizontal, max {clk} MHz"


def _std_timing(b0: int, b1: int, version: tuple[int, int]) -> VideoMode | None:
    if (b0, b1) in ((1, 1), (0, 0), (0x20, 0x20)):
        return None
    w = (b0 + 31) * 8
    asp = b1 >> 6
    if asp == 0:
        h = w if version < (1, 3) else w * 10 // 16
    elif asp == 1:
        h = w * 3 // 4
    elif asp == 2:
        h = w * 4 // 5
    else:
        h = w * 9 // 16
    return VideoMode(w, h, (b1 & 0x3F) + 60, source="standard")


def _cta(info: EdidInfo, ext: bytes) -> None:
    dtd_start = ext[2]
    flags = ext[3]
    if ext[1] >= 2:
        info.underscan = bool(flags & 0x80)
        if flags & 0x40 and not info.audio:
            info.audio.append("Basic audio (LPCM 2ch)")
        fmts = ["RGB"]
        if flags & 0x20:
            fmts.append("YCbCr 4:4:4")
        if flags & 0x10:
            fmts.append("YCbCr 4:2:2")
        info.color_formats = fmts
    i = 4
    end = dtd_start if 4 <= dtd_start <= 127 else 4
    while i < end:
        tag, ln = ext[i] >> 5, ext[i] & 0x1F
        d = ext[i + 1:i + 1 + ln]
        i += 1 + ln
        if tag == 1:  # audio
            for k in range(0, len(d) - 2, 3):
                fmt = (d[k] >> 3) & 0xF
                ch = (d[k] & 7) + 1
                rates = [r for n, r in enumerate(AUDIO_RATES) if d[k + 1] >> n & 1]
                name = AUDIO_FORMATS.get(fmt, f"format {fmt}")
                extra = ""
                if fmt == 1:
                    bits = [b for n, b in enumerate(("16", "20", "24")) if d[k + 2] >> n & 1]
                    extra = f", {'/'.join(bits)}-bit" if bits else ""
                elif 2 <= fmt <= 8:
                    extra = f", up to {d[k + 2] * 8} kbps"
                rate = f"{'/'.join(rates)} kHz" if rates else ""
                line = f"{name}, {ch}ch, {rate}{extra}"
                if line not in info.audio:
                    info.audio.append(line)
            info.audio = [a for a in info.audio if not a.startswith("Basic audio")] or info.audio
        elif tag == 2:  # video
            for v in d:
                native = False
                vic = v
                if 129 <= v <= 192:
                    vic, native = v & 0x7F, True
                m = _V.get(vic)
                if m:
                    vm = VideoMode(m[0], m[1], m[2], bool(m[3]), m[4], "CTA", native)
                    info.modes.append(vm)
        elif tag == 3 and len(d) >= 3:  # vendor specific
            oui = d[0] | d[1] << 8 | d[2] << 16
            if oui == 0x000C03:
                if len(d) >= 5:
                    info.hdmi.append(f"HDMI 1.x, CEC address {d[3] >> 4}.{d[3] & 15}.{d[4] >> 4}.{d[4] & 15}")
                if len(d) >= 6:
                    dc = [n for bit, n in ((4, "30-bit (10 bpc)"), (5, "36-bit (12 bpc)"), (6, "48-bit (16 bpc)"))
                          if d[5] >> bit & 1]
                    info.deep_color = dc
                    if d[5] & 0x80:
                        info.hdmi.append("Supports AI (ACP/ISRC audio)")
                if len(d) >= 7 and d[6]:
                    info.hdmi.append(f"Max TMDS clock {d[6] * 5} MHz")
            elif oui == 0xC45DD8:
                info.hdmi.append("HDMI 2.x (HDMI Forum block)")
                if len(d) >= 5 and d[4]:
                    info.hdmi.append(f"HDMI 2.x max TMDS {d[4] * 5} MHz")
                if len(d) >= 7 and d[6] >> 4:
                    frl = {1: "3G x3", 2: "6G x3", 3: "6G x4", 4: "8G x4", 5: "10G x4", 6: "12G x4"}
                    info.hdmi.append(f"HDMI 2.1 FRL {frl.get(d[6] >> 4, '?')}")
            elif oui == 0x00001A:
                info.hdmi.append("AMD FreeSync")
        elif tag == 4 and d:  # speaker allocation
            bits = d[0] | (d[1] << 8 if len(d) > 1 else 0)
            info.speakers = [s for n, s in enumerate(SPEAKERS) if bits >> n & 1]
        elif tag == 7 and d:  # extended
            et, x = d[0], d[1:]
            if et == 5 and x:  # colorimetry
                names = ["xvYCC 601", "xvYCC 709", "sYCC 601", "opYCC 601", "opRGB",
                         "BT.2020 cYCC", "BT.2020 YCC", "BT.2020 RGB"]
                info.colorimetry = [n for k, n in enumerate(names) if x[0] >> k & 1]
                if len(x) > 1 and x[1] & 0x80:
                    info.colorimetry.append("DCI-P3")
            elif et == 6 and x:  # HDR static metadata
                eotf = [n for k, n in enumerate(("SDR", "HDR (traditional gamma)",
                                                 "HDR10 (PQ / ST 2084)", "HLG")) if x[0] >> k & 1]
                info.hdr = [e for e in eotf if e != "SDR"] or []
                if len(x) >= 3 and x[2]:
                    lum = 50 * 2 ** (x[2] / 32)
                    info.hdr_luminance = f"max {lum:.0f} nits"
                    if len(x) >= 4 and x[3]:
                        info.hdr_luminance += f", frame avg {50 * 2 ** (x[3] / 32):.0f} nits"
            elif et == 1 and len(x) >= 3:
                oui = x[0] | x[1] << 8 | x[2] << 16
                if oui == 0x00D046:
                    info.hdr.append("Dolby Vision")
                elif oui == 0x90848B:
                    info.hdr.append("HDR10+")
            elif et == 14:
                for v in x:
                    m = _V.get(v & 0x7F if 129 <= v <= 192 else v)
                    if m:
                        info.notes.append(f"4:2:0 only: {m[0]}x{m[1]}p{m[2]}")
                if "YCbCr 4:2:0" not in info.color_formats:
                    info.color_formats.append("YCbCr 4:2:0")
            elif et == 15:
                if "YCbCr 4:2:0" not in info.color_formats:
                    info.color_formats.append("YCbCr 4:2:0")
    # detailed timings at the end of the extension
    j = dtd_start
    while 4 <= j and j + 18 <= 127:
        m = _dtd(ext[j:j + 18])
        if not m:
            break
        info.modes.append(m)
        j += 18


def parse(raw: bytes, connector: str = "") -> EdidInfo:
    info = EdidInfo(raw=raw, connector=connector)
    if len(raw) < 128 or raw[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        info.notes.append("Not a valid EDID (bad header)")
        return info
    for k in range(0, len(raw) // 128):
        if sum(raw[k * 128:(k + 1) * 128]) % 256:
            info.checksum_ok = False
    m = raw[8] << 8 | raw[9]
    info.vendor_id = "".join(chr(64 + (m >> s & 31)) for s in (10, 5, 0))
    info.vendor = _pnp_name(info.vendor_id)
    info.product_code = raw[10] | raw[11] << 8
    info.serial_number = int.from_bytes(raw[12:16], "little")
    info.week, info.year = raw[16], raw[17] + 1990
    info.model_year = raw[16] == 0xFF
    ver = (raw[18], raw[19])
    info.version = f"{ver[0]}.{ver[1]}"
    vi = raw[20]
    info.digital = bool(vi & 0x80)
    if info.digital and ver >= (1, 4):
        info.bit_depth = {1: 6, 2: 8, 3: 10, 4: 12, 5: 14, 6: 16}.get(vi >> 4 & 7, 0)
        info.interface = INTERFACES.get(vi & 0xF, "")
    info.width_cm, info.height_cm = raw[21], raw[22]
    info.gamma = (raw[23] + 100) / 100 if raw[23] != 0xFF else 0
    est = raw[35] << 16 | raw[36] << 8 | raw[37]
    for n, (w, h, hz) in enumerate(ESTABLISHED):
        if est >> (23 - n) & 1:
            info.modes.append(VideoMode(w, h, hz, source="established"))
    for k in range(38, 54, 2):
        sm = _std_timing(raw[k], raw[k + 1], ver)
        if sm:
            info.modes.append(sm)
    for k in range(54, 126, 18):
        b = raw[k:k + 18]
        if b[0] or b[1]:
            dm = _dtd(b)
            if dm and info.preferred is None:
                dm.native = True
                info.preferred = dm
            if dm:
                info.modes.append(dm)
        else:
            _descriptor(info, b)
    for e in range(1, min(raw[126], len(raw) // 128 - 1) + 1):
        ext = raw[e * 128:(e + 1) * 128]
        if ext[0] == 0x02:
            _cta(info, ext)
        elif ext[0] == 0x70:
            info.notes.append("Has a DisplayID block (not decoded)")
    info.modes = _dedupe(info.modes)
    return info


def _dedupe(modes: list[VideoMode]) -> list[VideoMode]:
    best: dict[tuple, VideoMode] = {}
    for m in modes:
        key = (m.w, m.h, round(m.hz), m.interlaced)
        old = best.get(key)
        if old is None:
            best[key] = m
        else:
            old.native = old.native or m.native
            if not old.mhz and m.mhz:
                old.mhz = m.mhz
    return sorted(best.values(), key=lambda v: (v.w * v.h, not v.interlaced, v.hz), reverse=True)


def find_edid() -> tuple[str, bytes] | None:
    """(connector name, EDID bytes) of the first connected HDMI port."""
    for d in sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*")):
        try:
            if open(f"{d}/status").read().strip() != "connected":
                continue
            raw = open(f"{d}/edid", "rb").read()
        except OSError:
            continue
        if raw:
            return os.path.basename(d).split("-", 1)[1], raw
    return None


def read() -> EdidInfo | None:
    found = find_edid()
    return parse(found[1], found[0]) if found else None


# ---- human-readable report ----

def _hz(h: float) -> str:
    return f"{h:.2f}".rstrip("0").rstrip(".")


def sections(info: EdidInfo) -> list[tuple[str, list[str]]]:
    """The EDID as titled sections of short plain-English lines."""
    out: list[tuple[str, list[str]]] = []
    maker = info.vendor or "Unknown maker"
    disp = [f"Maker: {maker} ({info.vendor_id})", f"Model: {info.name or 'not given'}",
            f"Product code: {info.product_code} (0x{info.product_code:04X})"]
    serial = info.serial_text or (str(info.serial_number) if info.serial_number else "not given")
    disp.append(f"Serial: {serial}")
    if info.model_year:
        disp.append(f"Model year: {info.year}")
    elif info.week and info.week <= 54:
        disp.append(f"Made: week {info.week} of {info.year}")
    else:
        disp.append(f"Made: {info.year}")
    if info.width_cm and info.height_cm:
        disp.append(f"Screen: {info.width_cm} x {info.height_cm} cm, about {info.diagonal_in:.0f}\" diagonal")
    else:
        disp.append("Screen: size not given (projector or variable)")
    disp.append(f"EDID version {info.version}, {len(info.raw)} bytes, "
                f"checksum {'OK' if info.checksum_ok else 'BAD'}")
    if info.connector:
        disp.append(f"Port: {info.connector}")
    out.append(("Display", disp))

    vid = []
    if info.preferred:
        p = info.preferred
        vid.append(f"Native: {p.w}x{p.h}{'i' if p.interlaced else 'p'} @ {_hz(p.hz)} Hz")
    if info.interface:
        vid.append(f"Input: {info.interface}")
    if info.bit_depth:
        vid.append(f"Panel color depth: {info.bit_depth}-bit per color")
    if info.deep_color:
        vid.append("Deep color: " + ", ".join(info.deep_color))
    else:
        vid.append("Deep color: 8-bit only")
    if info.color_formats:
        vid.append("Color formats: " + ", ".join(info.color_formats))
    vid.append("HDR: " + (", ".join(info.hdr) if info.hdr else "none (SDR only)"))
    if info.hdr_luminance:
        vid.append("HDR brightness: " + info.hdr_luminance)
    if info.colorimetry:
        vid.append("Wide color: " + ", ".join(info.colorimetry))
    if info.underscan is not None:
        vid.append(f"Underscans by default: {'yes' if info.underscan else 'no'}")
    if info.gamma:
        vid.append(f"Gamma: {info.gamma:.2f}")
    if info.range_text:
        vid.append("Range: " + info.range_text)
    out.append(("Video", vid))

    modes = []
    for m in info.modes:
        tags = []
        if m.native:
            tags.append("native")
        if m.too_fast:
            tags.append("too fast for this device")
        modes.append(m.label + (f"  ({', '.join(tags)})" if tags else ""))
    if any(m.source == "CTA" for m in info.modes):
        modes.append("TV modes at 60, 30 and 24 Hz also run at 59.94, 29.97 and 23.98 Hz.")
    out.append((f"Modes ({len(info.modes)})", modes or ["none listed"]))

    aud = list(info.audio) or ["No audio (DVI or audio not supported)"]
    if info.speakers:
        aud.append("Speakers: " + ", ".join(info.speakers))
    out.append(("Audio", aud))

    hd = list(info.hdmi) or ["No HDMI block (DVI-style display)"]
    out.append(("HDMI", hd + info.notes))
    return out


def text_report(info: EdidInfo | None) -> str:
    if info is None:
        return "No HDMI display connected (no EDID found).\n"
    lines = []
    for title, body in sections(info):
        lines.append(f"== {title} ==")
        lines.extend("  " + b for b in body)
        lines.append("")
    lines.append("== Raw EDID (hex) ==")
    for k in range(0, len(info.raw), 16):
        lines.append("  " + " ".join(f"{x:02x}" for x in info.raw[k:k + 16]))
    return "\n".join(lines) + "\n"


def summary_lines(info: EdidInfo | None) -> list[str]:
    """Flat list of short lines for the 320x170 screen (scrolled)."""
    if info is None:
        return ["No HDMI display connected.", "Connect a display and", "press E again."]
    out = []
    for title, body in sections(info):
        out.append(f"-- {title} --")
        out.extend(body)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(text_report(parse(open(sys.argv[1], "rb").read())), end="")
    else:
        print(text_report(read()), end="")
