"""Ask Elmer Shack Tools: the app. Screens on the LCD, input from the keyboard."""
from __future__ import annotations

import json
import os
import time

from . import calc as C
from . import lcd as L
from . import nomadui as T
from .keys import Keyboard
from .ui import BACK, DOWN, SELECT, UP, EditList, Field, Menu, Message, Screen, nav_key

APP_TITLE = "Ask Elmer"
PKG = "askelmer-shack-tools"
HELP_MAIN = ("Ask Elmer Shack Tools: the everyday ham radio calculators from askelmer.com. Frequency and "
             "wavelength with your license privileges, the band plan, Ohm's law, decibels, SWR, coax loss, "
             "grid squares, a UTC clock, phonetics and Q signals. Works offline.")
HELP_CALC = ("Up/Down pick a field, OK or Right edits it (red), type, OK saves. The answers below update "
             "as you go; OK on an answer shows it in full. Values are kept for next time.")


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, PKG)


class State:
    """Remembers what you typed in each tool, and your license class."""

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

    @property
    def license(self):
        return self.d.get("license", "Technician")

    @license.setter
    def license(self, v):
        self.d["license"] = v
        self.save()


class App:
    def __init__(self, panel: L.Panel, kb: Keyboard | None):
        self.panel, self.kb = panel, kb
        self.st = State()
        self.stack: list[Screen] = []
        self.helpview = None
        self.dirty = True
        self.quit = False

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

    def wake(self):
        self.dirty = True

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


# ---- a calculator screen: input fields on top, answers below ------------------------------

class Calc(Screen):
    """inputs: [Field]; defaults: {key: text}; compute(values) -> [(label, value[, color])]."""
    help = HELP_CALC
    tool = ""

    def __init__(self, app, title, inputs, defaults):
        super().__init__(app)
        self.title = title
        self.inputs = inputs
        self.values = app.st.get(self.tool or title, defaults)
        self.results = []
        self.build()

    def compute(self, v) -> list:
        return []

    def build(self, keep=None):
        try:
            self.results = self.compute(self.values)
        except ValueError as e:
            self.results = [(str(e), "", L.BAD)]
        fields = list(self.inputs) + [Field("_h", "Answers", "header")] if self.results else list(self.inputs)
        vals = dict(self.values)
        for i, r in enumerate(self.results):
            color = r[2] if len(r) > 2 else None
            fields.append(Field(f"r{i}", r[0], "info", color=color))
            vals[f"r{i}"] = r[1]
        old = getattr(self, "form", None)
        self.form = EditList(fields, vals)
        if old is not None:
            self.form.sel, self.form.top = old.sel, old.top

    @property
    def text_entry(self):
        return self.form.editing

    @property
    def hint(self):
        return self.form.hint()

    def rows(self):
        return self.form.view(self.nrows), None

    def key(self, k):
        ev = self.form.handle(k)
        if not ev:
            return
        kind, _, key = ev.partition(":")
        if kind == "back":
            self.app.st.put(self.tool or self.title, {f.key: self.values.get(f.key, "") for f in self.inputs})
            self.app.pop(self)
        elif kind == "changed" and not key.startswith("r"):
            self.values[key] = self.form.values[key]
            self.changed(key)
            self.build()
        elif kind == "info":
            i = int(key[1:])
            if i < len(self.results):
                r = self.results[i]
                self.app.push(Message(self.app, self.title, f"{r[0]}\n{r[1]}" if r[1] else r[0]))

    def changed(self, key):
        pass


def num(v, key, **kw):
    """Parse one field; a bad entry raises ValueError naming the field."""
    try:
        return C.parse_number(v.get(key), **kw)
    except ValueError as e:
        raise ValueError(f"{key}: {e}")


# ---- the tools ----------------------------------------------------------------------

class Frequency(Calc):
    tool = "frequency"
    help = ("Type a frequency in MHz (or a wavelength in metres) and pick your license. Shows the band, "
            "whether you may transmit there and with which modes, and the wavelength. " + HELP_CALC)

    def __init__(self, app):
        super().__init__(app, "Frequency", [
            Field("MHz", "Frequency MHz", "decimal", maxlen=10),
            Field("m", "or wavelength m", "decimal", maxlen=10),
            Field("lic", "License", "choice", C.CLASSES),
        ], {"MHz": "146.52", "m": "", "lic": app.st.license})

    def changed(self, key):
        if key == "m" and self.values.get("m"):
            m = C.parse_number(self.values["m"])
            if m:
                self.values["MHz"] = C.fmt(C.wavelength_m(m), 6)
        elif key == "MHz":
            self.values["m"] = ""
        elif key == "lic":
            self.app.st.license = self.values["lic"]

    def compute(self, v):
        mhz = num(v, "MHz")
        if not mhz:
            return []
        lam = C.wavelength_m(mhz)
        band, seg, text = C.privilege(mhz, v.get("lic", "Technician"))
        out = [("Wavelength", f"{C.fmt(lam, 4)} m  {C.fmt(lam * C.FT_PER_M, 4)} ft"),
               ("Band", band.name if band else "none"),
               ("Transmit", text, L.OK if seg else L.BAD)]
        if seg:
            out.append(("Segment", f"{C.fmt(seg[0], 6)}-{C.fmt(seg[1], 6)} MHz"))
        if band and band.note:
            out.append(("Note", band.note, L.WARN))
        out.append(("Half-wave dipole", f"{C.fmt(468 / mhz, 4)} ft  {C.fmt(142.6 / mhz, 4)} m"))
        out.append(("Quarter wave", f"{C.fmt(234 / mhz, 4)} ft  {C.fmt(71.3 / mhz, 4)} m"))
        return out


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
        return [("Class", self.cycle)]

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


class Decibels(Calc):
    tool = "db"
    help = "Power to dBm and dBW, a gain or loss in dB applied to it, and a power ratio to dB. " + HELP_CALC

    def __init__(self, app):
        super().__init__(app, "Decibels", [
            Field("W", "Power W", "text", maxlen=12),
            Field("dB", "Gain or loss dB", "decimal", maxlen=8),
            Field("ratio", "Power ratio (x)", "decimal", maxlen=10),
        ], {"W": "100", "dB": "-3", "ratio": "2"})

    def compute(self, v):
        w = num(v, "W", prefixes=True)
        db = num(v, "dB", negative=True)
        ratio = num(v, "ratio")
        out = []
        if w:
            out += [("Power", f"{C.fmt(C.watts_to_dbm(w), 4)} dBm  {C.fmt(C.watts_to_dbm(w) - 30, 4)} dBW")]
        if db is not None:
            out.append((f"{C.fmt(db, 4)} dB as a ratio", f"x {C.fmt(C.db_to_ratio(db), 4)}"))
            if w:
                after = w * C.db_to_ratio(db)
                out.append(("After the change", f"{C.si(after, 'W')}  {C.fmt(C.watts_to_dbm(after), 4)} dBm", L.OK))
        if ratio:
            out.append((f"Ratio x{C.fmt(ratio, 4)} in dB", f"{C.fmt(C.ratio_to_db(ratio), 4)} dB"))
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
        return [("SWR", f"{C.fmt(r['swr'], 3)} : 1", col),
                ("Reflected power", f"{C.fmt(r['refl_pct'], 3)} %"),
                ("Return loss", rl),
                ("Mismatch loss", f"{C.fmt(r['mismatch'], 3)} dB"),
                ("Reflection coeff.", C.fmt(r["gamma"], 3))]


class Coax(Calc):
    tool = "coax"
    help = ("How much power reaches the antenna through the feed line (matched line, typical published "
            "loss; check your cable's datasheet). " + HELP_CALC)

    def __init__(self, app):
        super().__init__(app, "Coax loss", [
            Field("cable", "Cable", "choice", [c[0] for c in C.CABLES]),
            Field("len", "Length", "decimal", maxlen=8),
            Field("unit", "Length in", "choice", ["ft", "m"]),
            Field("MHz", "Frequency MHz", "decimal", maxlen=10),
            Field("W", "Power W", "decimal", maxlen=8),
        ], {"cable": "RG-8X", "len": "50", "unit": "ft", "MHz": "146.52", "W": "50"})

    def compute(self, v):
        ln, mhz, w = num(v, "len"), num(v, "MHz"), num(v, "W")
        if not (ln and mhz and w):
            return []
        ft = ln if v.get("unit") == "ft" else ln * C.FT_PER_M
        r = C.coax_loss(v.get("cable", "RG-8X"), ft, mhz, w)
        out = [("Loss", f"{C.fmt(r['loss'], 3)} dB", L.WARN if r["loss"] > 3 else L.OK),
               ("Reaches the antenna", f"{C.fmt(r['delivered'], 3)} W  ({C.fmt(r['pct'], 3)} %)"),
               ("Loss per 100 ft", f"{C.fmt(r['per100'], 3)} dB")]
        if r["extrapolated"]:
            out.append(("Estimate outside 10-400 MHz", "", L.DIM))
        return out


class Grid(Calc):
    tool = "grid"
    help = ("Your grid square from latitude and longitude (decimal degrees, like 41.71 and 72.73W), or type "
            "your grid. Add another grid for distance and the beam heading to it.")

    def __init__(self, app):
        super().__init__(app, "Grid square", [
            Field("lat", "My latitude", "text", maxlen=12),
            Field("lon", "My longitude", "text", maxlen=12),
            Field("me", "or my grid", "text", maxlen=6),
            Field("dx", "Other grid", "text", maxlen=6),
        ], {"lat": "", "lon": "", "me": "EN61", "dx": "FN31pr"})

    def compute(self, v):
        lat = C.parse_coord(v.get("lat"), "lat")
        lon = C.parse_coord(v.get("lon"), "lon")
        out = []
        if lat is not None and lon is not None:
            g = C.to_grid(lat, lon)
            out.append(("My grid", g, L.OK))
        else:
            g = C.norm_grid(v.get("me", ""))
            if v.get("me") and not g:
                return [("My grid looks wrong (like EN61 or EN61ex)", "", L.BAD)]
            if g:
                lat, lon = C.grid_center(g)
                out.append(("My grid", g, L.OK))
        if v.get("dx"):
            d = C.norm_grid(v["dx"])
            if not d:
                out.append(("Other grid looks wrong", "", L.BAD))
            elif lat is not None:
                la2, lo2 = C.grid_center(d)
                km = C.distance_km(lat, lon, la2, lo2)
                b = C.bearing_deg(lat, lon, la2, lo2)
                out += [("Distance", f"{C.fmt(km, 4)} km  {C.fmt(km / 1.609344, 4)} mi"),
                        ("Beam heading", f"{b:.0f}° {C.compass(b)} (true)"),
                        ("Long path", f"{(b + 180) % 360:.0f}°")]
        return out


class Clock(Screen):
    title = "UTC clock"
    help = "Hams log contacts in UTC, 24-hour time. The big time is UTC; your local time and offset are below."

    def rows(self):
        return [], None

    def tick(self):
        self.app.dirty = True

    def paint(self, surf, f):
        now = time.time()
        u = time.gmtime(now)
        lt = time.localtime(now)
        if not hasattr(self, "big"):
            import pygame
            path = next((p for p in T.TITLE_FONT_PATHS if os.path.exists(p)), None)
            self.big = pygame.font.Font(path, 58)
        big = self.big.render(time.strftime("%H:%M:%S", u), True, T.FG)
        y = T.TITLE_H + 2
        surf.blit(big, ((T.W - big.get_width()) // 2, y))
        y += big.get_height() + 2
        for text, col in ((time.strftime("%Y-%m-%d UTC   log %H%M", u), T.AMBER),
                          (time.strftime("Local %H:%M:%S  %a %d %b", lt), T.FG),
                          (C.offset_label(C.local_offset_minutes(now)) + f"  ({time.strftime('%Z', lt)})", T.DIM)):
            img = f["small"].render(text, True, col)
            surf.blit(img, ((T.W - img.get_width()) // 2, y))
            y += 17

    def key(self, k):
        if k.name in BACK or k.name in SELECT:
            self.app.pop(self)


class Phonetics(Calc):
    tool = "phonetics"
    help = "Spell a call sign (or any text) in the ITU phonetic alphabet."

    def __init__(self, app):
        super().__init__(app, "Phonetics", [Field("text", "Call sign", "text", maxlen=16)], {"text": "N0TNT"})

    def compute(self, v):
        return [(c, w or "(no phonetic)", L.OK if w else L.DIM) for c, w in C.spell(v.get("text", ""))]


class QSignals(Menu):
    help = "Common Q signals. Sent with a question mark they ask; without, they state. OK shows both."

    def __init__(self, app):
        items = [(f"{q} {m}", (lambda q=q, m=m, a=a: app.push(Message(app, q, f"{m}\n\n{q}? {a}"))))
                 for q, m, a in C.Q_SIGNALS]
        super().__init__(app, "Q signals", items)


class Home(Menu):
    help = HELP_MAIN

    def __init__(self, app):
        items = [
            ("Frequency and band", lambda: app.push(Frequency(app))),
            ("Band plan", lambda: app.push(BandPlan(app)), lambda: app.st.license),
            ("Ohm's law", lambda: app.push(Ohms(app))),
            ("Decibels", lambda: app.push(Decibels(app))),
            ("SWR", lambda: app.push(Swr(app))),
            ("Coax loss", lambda: app.push(Coax(app))),
            ("Grid square", lambda: app.push(Grid(app))),
            ("UTC clock", lambda: app.push(Clock(app)), lambda: time.strftime("%H:%M", time.gmtime())),
            ("Phonetics", lambda: app.push(Phonetics(app))),
            ("Q signals", lambda: app.push(QSignals(app))),
            ("About", lambda: app.push(Message(app, "About", HELP_MAIN + " From Ask Elmer, askelmer.com. "
                                               "Band privileges follow FCC Part 97; check the current rules "
                                               "before you transmit."))),
        ]
        super().__init__(app, APP_TITLE, items, "↑↓ move  OK open  ESC quit")


def main_ui() -> int:
    panel = L.Panel()
    kb = Keyboard()
    app = App(panel, kb if kb.ok else None)
    try:
        app.run()
    finally:
        if kb:
            kb.close()
    return 0
