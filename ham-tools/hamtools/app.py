"""Ask Elmer Ham Tools: the app. Screens on the LCD, input from the keyboard."""
from __future__ import annotations

import json
import math
import os
import threading
import time

from . import calc as C
from . import geo
from . import icons as IC
from . import lcd as L
from . import nomadgps
from . import nomadui as T
from . import online
from . import prop
from . import sats
from .keys import Keyboard
from .ui import BACK, DOWN, SELECT, UP, EditList, Field, Menu, Message, Screen, nav_key

from . import APP_NAME, __version__, config_dir, migrate

APP_TITLE = "Ask Elmer"
T.set_about(APP_NAME, __version__, extra="Learn more at askelmer.com")
T.ICON_DRAW = IC.draw

HELP_MAIN = (APP_NAME + ": the ham radio tools from askelmer.com in your pocket. Antenna Lab (NEC2 antenna "
             "modelling), band check, RF math, "
             "where and when (distance, heading, sunrise and greyline), propagation, satellite passes, POTA and "
             "SOTA, a station clock with a 10-minute ID timer, and a searchable reference. A USB GPS gives the "
             "time and your location; without one, set your grid in Settings.")
HELP_CALC = ("Up/Down pick a field, OK or Right edits it (red), type, OK saves. The answers below update "
             "as you go; OK on an answer shows it in full. Values are kept for next time.")


def K(text, icon):
    """A key 4-8 label with its icon."""
    return (text, None, icon)


class State:
    """Remembers what you typed in each tool, and your settings."""

    def __init__(self):
        self.path = os.path.join(config_dir(), "state.json")
        try:
            self.d = json.load(open(self.path))
        except (OSError, ValueError):
            self.d = {}

    def get(self, tool, defaults):
        return {**defaults, **self.d.get(tool, {})}

    def put(self, tool, values):
        self.d[tool] = values
        self.save()

    def save(self):
        try:
            os.makedirs(config_dir(), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(self.d, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def setting(self, key, default=""):
        return self.d.get("settings", {}).get(key, default)

    def set(self, key, value):
        self.d.setdefault("settings", {})[key] = value
        self.save()

    @property
    def license(self):
        return self.d.get("license", "Technician")

    @license.setter
    def license(self, v):
        self.d["license"] = v
        self.save()

    @property
    def miles(self) -> bool:
        return self.setting("units", "mi") == "mi"


class App:
    def __init__(self, panel: L.Panel, kb: Keyboard | None, gps=None):
        self.panel, self.kb = panel, kb
        self.st = State()
        self.gps = gps
        self.stack: list[Screen] = []
        self.helpview = None
        self.dirty = True
        self.quit = False

    # -- where and when --
    def location(self):
        """(lat, lon, label): live GPS, else your grid from Settings, else the last GPS fix."""
        fix = self.gps.fix() if self.gps else None
        if fix:
            return fix["lat"], fix["lon"], "GPS"
        g = C.norm_grid(self.st.setting("grid", ""))
        if g:
            la, lo = C.grid_center(g)
            return la, lo, "your grid"
        last = self.gps.last() if self.gps else None
        if last and last.get("lat") is not None:
            return last["lat"], last["lon"], "last GPS fix"
        return None

    def utc(self) -> float:
        return self.gps.utc() if self.gps else time.time()

    def dist(self, km: float) -> str:
        return f"{C.fmt(km / 1.609344, 3)} mi" if self.st.miles else f"{C.fmt(km, 3)} km"

    # -- screens --
    def push(self, s):
        self.stack.append(s)
        self.dirty = True

    def pop(self, s=None):
        if s is None:
            if len(self.stack) > 1:
                self.stack.pop()
            else:
                self.quit = True
        elif s in self.stack:
            self.stack.remove(s)
        self.dirty = True

    def open_about(self):
        """The About screen (shown like Fn+H help, ESC closes it)."""
        self.helpview = T.AboutView()
        self.dirty = True

    def wake(self):
        self.dirty = True

    def task(self, title, label, fn, done):
        """Run fn in a worker thread behind a Busy screen, then done(result)."""
        def finish(result, error):
            if error is not None:
                self.push(Message(self, "Problem", str(error) or error.__class__.__name__, L.BAD))
            else:
                done(result)
        self.push(Busy(self, title, label, fn, finish))

    def run(self):
        self.push(Home(self))
        last = 0.0
        while not self.quit:
            keys = self.kb.poll(0.1) if self.kb else (time.sleep(0.1) or [])
            for k in keys:
                if self.stack:
                    self.dispatch(k)
                self.dirty = True
            if self.stack:
                self.stack[-1].tick()
            now = time.monotonic()
            if self.dirty or now - last > 1.0:
                self.draw()
                last = now
                self.dirty = False
        self.st.save()

    def dispatch(self, k):
        top = self.stack[-1]
        if self.helpview is not None:
            if self.helpview.handle(k) == "close":
                self.helpview = None
            return
        if k.name == "help":
            self.helpview = T.HelpView(top.title, top.help or HELP_MAIN, top.keybar())
            return
        if not top.text_entry and top.soft(k):
            return
        top.key(k if top.text_entry else nav_key(k))

    def draw(self):
        if not self.stack:
            return
        surf = self.panel.surf
        if self.helpview is not None:
            self.helpview.render(surf, self.panel.fonts)
            self.panel.flush()
            return
        s = self.stack[-1]
        rows, sel = s.rows()
        T.render(surf, s.title, rows, s.hint, sel, s.right(), self.panel.fonts, s.keybar())
        paint = getattr(s, "paint", None)
        if paint:
            paint(surf, self.panel.fonts)
        self.panel.flush()


class Busy(Screen):
    """Runs a job in a thread; the screen keeps drawing."""
    hint = ""

    def __init__(self, app, title, label, fn, finish):
        super().__init__(app)
        self.title, self.label, self.finish = title, label, finish
        self.t0 = time.monotonic()
        self.result = self.error = None
        self.done = False

        def work():
            try:
                self.result = fn()
            except Exception as e:   # noqa: BLE001 - shown to the user
                self.error = e
            self.done = True
        threading.Thread(target=work, daemon=True).start()

    def rows(self):
        dots = "." * (1 + int(time.monotonic() - self.t0) % 3)
        return [(f"{self.label}{dots}", L.FG), (f"{time.monotonic() - self.t0:.0f} s", L.DIM)], None

    def tick(self):
        self.app.wake()
        if self.done:
            self.app.pop(self)
            self.finish(self.result, self.error)

    def key(self, k):
        pass


# ---- a calculator screen: input fields on top, answers below ------------------------------

class Calc(Screen):
    """inputs: [Field]; defaults: {key: text}; compute(values) -> [(label, value[, color])]."""
    help = HELP_CALC
    tool = ""
    answers_header = True

    def __init__(self, app, title, inputs, defaults):
        super().__init__(app)
        self.title = title
        self.inputs = inputs
        self.values = app.st.get(self.tool or title, defaults)
        self.results = []
        self.build()

    def compute(self, v) -> list:
        return []

    def extra_fields(self) -> list:
        return []

    def build(self, keep=None):
        try:
            self.results = self.compute(self.values)
        except ValueError as e:
            self.results = [(str(e), "", L.BAD)]
        fields = list(self.inputs) + self.extra_fields()
        if self.results and self.answers_header:
            fields.append(Field("_h", "Answers", "header"))
        vals = dict(self.values)
        for i, r in enumerate(self.results):
            if r[0] == "--":
                fields.append(Field(f"_s{i}", r[1], "header"))
                continue
            color = r[2] if len(r) > 2 else None
            fields.append(Field(f"r{i}", r[0], "info", color=color))
            vals[f"r{i}"] = r[1]
        old = getattr(self, "form", None)
        self.form = EditList(fields, vals)
        if old is not None:
            self.form.sel, self.form.top = min(old.sel, len(fields) - 1), old.top

    @property
    def text_entry(self):
        return self.form.editing

    @property
    def hint(self):
        return self.form.hint()

    def rows(self):
        return self.form.view(self.nrows), None

    def save(self):
        self.app.st.put(self.tool or self.title, {f.key: self.values.get(f.key, "") for f in self.inputs})

    def key(self, k):
        ev = self.form.handle(k)
        if not ev:
            return
        kind, _, key = ev.partition(":")
        if kind == "back":
            self.save()
            self.app.pop(self)
        elif kind == "changed" and not key.startswith("r"):
            self.values[key] = self.form.values[key]
            self.changed(key)
            self.build()
        elif kind == "action":
            self.action(key)
        elif kind == "info":
            i = int(key[1:])
            if i < len(self.results):
                r = self.results[i]
                self.app.push(Message(self.app, self.title, f"{r[0]}\n{r[1]}" if r[1] else r[0]))

    def changed(self, key):
        pass

    def action(self, key):
        pass

    def tick(self):
        pass


def num(v, key, **kw):
    """Parse one field; a bad entry raises ValueError naming the field."""
    try:
        return C.parse_number(v.get(key), **kw)
    except ValueError as e:
        raise ValueError(f"{key}: {e}")


def ago(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 172800:
        return f"{seconds / 3600:.0f} h ago"
    return f"{seconds / 86400:.0f} days ago"


# ---- Band check ------------------------------------------------------------------------

SEG_CW = (0x2E, 0x8C, 0xA8)      # CW and data: teal
SEG_PHONE = (0xE8, 0xA3, 0x3D)   # phone: amber
SEG_ALL = (0x5C, 0xC0, 0x8A)     # all modes: green


def seg_color(modes: str):
    m = modes.lower()
    if m.startswith("all") or "channels" in m:
        return SEG_ALL
    if "phone" in m or "ssb" in m:
        return SEG_PHONE
    return SEG_CW


class BandCheck(Calc):
    tool = "band"
    answers_header = False
    help = ("Type a frequency in MHz (or a wavelength in metres). The bar shows the whole band: one strip for "
            "each license class, teal for CW and data, amber for phone, green for all modes, and a marker where "
            "you are. Below: may you transmit, the power limit, how far to the edge, what's usually nearby, "
            "and the wavelength. 4 changes your class, 5 and 6 step through the bands, 7 the band plan, 8 opens Antenna Lab "
            "at this frequency.")

    def __init__(self, app):
        super().__init__(app, "Band check", [
            Field("MHz", "Frequency MHz", "decimal", maxlen=10),
        ], {"MHz": "7.074"})

    def extra_fields(self):
        return [Field("_bar1", "", "header"), Field("_bar2", "", "header")]

    def right(self):
        return self.app.st.license

    def softkeys(self):
        return [(K("Class", "ref"), self.cycle), (K("Band", "minus"), lambda: self.step(-1)),
                (K("Band", "plus"), lambda: self.step(1)), (K("Plan", "band"), lambda: self.app.push(BandPlan(self.app))),
                (K("Model", "antenna"), self.antenna)]

    def antenna(self):
        try:
            mhz = C.parse_number(self.values.get("MHz"))
        except ValueError:
            mhz = None
        open_lab(self.app, mhz if mhz and 1.0 <= mhz <= 1300 else None)

    def cycle(self):
        st = self.app.st
        st.license = C.CLASSES[(C.CLASSES.index(st.license) + 1) % len(C.CLASSES)]
        self.build()

    def step(self, d):
        try:
            mhz = C.parse_number(self.values.get("MHz")) or 7.074
        except ValueError:
            mhz = 7.074
        b = C.band_for(mhz)
        i = C.BANDS.index(b) if b else min(range(len(C.BANDS)), key=lambda j: abs(C.BANDS[j].lo - mhz))
        nb = C.BANDS[(i + d) % len(C.BANDS)]
        acts = [f for f, _w in C.ACTIVITY if nb.lo <= f <= nb.hi]
        self.values["MHz"] = C.fmt(acts[0] if acts else (nb.lo + nb.hi) / 2, 6)
        self.build()

    def compute(self, v):
        mhz = num(v, "MHz")
        if not mhz:
            return []
        lic = self.app.st.license
        band, seg, text = C.privilege(mhz, lic)
        out = [("Transmit", text, L.OK if seg else L.BAD)]
        if band:
            out.append(("Band", f"{band.name}  {C.fmt(band.lo, 6)}-{C.fmt(band.hi, 6)}"))
            out.append(("Power limit", C.power_limit(mhz, lic)))
            e = C.edges(mhz, lic)
            if e and e["inside"]:
                lo, hi = e["below"], e["above"]
                near = min(lo, hi)
                out.append(("Segment edge", f"{C.fmt(near, 3)} kHz {'above the low' if lo <= hi else 'below the top'} "
                            "edge", L.WARN if near < 3 else None))
            elif e:
                out.append(("Nearest segment", f"{C.fmt(e['to'], 4)} kHz away: "
                            f"{C.fmt(e['seg'][0], 6)}-{C.fmt(e['seg'][1], 6)}"))
            if band.name == "60 m":
                ch, off = C.nearest_60m(mhz)
                out.append(("60 m channel", f"{C.fmt(ch, 6)} (USB dial {C.fmt(ch - 0.0015, 6)}), "
                            f"{C.fmt(off, 3)} kHz off", L.WARN if abs(off) > 1.5 else L.OK))
            if band.note:
                out.append(("Note", band.note, L.WARN))
            for f, what, khz in C.activity_near(mhz):
                where = "here" if abs(khz) < 0.6 else f"{C.fmt(abs(khz), 3)} kHz {'up' if khz > 0 else 'down'}"
                out.append((f"{what} {C.fmt(f, 6)}", where, L.OK if abs(khz) < 0.6 else L.DIM))
        lam = C.wavelength_m(mhz)
        out.append(("Wavelength", f"{C.fmt(lam, 4)} m  {C.fmt(lam * C.FT_PER_M, 4)} ft"))
        out.append(("Antenna", "8 Model opens Antenna Lab at this frequency", L.DIM))
        return out

    def paint(self, surf, f):
        import pygame
        keys = [fl.key for fl in self.form.fields]
        if "_bar1" not in keys:
            return
        i = keys.index("_bar1") - self.form.top
        if i < 0 or i + 1 >= self.nrows:
            return
        try:
            mhz = C.parse_number(self.values.get("MHz"))
        except ValueError:
            mhz = None
        b = C.band_for(mhz) if mhz else None
        y = T.TITLE_H + 1 + i * T.ROW_H
        surf.fill(T.BG, (0, y, T.W, 2 * T.ROW_H))
        tiny = f["tiny"]
        if not b:
            surf.blit(tiny.render("Not in a US amateur band", True, L.DIM), (8, y + 12))
            return
        x0, x1 = 22, T.W - 10

        def X(m):
            return x0 + (m - b.lo) / (b.hi - b.lo) * (x1 - x0)
        lic = self.app.st.license
        for k, cls in enumerate(C.CLASSES):
            yy = y + 3 + k * 13
            mine = cls == lic
            surf.blit(tiny.render(cls[0], True, L.FG if mine else L.DIM), (7, yy - 4))
            surf.fill(T.SURFACE, (x0, yy, x1 - x0, 8))
            for s in b.seg.get(cls, []):
                c = seg_color(s[2])
                if not mine:
                    c = tuple(v // 2 for v in c)
                surf.fill(c, (X(s[0]), yy, max(1, X(s[1]) - X(s[0])), 8))
        xm = X(mhz)
        pygame.draw.line(surf, (255, 255, 255), (xm, y + 1), (xm, y + 36), 2)
        pygame.draw.polygon(surf, (255, 255, 255), [(xm - 4, y - 1), (xm + 4, y - 1), (xm, y + 4)])


class BandPlan(Menu):
    help = ("Where your license lets you transmit, band by band (FCC Part 97.301). 4 changes the license "
            "class. CW is allowed everywhere on the amateur bands. OK on a band shows its notes.")

    def __init__(self, app):
        self.lic = app.st.license
        super().__init__(app, "Band plan", [])
        self.fill()

    def fill(self):
        items = []
        for b in C.BANDS:
            segs = b.seg.get(self.lic, [])
            if not segs:
                items.append((b.name, (lambda b=b: self.show(b)), "none", L.DIM))
                continue
            for i, s in enumerate(segs):
                lab = b.name if i == 0 else ""
                rng = f"{C.fmt(s[0], 5)}-{C.fmt(s[1], 5)}"
                items.append((f"{lab:6} {rng}".rstrip() if lab else f"       {rng}", (lambda b=b: self.show(b)),
                              s[2].split(",")[0].replace("Channels and segment", "Channels")))
        self.items = items
        self.sel = min(self.sel, len(items) - 1)

    def right(self):
        return self.lic

    def softkeys(self):
        return [(K("Class", "ref"), self.cycle)]

    def cycle(self):
        self.lic = C.CLASSES[(C.CLASSES.index(self.lic) + 1) % len(C.CLASSES)]
        self.app.st.license = self.lic
        self.fill()

    def show(self, b):
        segs = b.seg.get(self.lic, [])
        lines = [f"{C.fmt(s[0], 6)}-{C.fmt(s[1], 6)} MHz: {s[2]}" for s in segs] or [f"No {self.lic} privileges."]
        if b.note:
            lines.append(b.note)
        lines.append("Check the current FCC rules before you transmit.")
        self.app.push(Message(self.app, f"{b.name}  {self.lic}", "\n".join(lines)))


# ---- RF math -----------------------------------------------------------------------------

class Power(Calc):
    tool = "power"
    help = ("Watts to dBm and dBW, a gain or loss applied to them, and a received signal in dBm or microvolts "
            "as S-units (S9 is 50 uV, -73 dBm, on HF and -93 dBm on VHF; 6 dB per S-unit). " + HELP_CALC)

    def __init__(self, app):
        super().__init__(app, "Power and signal", [
            Field("W", "Power W", "text", maxlen=12),
            Field("dB", "Gain or loss dB", "decimal", maxlen=8),
            Field("sig", "Signal dBm or uV", "text", maxlen=10,
                  help="-73 is dBm; 50u or 50uV is microvolts"),
        ], {"W": "100", "dB": "-3", "sig": "-73"})

    def compute(self, v):
        w = num(v, "W", prefixes=True)
        db = num(v, "dB", negative=True)
        raw = (v.get("sig") or "").strip().lower().replace("µ", "u")
        if raw.endswith(("uv", "u")):
            uv = C.parse_number(raw.rstrip("v").rstrip("u"))
            sig = C.uv_to_dbm(uv) if uv else None
        else:
            sig = num(v, "sig", negative=True)
        out = []
        if w:
            out.append(("Power", f"{C.fmt(C.watts_to_dbm(w), 4)} dBm  {C.fmt(C.watts_to_dbm(w) - 30, 4)} dBW"))
            if db is not None:
                after = w * C.db_to_ratio(db)
                out.append((f"After {C.fmt(db, 3)} dB (x{C.fmt(C.db_to_ratio(db), 3)})",
                            f"{C.si(after, 'W')}  {C.fmt(C.watts_to_dbm(after), 4)} dBm", L.OK))
        if sig is not None:
            out.append(("S-meter HF", C.s_units(sig, False), L.OK))
            out.append(("S-meter VHF/UHF", C.s_units(sig, True)))
            out.append(("Signal", f"{C.fmt(sig, 4)} dBm  {C.fmt(C.dbm_to_uv(sig), 3)} uV  "
                        f"{C.si(10 ** (sig / 10) / 1000, 'W', 3)}"))
        return out


class Swr(Calc):
    tool = "swr"
    help = ("Type an SWR reading, or forward and reflected watts from a wattmeter (they win when both are "
            "filled). Shows reflected power, return loss and mismatch loss.")

    def __init__(self, app):
        super().__init__(app, "SWR", [
            Field("swr", "SWR (x : 1)", "decimal", maxlen=8),
            Field("fwd", "or forward W", "decimal", maxlen=8),
            Field("ref", "reflected W", "decimal", maxlen=8),
        ], {"swr": "1.5", "fwd": "", "ref": ""})

    def compute(self, v):
        swr, fwd, ref = num(v, "swr"), num(v, "fwd"), num(v, "ref")
        r = C.swr_figures(swr=swr, forward=fwd, reflected=ref) if (fwd is not None and ref is not None) \
            else C.swr_figures(swr=swr)
        if not r:
            if fwd is not None and ref is not None:
                return [("Reflected must be below forward", "", L.BAD)]
            return [("SWR is 1 or more", "", L.WARN)] if swr is not None else []
        rl = "∞ dB" if r["rl"] == float("inf") else f"{C.fmt(r['rl'], 3)} dB"
        col = L.OK if r["swr"] <= 1.5 else L.WARN if r["swr"] <= 2.5 else L.BAD
        out = [("SWR", f"{C.fmt(r['swr'], 3)} : 1", col),
               ("Reflected power", f"{C.fmt(r['refl_pct'], 3)} %"),
               ("Return loss", rl),
               ("Mismatch loss", f"{C.fmt(r['mismatch'], 3)} dB"),
               ("Reflection coeff.", C.fmt(r["gamma"], 3))]
        if fwd:
            out.append(("Reaches the antenna", C.si(fwd * (1 - r["refl_pct"] / 100), "W", 3)))
        return out


class Ohms(Calc):
    tool = "ohms"
    help = ("Fill in any two of voltage, current, resistance and power; the other two are worked out. "
            "Prefixes work: 4.7k, 250m, 10u. Clear a field (Ctrl+U while editing) to pick another pair.")

    def __init__(self, app):
        super().__init__(app, "Ohm's law", [
            Field("E", "Voltage E (V)", "text", maxlen=12),
            Field("I", "Current I (A)", "text", maxlen=12),
            Field("R", "Resistance R (ohm)", "text", maxlen=12),
            Field("P", "Power P (W)", "text", maxlen=12),
        ], {"E": "13.8", "I": "", "R": "", "P": "100"})

    def compute(self, v):
        known = {k: num(v, k, prefixes=True) for k in "EIRP"}
        n = sum(1 for x in known.values() if x is not None)
        if n != 2:
            return [("Fill in exactly two fields", f"{n} filled now", L.WARN)]
        r = C.solve_ohm(**known)
        if not r:
            return [("Values must be above zero", "", L.BAD)]
        vals, formulas = r
        units = {"E": "V", "I": "A", "R": "ohm", "P": "W"}
        names = {"E": "Voltage", "I": "Current", "R": "Resistance", "P": "Power"}
        return [(f"{names[k]} = {formulas[k]}", C.si(vals[k], units[k]), L.OK) for k in "EIRP" if k in formulas]


class LC(Calc):
    tool = "lc"
    help = ("Resonance: fill in two of frequency, inductance and capacitance and get the third, with the "
            "reactances at that frequency. Prefixes work in L and C: 2.2 (uH), 150 (pF).")

    def __init__(self, app):
        super().__init__(app, "LC and reactance", [
            Field("MHz", "Frequency MHz", "decimal", maxlen=10),
            Field("L", "Inductance uH", "decimal", maxlen=10),
            Field("C", "Capacitance pF", "decimal", maxlen=10),
        ], {"MHz": "7.1", "L": "2.2", "C": ""})

    def compute(self, v):
        f, lu, cp = num(v, "MHz"), num(v, "L"), num(v, "C")
        given = sum(1 for x in (f, lu, cp) if x)
        out = []
        if given == 2:
            r = C.lc_solve(f * 1e6 if f else None, lu * 1e-6 if lu else None, cp * 1e-12 if cp else None)
            fh, lh, cf = r
            if not f:
                out.append(("Resonates at", f"{C.fmt(fh / 1e6, 5)} MHz", L.OK))
            if not lu:
                out.append(("Inductance", f"{C.fmt(lh * 1e6, 4)} uH", L.OK))
            if not cp:
                out.append(("Capacitance", f"{C.fmt(cf * 1e12, 4)} pF", L.OK))
            f, lu, cp = fh / 1e6, lh * 1e6, cf * 1e12
        elif given == 3:
            out.append(("Fill in two of the three", "clear one", L.WARN))
            return out
        if f and (lu or cp):
            xl, xc = C.reactance(f * 1e6, lu * 1e-6 if lu else None, cp * 1e-12 if cp else None)
            if xl:
                out.append((f"XL at {C.fmt(f, 4)} MHz", C.si(xl, "ohm", 4)))
            if xc:
                out.append((f"XC at {C.fmt(f, 4)} MHz", C.si(xc, "ohm", 4)))
        return out


class Toroid(Calc):
    tool = "toroid"
    help = ("Turns on an Amidon iron powder (T) or ferrite (FT) core for an inductance, or the inductance for "
            "a number of turns, with about how much wire to cut. Mix 2 suits 2-30 MHz, mix 6 10-50 MHz, "
            "43 and 61 ferrite for chokes and transformers. Check your core's datasheet.")

    def __init__(self, app):
        super().__init__(app, "Toroid winding", [
            Field("core", "Core", "choice", list(C.CORES)),
            Field("uH", "Inductance uH", "decimal", maxlen=10),
            Field("turns", "or turns", "number", maxlen=4),
        ], {"core": "T-50-2", "uH": "1.5", "turns": ""})

    def changed(self, key):
        if key == "uH":
            self.values["turns"] = ""
        elif key == "turns" and self.values.get("turns"):
            self.values["uH"] = ""

    def compute(self, v):
        core = v.get("core", "T-50-2")
        if core not in C.CORES:
            core = "T-50-2"
        al, unit, od, idd, h = C.CORES[core]
        luh, n = num(v, "uH"), num(v, "turns")
        out = []
        if n:
            n = int(n)
            luh = C.toroid_from_turns(core, n)
            out.append((f"{n} turns give", f"{C.fmt(luh, 4)} uH", L.OK))
            wire = n * (2 * h + (od - idd) + 0.08) + 2
        elif luh:
            r = C.toroid(core, luh)
            out.append(("Turns", f"{r['turns']}  (exactly {C.fmt(r['exact'], 3)})", L.OK))
            out.append(("You get", f"{C.fmt(r['got_uh'], 4)} uH"))
            wire = r["wire_in"]
            luh = r["got_uh"]
        else:
            return []
        out.append(("Wire to cut", f"{C.fmt(wire, 3)} in  {C.fmt(wire * 2.54, 3)} cm (2 in leads)"))
        out.append(("Core AL", f"{C.fmt(al, 4)} {unit}"))
        for f in (3.6, 7.1, 14.2):
            out.append((f"XL at {C.fmt(f, 3)} MHz", C.si(2 * math.pi * f * 1e6 * luh * 1e-6, "ohm", 3), L.DIM))
        return out


class Attenuator(Calc):
    tool = "atten"
    help = "Resistor values for a pi or T attenuator pad, exact and the nearest 5% (E24) value."

    def __init__(self, app):
        super().__init__(app, "Attenuator pad", [
            Field("dB", "Attenuation dB", "decimal", maxlen=6),
            Field("z0", "Impedance", "choice", ["50", "75"]),
        ], {"dB": "6", "z0": "50"})

    def compute(self, v):
        db = num(v, "dB")
        if not db:
            return []
        r = C.attenuator(db, float(v.get("z0", "50")))

        def rr(x):
            return f"{C.fmt(x, 4)} ohm  (5%: {C.fmt(C.e24(x), 3)})"
        return [("--", "Pi pad: two to ground, one in line"),
                ("Shunt (x2)", rr(r["pi_shunt"])), ("Series", rr(r["pi_series"])),
                ("--", "T pad: two in line, one to ground"),
                ("Series (x2)", rr(r["t_series"])), ("Shunt", rr(r["t_shunt"])),
                ("Power in the first resistor", "about half the loss: use 2 W parts for 5 W QRP", L.DIM)]


class RfMath(Menu):
    help = "The RF calculators. OK opens one; what you type is kept for next time."

    def __init__(self, app):
        items = [("Power, dB and S-units", lambda: app.push(Power(app)), "", L.FG, "rf"),
                 ("SWR and return loss", lambda: app.push(Swr(app)), "", L.FG, "chart"),
                 ("Ohm's law", lambda: app.push(Ohms(app)), "", L.FG, "rf"),
                 ("LC resonance, reactance", lambda: app.push(LC(app)), "", L.FG, "sun"),
                 ("Toroid winding", lambda: app.push(Toroid(app)), "", L.FG, "gear"),
                 ("Attenuator pad", lambda: app.push(Attenuator(app)), "", L.FG, "minus")]
        super().__init__(app, "RF math", items)


# ---- Where and when ---------------------------------------------------------------------------

class Where(Calc):
    tool = "where"
    answers_header = False
    help = ("Your location comes from a USB GPS, or your grid in Settings (4 uses the GPS fix as your grid, "
            "5 picks a city). Type a grid or a call sign to get the country and zones, distance and beam "
            "headings, and sunrise, sunset and greyline at both ends, in UTC. Greyline (sun from 6 degrees below "
            "to 3 above the horizon) is when low bands open over long paths.")

    def __init__(self, app):
        super().__init__(app, "Where & when", [
            Field("to", "To grid or call", "text", maxlen=12),
        ], {"to": "JA1ABC"})

    def softkeys(self):
        return [(K("GPS", "gps"), self.use_gps), (K("City", "where"), self.pick_city)]

    def use_gps(self):
        fix = self.app.gps.fix() if self.app.gps else None
        if not fix:
            self.app.push(Message(self.app, "No GPS fix", "Plug in a USB GPS and give it a view of the sky. "
                                  "It can take a minute or two to get a first fix.", L.WARN))
            return
        self.app.st.set("grid", C.to_grid(fix["lat"], fix["lon"]))
        self.build()

    def pick_city(self):
        def choose(name, la, lo):
            self.app.st.set("grid", C.to_grid(la, lo))
            self.app.pop()
            self.build()
        self.app.push(Menu(self.app, "Pick a city", [(n, (lambda n=n, la=la, lo=lo: choose(n, la, lo)))
                                                     for n, la, lo in geo.CITIES]))

    def compute(self, v):
        here = self.app.location()
        now = self.app.utc()
        out = []
        if not here:
            return [("No location yet", "Settings: your grid, or plug in a GPS", L.WARN)]
        lat, lon, src = here
        out.append(("Me", f"{C.to_grid(lat, lon)} ({src})", L.OK))
        word = geo.daylight_word(lat, lon, now)
        ev = geo.sun_events(lat, lon, geo.day_start(now))
        out.append(("Sun here", self.sun_text(ev, word)))
        if ev["rise"] and ev["set"]:
            out.append(("Greyline", f"{geo.hhmm(ev['rise'] - 1800)}-{geo.hhmm(ev['rise'] + 1800)}  "
                        f"{geo.hhmm(ev['set'] - 1800)}-{geo.hhmm(ev['set'] + 1800)}"))
        to = (v.get("to") or "").strip().upper()
        if not to:
            return out
        g = C.norm_grid(to)
        info = None
        if g and not any(ch.isdigit() for ch in to[4:]) and len(to) in (4, 6):
            la2, lo2 = C.grid_center(g)
            label = g
        else:
            info = geo.lookup_call(to)
            if not info:
                out.append(("Unknown call prefix", to, L.BAD))
                return out
            la2, lo2 = info["lat"], info["lon"]
            label = info["country"]
        out.append(("--", f"To {label}"))
        if info:
            out.append(("Zones", f"CQ {info['cq']}  ITU {info['itu']}"))
        km = C.distance_km(lat, lon, la2, lo2)
        b = C.bearing_deg(lat, lon, la2, lo2)
        out.append(("Distance", f"{self.app.dist(km)}  (LP {self.app.dist(40075 - km)})"))
        out.append(("Beam", f"{b:.0f}° {C.compass(b)}  (LP {(b + 180) % 360:.0f}°)", L.OK))
        word2 = geo.daylight_word(la2, lo2, now)
        ev2 = geo.sun_events(la2, lo2, geo.day_start(now))
        out.append(("Sun there", self.sun_text(ev2, word2)))
        if word == "greyline" and word2 == "greyline":
            out.append(("Both ends in greyline now", "try 160, 80 and 40 m", L.OK))
        elif word == "night" and word2 == "night":
            out.append(("Dark path now", "the low bands are favoured", L.DIM))
        elif word == "day" and word2 == "day":
            out.append(("Daylight path now", "the high bands are favoured", L.DIM))
        return out

    @staticmethod
    def sun_text(ev, word):
        if ev["polar"] == "day":
            return f"no sunset today, {word}"
        if ev["polar"] == "night":
            return f"no sunrise today, {word}"
        return f"{geo.hhmm(ev['rise'])}-{geo.hhmm(ev['set'])}, {word}"

    def tick(self):
        if int(time.time()) % 30 == 0 and not self.text_entry:
            self.build()


# ---- Propagation ------------------------------------------------------------------------

class Propagation(Menu):
    help = ("Solar flux, sunspots and the A and K indices with N0NBH's band conditions from hamqsl.com when "
            "online (4 refreshes; the last copy is kept). The MUF line is Ask Elmer's own rough estimate for a "
            "3000 km hop from your location, worked out offline from the time and the solar flux. 5 shows it "
            "through the day. A K index of 5 or more means a geomagnetic storm: HF is poor, aurora likely.")

    def __init__(self, app):
        super().__init__(app, "Propagation", [])
        self.fill()

    def sfi(self) -> float:
        d = online.solar()
        try:
            return float(d["solarflux"])
        except (TypeError, KeyError, ValueError):
            try:
                return float(self.app.st.setting("sfi", "100"))
            except ValueError:
                return 100.0

    def fill(self):
        d = online.solar()
        items = []
        if d:
            k = d.get("kindex", "?")
            try:
                kc = L.BAD if float(k) >= 5 else L.WARN if float(k) >= 4 else L.OK
            except ValueError:
                kc = L.FG
            items.append((f"Solar flux {d.get('solarflux')}", None, f"SSN {d.get('sunspots')}"))
            items.append((f"K {k}   A {d.get('aindex')}", None, d.get("geomagfield", "").title(), kc))
            items.append(("X-ray", None, f"{d.get('xray')}  noise {d.get('signalnoise')}"))
            for name, w in d.get("bands", {}).items():
                day, night = w.get("day", "?"), w.get("night", "?")
                col = L.OK if "Good" in (day, night) else L.WARN if "Fair" in (day, night) else L.DIM
                items.append((name.replace("m-", "-") , None, f"{day} / {night}", col))
            items.append(("Updated", None, f"{d.get('updated', '').replace('GMT', 'UTC').strip()}", L.DIM))
        else:
            items.append(("No solar data yet: press 4 when online", None, "", L.WARN))
        here = self.app.location()
        if here:
            m = prop.muf(here[0], here[1], self.app.utc(), self.sfi())
            items.append((f"MUF here ~{m:.0f} MHz", (lambda: self.app.push(MufChart(self.app, self.sfi()))),
                          "estimate", L.OK))
            opened = [n.replace(" m", "") for n, _f, w in prop.band_outlook(m) if w in ("open", "short hops")]
            items.append(("Likely open", None, " ".join(opened) or "none"))
        else:
            items.append(("Set your grid for a MUF estimate", None, "", L.DIM))
        self.items = items
        self.sel = min(self.sel, len(items) - 1)

    def right(self):
        a = online.age_of("solar.json")
        return ago(a) if a is not None else ""

    def softkeys(self):
        return [(K("Update", "refresh"), self.refresh), (K("MUF", "chart"), lambda: self.app.push(
            MufChart(self.app, self.sfi())))]

    def refresh(self):
        self.app.task("Propagation", "Asking hamqsl.com", lambda: online.solar(refresh=True), lambda _d: self.fill())


class MufChart(Screen):
    title = "MUF today"
    help = ("Ask Elmer's rough MUF estimate for a 3000 km hop from your location over the next 24 hours, from "
            "the solar flux. A band is likely open for long hops while the curve is above its line.")

    def __init__(self, app, sfi):
        super().__init__(app)
        self.sfi = sfi

    def right(self):
        return f"SFI {self.sfi:.0f}"

    def paint(self, surf, f):
        import pygame
        here = self.app.location()
        tiny = f["tiny"]
        top, bot = T.TITLE_H + 6, T.H - T.HINT_H - 16
        if not here:
            surf.blit(f["small"].render("Set your grid in Settings", True, L.DIM), (10, 60))
            return
        now = self.app.utc()
        start = now - now % 3600
        pts = prop.day_curve(here[0], here[1], start, self.sfi, 24, 20)
        fmax = 35.0
        x0, x1 = 36, T.W - 8

        def X(t):
            return x0 + (t - start) / 86400 * (x1 - x0)

        def Y(mhz):
            return bot - min(mhz, fmax) / fmax * (bot - top)
        for name, mhz in (("40m", 7.15), ("20m", 14.2), ("15m", 21.2), ("10m", 28.5)):
            y = Y(mhz)
            pygame.draw.line(surf, T.RULE, (x0, y), (x1, y))
            img = tiny.render(name, True, L.DIM)
            surf.blit(img, (x0 - 4 - img.get_width(), y - 7))
        poly = [(X(t), Y(m)) for t, m in pts]
        pygame.draw.lines(surf, T.AMBER, False, poly, 2)
        for h in range(0, 25, 6):
            t = start + h * 3600
            x = X(t)
            pygame.draw.line(surf, T.RULE, (x, bot), (x, bot + 3))
            img = tiny.render(time.strftime("%H", time.gmtime(t)), True, L.DIM)
            surf.blit(img, (x - img.get_width() // 2, bot + 3))
        xn = X(now)
        pygame.draw.line(surf, (255, 255, 255), (xn, top), (xn, bot))
        m = prop.muf(here[0], here[1], now, self.sfi)
        surf.blit(tiny.render(f"now ~{m:.0f} MHz", True, L.OK), (min(xn + 4, T.W - 90), top))
        surf.blit(tiny.render("UTC", True, L.DIM), (2, bot + 3))

    def key(self, k):
        if k.name in BACK or k.name in SELECT:
            self.app.pop(self)


# ---- Satellites -------------------------------------------------------------------------------

class Satellites(Menu):
    help = ("The next passes of the easy FM satellites (ISS, SO-50, AO-91, PO-101) and the linear ones (RS-44, "
            "AO-7, FO-29) over your location, in UTC. OK on a pass shows where to point and the Doppler-corrected "
            "frequencies, live. 4 downloads fresh orbits (do it weekly); 5 changes the lowest pass shown.")

    MIN_ELS = (10, 30, 0)

    def __init__(self, app):
        super().__init__(app, "Satellites", [])
        self.min_el = int(app.st.setting("sat_min_el", 10))
        self.computed_at = 0.0
        self.passes = []
        self.problem = ""
        self.fill()

    def right(self):
        a = online.tle_age_days()
        return f"orbits {a:.0f} d old" if a is not None else "no orbits"

    def softkeys(self):
        return [(K("Update", "refresh"), self.update), (K(f"{self.min_el}° up", "sat"), self.cycle_el)]

    def cycle_el(self):
        i = self.MIN_ELS.index(self.min_el) if self.min_el in self.MIN_ELS else 0
        self.min_el = self.MIN_ELS[(i + 1) % len(self.MIN_ELS)]
        self.app.st.set("sat_min_el", self.min_el)
        self.fill()

    def update(self):
        self.app.task("Satellites", "Downloading orbits", online.update_tles, lambda _n: self.fill())

    def fill(self):
        here = self.app.location()
        self.problem = ""
        if not sats.have_sgp4():
            self.problem = "Needs python3-sgp4 (sudo apt install python3-sgp4)"
        elif not here:
            self.problem = "Set your grid in Settings, or plug in a GPS"
        else:
            tl = online.tles()
            if not tl:
                self.problem = "No orbits yet: press 4 when online"
            else:
                now = self.app.utc()
                self.passes = sats.next_passes(here[0], here[1], tl, now - 900, 24, self.min_el)
                self.passes = [(b, p) for b, p in self.passes if p["los"] > now]
                self.computed_at = now
        self.refresh_items()

    def refresh_items(self):
        if self.problem:
            self.items = [(self.problem, None, "", L.WARN)]
            return
        now = self.app.utc()
        items = []
        for b, p in self.passes[:40]:
            if p["aos"] <= now:
                when, col = "now", L.OK
            else:
                mins = (p["aos"] - now) / 60
                when = f"in {mins:.0f} min" if mins < 90 else time.strftime("%H:%M", time.gmtime(p["aos"]))
                col = L.FG
            label = f"{b.name}  {time.strftime('%H:%M', time.gmtime(p['aos']))}  {p['max_el']:.0f}°"
            items.append((label, (lambda b=b, p=p: self.app.push(PassView(self.app, b, p))), when, col))
        self.items = items or [(f"No passes above {self.min_el}° in 24 h", None, "", L.DIM)]
        self.sel = min(self.sel, len(self.items) - 1)

    def tick(self):
        now = time.time()
        if now - getattr(self, "_last", 0) > 15:
            self._last = now
            if self.app.utc() - self.computed_at > 1800 and not self.problem:
                self.fill()
            else:
                self.refresh_items()
            self.app.wake()


class PassView(Screen):
    hint = "ESC back"

    def __init__(self, app, bird, p):
        super().__init__(app)
        self.b, self.p = bird, p
        self.title = bird.name
        here = app.location()
        self.tr = sats.Tracker(bird, online.tles()[bird.norad], here[0], here[1])
        self.trackpts = self.tr.track(p["aos"], p["los"], 40)
        self.hint = f"{bird.kind} {bird.up or '-'} up / {bird.down or '-'} down"
        self.help = (f"{bird.name}: {bird.kind}. {bird.note} The sky plot has north up, the horizon on the outer "
                     "ring and overhead in the middle. Uplink is what to transmit on so the satellite hears "
                     "its own frequency; downlink is where to listen. Both change with Doppler during the pass.")

    def right(self):
        return f"max {self.p['max_el']:.0f}°"

    def tick(self):
        if time.time() - getattr(self, "_last", 0) >= 1:
            self._last = time.time()
            self.app.wake()

    def paint(self, surf, f):
        import pygame
        tiny, small = f["tiny"], f["small"]
        top = T.TITLE_H + 2
        surf.fill(T.BG, (0, top, T.W, T.H - top - T.HINT_H))
        cx, cy, R = 58, top + 56, 52
        for k in (1.0, 2 / 3, 1 / 3):
            pygame.draw.circle(surf, T.RULE, (cx, cy), int(R * k), 1)
        pygame.draw.line(surf, T.RULE, (cx - R, cy), (cx + R, cy))
        pygame.draw.line(surf, T.RULE, (cx, cy - R), (cx, cy + R))
        surf.blit(tiny.render("N", True, L.DIM), (cx - 4, cy - R - 2))

        def P(az, el):
            rr = R * (90 - max(0.0, el)) / 90
            return cx + rr * math.sin(math.radians(az)), cy - rr * math.cos(math.radians(az))
        pts = [P(a, e) for a, e, _r in [t for t in self.trackpts if t]]
        if len(pts) > 1:
            pygame.draw.lines(surf, T.AMBER, False, pts, 2)
            pygame.draw.circle(surf, L.OK, [int(v) for v in pts[0]], 3)
        now = self.app.utc()
        lk = self.tr.look(now)
        x = 122
        y = top + 2

        def line(text, col=L.FG, font=small):
            nonlocal y
            surf.blit(font.render(text, True, col), (x, y))
            y += font.get_height() + 1
        p = self.p
        line(f"Up   {time.strftime('%H:%M:%S', time.gmtime(p['aos']))}  {p['aos_az']:.0f}° {C.compass(p['aos_az'])}",
             L.OK)
        line(f"Top  {time.strftime('%H:%M', time.gmtime(p['tca']))}  {p['max_el']:.0f}° high")
        line(f"Down {time.strftime('%H:%M', time.gmtime(p['los']))}  {p['los_az']:.0f}° {C.compass(p['los_az'])}")
        if lk and p["aos"] - 60 <= now <= p["los"] + 60:
            az, el, rng = lk
            if el > -2:
                pygame.draw.circle(surf, (255, 255, 255), [int(v) for v in P(az, el)], 4)
            line(f"Now  az {az:.0f}°  el {el:.0f}°", T.AMBER)
            up, down = self.tr.doppler(now)
        else:
            mins = (p["aos"] - now) / 60
            line(f"Starts in {mins:.0f} min" if mins > 0 else "Pass is over", L.DIM)
            up, down = self.tr.doppler(p["aos"] + 30)
        b = self.b
        if b.up:
            line(f"TX {up:.3f}" + (f" t{b.tone}" if b.tone else ""), L.FG)
        if b.down:
            line(f"RX {down:.3f}", L.FG)

    def key(self, k):
        if k.name in BACK:
            self.app.pop(self)


# ---- POTA and SOTA ------------------------------------------------------------------------------

def bearing_text(app, lat, lon, la2, lo2):
    km = C.distance_km(lat, lon, la2, lo2)
    b = C.bearing_deg(lat, lon, la2, lo2)
    return km, f"{app.dist(km)} {C.compass(b)}"


class Spots(Menu):
    help = ("Who is on the air from a park right now (api.pota.app), newest first or nearest first (5). "
            "OK shows the details. 4 refreshes.")

    def __init__(self, app):
        super().__init__(app, "POTA spots", [])
        self.by_distance = False
        self.spots = online.pota_spots(refresh=False)
        self.fill()

    def right(self):
        return f"{len(self.spots)} on air" if self.spots else ""

    def softkeys(self):
        return [(K("Update", "refresh"), self.refresh), (K("Near" if not self.by_distance else "New",
                                                           "where" if not self.by_distance else "clock"), self.sort)]

    def refresh(self):
        def done(spots):
            self.spots = spots
            self.fill()
        self.app.task("POTA", "Getting spots", lambda: online.pota_spots(refresh=True), done)

    def sort(self):
        self.by_distance = not self.by_distance
        self.fill()

    def fill(self):
        here = self.app.location()
        rows = []
        for s in self.spots:
            km = None
            if here and s.get("latitude") is not None:
                km = C.distance_km(here[0], here[1], s["latitude"], s["longitude"])
            rows.append((km, s))
        if self.by_distance:
            rows.sort(key=lambda x: x[0] if x[0] is not None else 1e9)
        else:
            rows.sort(key=lambda x: x[1].get("spotTime") or "", reverse=True)
        items = []
        for km, s in rows:
            try:
                f = float(s.get("frequency") or 0) / 1000
            except ValueError:
                f = 0
            label = f"{s.get('activator')} {f:.3f} {s.get('mode') or ''}"
            items.append((label, (lambda s=s, km=km: self.show(s, km)), s.get("reference") or ""))
        self.items = items or [("No spots yet: press 4 when online", None, "", L.WARN)]
        self.sel = min(self.sel, len(self.items) - 1)

    def show(self, s, km):
        here = self.app.location()
        lines = [f"{s.get('reference')} {s.get('name') or ''} ({s.get('locationDesc') or ''})",
                 f"{s.get('frequency')} kHz {s.get('mode') or ''}, spotted {(s.get('spotTime') or '')[11:16]} UTC"]
        if here and s.get("latitude") is not None:
            b = C.bearing_deg(here[0], here[1], s["latitude"], s["longitude"])
            lines.append(f"{self.app.dist(km)} away, beam {b:.0f}° {C.compass(b)}, grid {s.get('grid6') or ''}")
        if s.get("comments"):
            lines.append(s["comments"])
        self.app.push(Message(self.app, s.get("activator") or "Spot", "\n".join(lines)))


class Nearby(Menu):
    """Parks (POTA) or summits (SOTA) near you, from a cached download."""

    def __init__(self, app, kind):
        self.kind = kind
        super().__init__(app, "Parks near me" if kind == "parks" else "Summits near me", [])
        self.help = (f"{'POTA parks' if kind == 'parks' else 'SOTA summits'} within {online.RADIUS_KM} km of you, "
                     "nearest first. 4 downloads the list for where you are now (needs internet once; it is kept "
                     "for offline use). 5 starts the activation counter for the one you've picked.")
        self.fill()

    def softkeys(self):
        return [(K("Update", "refresh"), self.download), (K("Activate", "plus"), self.activate)]

    def download(self):
        here = self.app.location()
        if not here:
            self.app.push(Message(self.app, "No location", "Set your grid in Settings, or plug in a GPS.", L.WARN))
            return
        fn = online.download_parks if self.kind == "parks" else online.download_summits
        self.app.task(self.title, "Downloading the list", lambda: fn(here[0], here[1]), lambda _n: self.fill())

    def fill(self):
        here = self.app.location()
        self.near = []
        if not here:
            self.items = [("Set your grid in Settings", None, "", L.WARN)]
            return
        near, meta = online.nearby(self.kind, here[0], here[1])
        if meta is None:
            self.items = [("Nothing downloaded yet: press 4", None, "", L.WARN)]
            return
        moved = C.distance_km(here[0], here[1], meta["lat"], meta["lon"])
        items = []
        if moved > 100:
            items.append((f"You've moved {self.app.dist(moved)}: press 4", None, "", L.WARN))
        for km, it in near[:60]:
            b = C.bearing_deg(here[0], here[1], it[3], it[4])
            right = f"{self.app.dist(km)} {C.compass(b)}"
            items.append((it[1], (lambda it=it, km=km, b=b: self.show(it, km, b)), right))
            self.near.append(it)
        self.items = items or [("None within range", None, "", L.DIM)]
        self.sel = min(self.sel, len(self.items) - 1)

    def selected(self):
        it = self.items[self.sel] if self.items else None
        if not it or not it[1]:
            return None
        return next((x for x in self.near if x[1] == it[0]), None)

    def show(self, it, km, b):
        if self.kind == "parks":
            text = f"{it[1]}\n{it[2]}\n{self.app.dist(km)} away, {b:.0f}° {C.compass(b)}, grid {C.to_grid(it[3], it[4])}"
        else:
            text = (f"{it[1]}\n{it[2]} ft, {it[5]} points, activated {it[6]} times\n"
                    f"{self.app.dist(km)} away, {b:.0f}° {C.compass(b)}, grid {C.to_grid(it[3], it[4])}")
        self.app.push(Message(self.app, it[0], text))

    def activate(self):
        it = self.selected()
        if it:
            start_activation(self.app, it[0], it[1])


def start_activation(app, ref, name=""):
    a = app.st.d.get("activation", {})
    if a.get("ref") != ref or time.gmtime(a.get("started", 0))[:3] != time.gmtime(app.utc())[:3]:
        app.st.d["activation"] = {"ref": ref, "name": name, "started": app.utc(), "times": []}
        app.st.save()
    app.push(Counter(app))


class Counter(Screen):
    title = "Activation"
    help = ("Count your contacts toward a valid activation: 10 for POTA, 4 for SOTA, in one UTC day. Space, OK "
            "or 4 adds one; Backspace or 5 takes one away; 6 starts a new activation. This is a counter, not a "
            "log: keep your log as usual.")
    hint = ""

    @property
    def a(self):
        return self.app.st.d.setdefault("activation", {"ref": "", "name": "", "started": self.app.utc(), "times": []})

    def softkeys(self):
        return [(K("+1", "plus"), self.add), (K("-1", "minus"), self.undo), (K("New", "refresh"), self.new),
                (K("Ref", "park"), self.edit_ref)]

    def add(self):
        self.a["times"].append(self.app.utc())
        self.app.st.save()

    def undo(self):
        if self.a["times"]:
            self.a["times"].pop()
            self.app.st.save()

    def new(self):
        self.app.st.d["activation"] = {"ref": self.a.get("ref", ""), "name": self.a.get("name", ""),
                                       "started": self.app.utc(), "times": []}
        self.app.st.save()

    def edit_ref(self):
        self.app.push(RefEdit(self.app, self))

    def goal(self):
        ref = self.a.get("ref", "")
        return 4 if "/" in ref else 10

    def right(self):
        return self.a.get("ref", "")

    def key(self, k):
        if k.name in BACK:
            self.app.pop(self)
        elif k.name in SELECT or k.char == " " or k.char == "+":
            self.add()
        elif k.name == "backspace" or k.char == "-":
            self.undo()

    def tick(self):
        if time.time() - getattr(self, "_last", 0) >= 1:
            self._last = time.time()
            self.app.wake()

    def paint(self, surf, f):
        import pygame
        a = self.a
        n = len(a["times"])
        goal = self.goal()
        top = T.TITLE_H + 2
        if not hasattr(self, "big"):
            path = next((p for p in T.TITLE_FONT_PATHS if os.path.exists(p)), None)
            self.big = pygame.font.Font(path, 64)
        col = L.OK if n >= goal else T.AMBER
        img = self.big.render(str(n), True, col)
        surf.blit(img, (14, top - 4))
        small, tiny = f["small"], f["tiny"]
        x = 24 + max(img.get_width(), 40)
        surf.blit(small.render(f"of {goal}" + ("  valid!" if n >= goal else ""), True, col), (x, top + 6))
        name = a.get("name") or ("SOTA summit" if goal == 4 else "POTA park")
        surf.blit(tiny.render(name[:30], True, L.DIM), (x, top + 26))
        # progress bar
        bx, by, bw = 12, top + 66, T.W - 24
        surf.fill(T.SURFACE, (bx, by, bw, 8))
        surf.fill(col, (bx, by, int(bw * min(1.0, n / goal)), 8))
        now = self.app.utc()
        last = a["times"][-1] if a["times"] else None
        end = now - now % 86400 + 86400
        left = end - now
        info = f"last QSO {ago(now - last)}" if last else "no QSOs yet"
        if len(a["times"]) >= 2:
            span = (a["times"][-1] - a["times"][0]) / 3600
            if span > 0.05:
                info += f", {len(a['times']) / span:.0f}/h"
        surf.blit(small.render(info, True, L.FG), (12, by + 12))
        surf.blit(small.render(f"UTC day ends in {int(left // 3600)} h {int(left % 3600 // 60):02d} m", True,
                               L.WARN if left < 3600 else L.DIM), (12, by + 30))


class RefEdit(Calc):
    tool = "_ref"

    def __init__(self, app, counter):
        self.counter = counter
        a = counter.a
        super().__init__(app, "Park or summit", [
            Field("ref", "Reference", "text", maxlen=14),
            Field("name", "Name", "text", maxlen=40),
        ], {"ref": a.get("ref", ""), "name": a.get("name", "")})
        self.values = {"ref": a.get("ref", ""), "name": a.get("name", "")}
        self.build()

    def save(self):
        a = self.counter.a
        a["ref"] = self.values.get("ref", "").upper().strip()
        a["name"] = self.values.get("name", "").strip()
        self.app.st.save()


class PotaSota(Menu):
    help = ("Parks on the Air and Summits on the Air: who's on now, what's near you, and a counter for your own "
            "activation.")

    def __init__(self, app):
        items = [("Spots now (POTA)", lambda: app.push(Spots(app)), "", L.FG, "refresh"),
                 ("Parks near me", lambda: app.push(Nearby(app, "parks")), "", L.FG, "park"),
                 ("Summits near me", lambda: app.push(Nearby(app, "summits")), "", L.FG, "mountain"),
                 ("Activation counter", lambda: app.push(Counter(app)),
                  lambda: f"{len(app.st.d.get('activation', {}).get('times', []))} QSOs", L.FG, "plus")]
        super().__init__(app, "POTA / SOTA", items)


# ---- Station clock ---------------------------------------------------------------------------------

ID_SECONDS = 600


class Clock(Screen):
    title = "Station clock"
    help = ("UTC, the time hams log in, and your local time; from the GPS when one is plugged in. The ID "
            "timer counts down the 10 minutes between station IDs (FCC 97.119): 4 (or OK) when you've given "
            "your call, 5 turns the timer on or off. It beeps and the screen turns amber when it's time.")
    hint = ""

    def __init__(self, app):
        super().__init__(app)
        self.big = None
        self.beeped = False

    @property
    def id_on(self):
        return bool(self.app.st.setting("id_on", False))

    def softkeys(self):
        return [(K("ID'd", "bell"), self.ided), (K("Timer" if not self.id_on else "Off", "clock"), self.toggle)]

    def ided(self):
        self.app.st.set("id_last", time.time())
        self.app.st.set("id_on", True)
        self.beeped = False

    def toggle(self):
        on = not self.id_on
        self.app.st.set("id_on", on)
        if on:
            self.app.st.set("id_last", time.time())
        self.beeped = False

    def due(self) -> float:
        return float(self.app.st.setting("id_last", time.time())) + ID_SECONDS - time.time()

    def tick(self):
        self.app.wake()
        if self.id_on and self.due() <= 0 and not self.beeped:
            self.beeped = True
            beep()

    def key(self, k):
        if k.name in BACK:
            self.app.pop(self)
        elif k.name in SELECT:
            self.ided()

    def rows(self):
        return [], None

    def paint(self, surf, f):
        import pygame
        now = self.app.utc()
        u = time.gmtime(now)
        lt = time.localtime(now)
        if self.big is None:
            path = next((p for p in T.TITLE_FONT_PATHS if os.path.exists(p)), None)
            self.big = pygame.font.Font(path, 54)
        top = T.TITLE_H + 1
        overdue = self.id_on and self.due() <= 0
        if overdue and int(time.time() * 2) % 2 == 0:
            surf.fill((0x5A, 0x3C, 0x10), (0, top, T.W, T.H - top - T.KEYBAR_H))
        big = self.big.render(time.strftime("%H:%M:%S", u), True, T.FG)
        surf.blit(big, ((T.W - big.get_width()) // 2, top - 4))
        y = top + big.get_height() - 8
        src = "GPS" if (self.app.gps and self.app.gps.clock_offset() is not None) else "UTC"
        line1 = time.strftime("%a %d %b %Y", u) + f"  {src}   local " + time.strftime("%H:%M", lt)
        img = f["small"].render(line1, True, T.AMBER if src == "GPS" else L.DIM)
        surf.blit(img, ((T.W - img.get_width()) // 2, y))
        y += 18
        if self.id_on:
            d = self.due()
            if d > 0:
                txt, col = f"ID in {int(d // 60)}:{int(d % 60):02d}", L.OK if d > 60 else L.WARN
            else:
                txt, col = "Time to ID: give your call, then press 4", L.BAD
            bw = T.W - 24
            surf.fill(T.SURFACE, (12, y + 18, bw, 5))
            surf.fill(col, (12, y + 18, int(bw * max(0.0, d) / ID_SECONDS), 5))
        else:
            txt, col = "ID timer off (5 turns it on)", L.DIM
        call = self.app.st.setting("call", "")
        if call and self.id_on:
            txt = f"{txt}   {call}" if self.due() > 0 else txt
        img = f["small"].render(txt, True, col)
        surf.blit(img, ((T.W - img.get_width()) // 2, y))


_mixer_ok = None


def beep():
    """A short two-tone beep through the speaker (best effort)."""
    global _mixer_ok
    try:
        import numpy as np
        import pygame
        if _mixer_ok is None:
            pygame.mixer.pre_init(48000, -16, 1, 512)
            pygame.mixer.init()
            _mixer_ok = True
        sr = 48000
        t = np.arange(int(sr * 0.18)) / sr
        env = np.minimum(1, np.minimum(t, t[::-1]) * 200)
        tone = np.concatenate([np.sin(2 * np.pi * 880 * t) * env, np.zeros(int(sr * 0.06)),
                               np.sin(2 * np.pi * 660 * t) * env])
        snd = pygame.sndarray.make_sound((tone * 12000).astype(np.int16))
        snd.play()
    except Exception:   # noqa: BLE001 - no audio is fine
        _mixer_ok = False


# ---- Reference ----------------------------------------------------------------------------------

def reference_entries():
    out = [(q, f"{m}  Asked: {q}? {a}", "Q signal") for q, m, a in C.Q_SIGNALS]
    out += [(p, t, "Prosign") for p, t in C.PROSIGNS]
    out += [(a, t, "CW") for a, t in C.CW_ABBREV]
    out += [(r, t, "RST") for r, t in C.RST]
    out += [(k, v, "Phonetic") for k, v in C.PHONETIC.items() if k.isalpha()]
    out += [(f"Cut {c}", f"sent for {d}", "Cut number") for c, d in C.CUT_NUMBERS]
    return out


class Search(Calc):
    tool = "search"
    help = "Type part of a Q signal, prosign, abbreviation, RST figure or word in its meaning: QRZ, 73, fade..."

    def __init__(self, app):
        super().__init__(app, "Search", [Field("q", "Find", "text", maxlen=16)], {"q": ""})

    def compute(self, v):
        q = (v.get("q") or "").strip().lower()
        if not q:
            return [("Type a word or code above", "", L.DIM)]
        hits = [(k, t, c) for k, t, c in reference_entries() if q in k.lower() or q in t.lower()]
        hits.sort(key=lambda h: (not h[0].lower().startswith(q), h[0]))
        return [(f"{k}  {t}", c, L.FG) for k, t, c in hits[:40]] or [("Nothing found", "", L.DIM)]


class Phonetics(Calc):
    tool = "phonetics"
    help = "Spell a call sign (or any text) in the ITU phonetic alphabet."

    def __init__(self, app):
        call = app.st.setting("call", "") or "N0TNT"
        super().__init__(app, "Phonetics", [Field("text", "Call sign", "text", maxlen=16)], {"text": call})

    def compute(self, v):
        return [(c, w or "(no phonetic)", L.OK if w else L.DIM) for c, w in C.spell(v.get("text", ""))]


def list_menu(app, title, entries, help_=""):
    m = Menu(app, title, [(f"{k}  {t}", (lambda k=k, t=t: app.push(Message(app, k, t)))) for k, t in entries])
    m.help = help_
    return m


class Reference(Menu):
    help = "Q signals, prosigns, CW abbreviations, RST, cut numbers and phonetics, with a search (first line)."

    def __init__(self, app):
        q = [(q, f"{m}\n\n{q}? {a}") for q, m, a in C.Q_SIGNALS]
        items = [("Search", lambda: app.push(Search(app)), "", L.FG, "search"),
                 ("Q signals", lambda: app.push(list_menu(app, "Q signals", q,
                                                          "Sent with a question mark they ask; without, they state.")),
                  str(len(q)), L.FG, "ref"),
                 ("Prosigns", lambda: app.push(list_menu(app, "Prosigns", C.PROSIGNS,
                                                         "Prosigns are sent as one character, run together.")),
                  "", L.FG, "ref"),
                 ("CW abbreviations", lambda: app.push(list_menu(app, "CW abbreviations", C.CW_ABBREV)), "",
                  L.FG, "ref"),
                 ("RST reports", lambda: app.push(list_menu(app, "RST", C.RST)), "", L.FG, "ref"),
                 ("Cut numbers", lambda: app.push(list_menu(app, "Cut numbers", [(c, f"sent for {d}")
                                                                                 for c, d in C.CUT_NUMBERS])),
                  "", L.FG, "ref"),
                 ("Phonetics", lambda: app.push(Phonetics(app)), "", L.FG, "ref"),
                 ("60 m channels", lambda: app.push(list_menu(app, "60 m channels", [
                     (C.fmt(c, 6), f"Channel centre {C.fmt(c, 6)} MHz; USB dial {C.fmt(c - 0.0015, 6)} MHz. "
                      "100 W ERP, 2.8 kHz wide. The 5.3515-5.3665 MHz segment allows 9.15 W ERP.")
                     for c in C.CH60])), "", L.FG, "band")]
        super().__init__(app, "Reference", items)


# ---- Settings ----------------------------------------------------------------------------------------

class Settings(Calc):
    tool = "_settings"
    help = ("Your license class, call sign and grid (used when no GPS is plugged in), distance units, and the "
            "solar flux to use for the MUF estimate before the first download. A USB GPS (u-blox, BU-353 and "
            "the like) is found by itself and shared with the other Ask Elmer and Nomad apps. Cap LoRa GNSS uses the "
            "GPS in an M5Stack Cap LoRa-1262 and switches on its 5 V power. A cold start can take a few minutes "
            "outdoors.")

    def __init__(self, app):
        st = app.st
        super().__init__(app, "Settings", [
            Field("lic", "License", "choice", C.CLASSES),
            Field("call", "My call", "text", maxlen=12),
            Field("grid", "My grid", "text", maxlen=6),
            Field("units", "Distances in", "choice", ["mi", "km"]),
            Field("sfi", "Solar flux (offline)", "number", maxlen=3),
            Field("cap", "Cap LoRa GNSS", "choice", ["Off", "On"]),
        ], {})
        self.values = {"lic": st.license, "call": st.setting("call", ""), "grid": st.setting("grid", ""),
                       "units": st.setting("units", "mi"), "sfi": str(st.setting("sfi", "100")),
                       "cap": "On" if nomadgps.config().get("cap") else "Off"}
        self.build()

    def compute(self, v):
        gps = self.app.gps
        out = [("GPS", gps.status() if gps else "off", L.OK if gps and gps.fix() else L.DIM)]
        if getattr(self, "cap_note", ""):
            out.append(("Cap", self.cap_note))
        here = self.app.location()
        if here:
            out.append(("Location in use", f"{C.to_grid(here[0], here[1])} ({here[2]})"))
        g = (v.get("grid") or "").strip()
        if g and not C.norm_grid(g):
            out.append(("My grid looks wrong (like EN61 or EN61ex)", "", L.BAD))
        return out

    def changed(self, key):
        st = self.app.st
        v = self.values
        if key == "lic":
            st.license = v["lic"]
        elif key == "grid":
            g = C.norm_grid(v.get("grid", ""))
            st.set("grid", g or "")
        elif key in ("call",):
            st.set("call", v.get("call", "").upper().strip())
        elif key in ("units", "sfi"):
            st.set(key, v.get(key))
        elif key == "cap":
            self.cap_note = nomadgps.set_cap(v.get("cap") == "On")

    def save(self):
        pass

    def tick(self):
        if time.time() - getattr(self, "_last", 0) > 2 and not self.text_entry:
            self._last = time.time()
            self.build()


# ---- Home ------------------------------------------------------------------------------------------

class Home(Menu):
    help = HELP_MAIN

    def __init__(self, app):
        def grid():
            h = app.location()
            return C.to_grid(h[0], h[1])[:4] if h else ""

        def sfi():
            d = online.solar()
            return f"SFI {d['solarflux']}" if d and d.get("solarflux") else ""
        items = [
            ("Antenna Lab", lambda: open_lab(app), "NEC2", L.OK, "antenna"),
            ("Band check", lambda: app.push(BandCheck(app)), lambda: app.st.license, L.FG, "band"),
            ("RF math", lambda: app.push(RfMath(app)), "", L.FG, "rf"),
            ("Where & when", lambda: app.push(Where(app)), grid, L.FG, "where"),
            ("Propagation", lambda: app.push(Propagation(app)), sfi, L.FG, "sun"),
            ("Satellites", lambda: app.push(Satellites(app)), "", L.FG, "sat"),
            ("POTA / SOTA", lambda: app.push(PotaSota(app)), "", L.FG, "park"),
            ("Station clock", lambda: app.push(Clock(app)), lambda: time.strftime("%H:%M", time.gmtime(app.utc())),
             L.FG, "clock"),
            ("Reference", lambda: app.push(Reference(app)), "", L.FG, "ref"),
            ("Settings", lambda: app.push(Settings(app)), lambda: (app.gps.status() if app.gps and app.gps.fix()
                                                                   else app.st.setting("call", "")), L.FG, "gear"),
            ("About", lambda: app.open_about(), "", L.FG, "about"),
            ("Credits & data", lambda: app.push(Message(app, "Credits & data", HELP_MAIN + " From Ask Elmer, askelmer.com. "
                                               "Antennas are modelled with NEC2 (nec2c). Band privileges follow FCC Part 97; check the current rules "
                                               "before you transmit. Solar data from N0NBH (hamqsl.com), spots "
                                               "from POTA, summits from SOTA, orbits from AMSAT.")), "", L.FG,
             "about"),
        ]
        super().__init__(app, APP_TITLE, items, "↑↓ move  OK open  ESC quit")


def open_lab(app, mhz=None):
    from .lab.screens import open_lab as _open   # loaded on first use: NEC2 screens and templates
    _open(app, mhz)


def main_ui() -> int:
    migrate()
    panel = L.Panel()
    kb = Keyboard()
    app = App(panel, kb if kb.ok else None, nomadgps.shared())
    try:
        app.run()
    finally:
        if kb:
            kb.close()
        if app.gps:
            app.gps.close()
    return 0
