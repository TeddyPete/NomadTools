"""Antenna Lab, the headline section of Ask Elmer Ham Tools. It is imported only when you open it.

The screens get a LabContext: the main app, plus Antenna Lab's own saved designs (antenna.json)."""
from __future__ import annotations

import json
import math
import os
import time

import pygame

from .. import config_dir
from .. import icons as IC
from .. import lcd as L
from .. import nomadui as T
from ..ui import BACK, DOWN, SELECT, UP, EditList, Field, Menu, Message, Screen, wrap
from . import extras as X
from . import lab, nec
from . import templates as TP

FT = 3.28084


def K(text, icon):
    """A key 4-8 label with its icon."""
    return (text, None, icon)

HELP_MAIN = ("Antenna Lab models real antennas with the NEC2 engine. Pick an antenna, set the "
             "frequency and the sizes, then Run (key 4) for feed impedance, SWR, gain and the radiation "
             "pattern. Tune (key 5) adjusts the main size until the antenna is resonant. Cut (key 8) "
             "lists what to build. Treat results as a model: trim and check the real antenna with an "
             "analyzer. From Ask Elmer, askelmer.com.")
HELP_DESIGN = ("Up/Down pick a setting, OK or Right edits it (red), OK saves. Lengths are in your units "
               "(Settings). Changing the frequency offers new starting sizes. 4 Run, 5 Tune, 6 SWR chart, "
               "7 Pattern, 8 Cut list.")
HELP_SWR = ("SWR against frequency into 50 ohm coax, through the matching device. The dashed line marks your "
            "design frequency; the green band is 2:1 or better. 5 sweeps wide. 6 Measure lays a real sweep over "
            "the model in green: from a NanoVNA on the USB port, or a Touchstone .s1p file from your home "
            "folder or a USB stick. A measurement through coax shows the SWR at the radio end.")
HELP_3D = ("The whole radiation pattern in 3D, with the antenna in the middle. The shape reaches out where the "
           "antenna is strong: amber is the peak, navy is 20 dB or more down. Left/Right turn it, Up/Down tilt it, "
           "5 spins it. Over ground only the half above the ground is shown. ESC goes back.")
HELP_PATTERN = "Left: azimuth (seen from above) at the main lobe's elevation. Right: elevation through the main lobe; the horizon is the bottom line. Rings are -3, -10 and -20 dB from the peak. 5 shows the whole pattern in 3D."


class State:
    def __init__(self):
        self.path = os.path.join(config_dir(), "antenna.json")
        self.units, self.ground, self.material = "ft", "average", "copper"
        self.tpl, self.mhz, self.params, self.device = "dipole", None, {}, {}
        self.cable, self.cable_ft = "RG-8X", 50.0
        try:
            d = json.load(open(self.path))
            self.units = d.get("units", self.units)
            self.ground = d.get("ground", self.ground)
            self.material = d.get("material", self.material)
            self.tpl = d.get("tpl", self.tpl)
            self.mhz = d.get("mhz", {})
            self.params = d.get("params", {})
            self.device = d.get("device", {})
            self.cable = d.get("cable", self.cable)
            self.cable_ft = float(d.get("cable_ft", self.cable_ft))
        except (OSError, ValueError):
            self.mhz = {}

    def save(self):
        try:
            os.makedirs(config_dir(), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"units": self.units, "ground": self.ground, "material": self.material,
                           "tpl": self.tpl, "mhz": self.mhz, "params": self.params, "device": self.device,
                           "cable": self.cable, "cable_ft": self.cable_ft}, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass


# ---- formatting ---------------------------------------------------------------------

def fmt_len(m: float, units: str, short=False) -> str:
    if m is None:
        return ""
    if units == "m":
        return f"{m:.3f} m" if m < 10 else f"{m:.2f} m"
    inches = m / 0.0254
    if short or inches < 12:
        return f"{m * FT:.2f} ft" if inches >= 12 else f"{inches:.2f} in"
    ft = int(inches // 12)
    return f"{ft} ft {inches - ft * 12:.1f} in"


def fmt_mhz(m: float) -> str:
    return f"{m:.2f}" if m >= 100 else f"{m:.3f}" if m >= 10 else f"{m:.4f}"


def fmt_swr(s: float) -> str:
    return ">20" if s > 20 else f"{s:.2f}"


def fmt_z(zr, zi) -> str:
    if zr != zr:
        return "?"
    sign = "+" if zi >= 0 else "-"
    return f"{zr:.1f} {sign}j{abs(zi):.1f}"


def swr_color(s):
    return L.OK if s <= 1.5 else L.WARN if s <= 2.5 else L.BAD


UNIT_OF = {"angle": "deg", "percent": "%", "uh": "uH", "pf": "pF", "ohms": "ohm"}


def to_display(pd: TP.Param, v, units: str) -> str:
    if pd.kind == "select":
        return next((lab_ for val, lab_ in pd.options if str(val) == str(v)), str(v))
    x = float(v)
    if pd.kind == "length":
        x = x * FT if units == "ft" else x
        return f"{x:.4g}" if x < 100 else f"{x:.1f}"
    if pd.kind == "count":
        return str(round(x))
    return f"{x:.4g}"


def from_display(pd: TP.Param, s: str, units: str):
    if pd.kind == "select":
        return next((val for val, lab_ in pd.options if lab_ == s), s)
    x = float(s)
    if pd.kind == "length" and units == "ft":
        x /= FT
    if pd.kind == "count":
        x = round(x)
    if pd.min is not None:
        x = max(pd.min, x)
    if pd.max is not None:
        x = min(pd.max, x)
    return x


# ---- context ------------------------------------------------------------------------

class LabContext:
    """What the Antenna Lab screens call "app": the main app (screens, keys, GPS, tasks) with
    Antenna Lab's own state. Reads and writes of anything else go to the main app."""
    _own = ("main", "st", "measured")

    def __init__(self, main):
        object.__setattr__(self, "main", main)
        object.__setattr__(self, "st", State())
        object.__setattr__(self, "measured", {})   # design id -> [(mhz, swr, zr, zi)] from a NanoVNA or .s1p

    def __getattr__(self, name):
        return getattr(self.main, name)

    def __setattr__(self, name, value):
        if name in self._own:
            object.__setattr__(self, name, value)
        else:
            setattr(self.main, name, value)


_ctx = None


def context(main) -> LabContext:
    global _ctx
    if _ctx is None or _ctx.main is not main:
        _ctx = LabContext(main)
    return _ctx


def open_lab(main, mhz: float | None = None) -> None:
    """Open Antenna Lab from the home menu, or straight to a design at mhz (from Band check)."""
    app = context(main)
    app.push(Home(app))
    if not nec.engine_path():
        app.push(Message(app, "Engine missing", "The NEC2 engine (nec2c) is not installed. "
                         "Reinstall Ask Elmer Ham Tools from the store.", L.BAD))
        return
    if mhz:
        t = TP.by_id(app.st.tpl) or TP.TEMPLATES[0]
        app.push(Design(app, t, mhz))


# ---- screens ------------------------------------------------------------------------

FAMILIES = ["Wire antennas", "Verticals", "Beams", "Loops"]


class Home(Menu):
    help = HELP_MAIN

    def __init__(self, app):
        items = [(f, (lambda f=f: app.push(Family(app, f))),
                  str(sum(1 for t in TP.TEMPLATES if t.family == f)), L.FG, IC.FAMILY_ICON[f]) for f in FAMILIES]
        items.insert(0, ("Last design", lambda: open_design(app, app.st.tpl),
                         lambda: TP.by_id(app.st.tpl).name if TP.by_id(app.st.tpl) else "", L.OK, "last"))
        items += [("Settings", lambda: app.push(Settings(app)), lambda: app.st.units, L.FG, "gear"),
                  ("About", lambda: app.push(Message(app, "About", HELP_MAIN)), "", L.FG, "about")]
        super().__init__(app, "Antenna Lab", items, "↑↓ move  OK open  ESC back")

    def key(self, k):
        if k.name in BACK:
            self.app.st.save()
        return super().key(k)


class Family(Menu):
    help = HELP_MAIN

    def __init__(self, app, fam):
        items = [(t.name, (lambda t=t: open_design(app, t.id)), "", L.FG, IC.for_template(t.id, t.family))
                 for t in TP.TEMPLATES if t.family == fam]
        super().__init__(app, fam, items)


def open_design(app, tid):
    t = TP.by_id(tid) or TP.TEMPLATES[0]
    app.st.tpl = t.id
    app.push(Design(app, t))


class Settings(Screen):
    title = "Settings"
    help = ("Units for every length. Ground and conductor material apply to every antenna. The feed line "
            "(type and length) adds coax loss and the SWR at the radio to the results.")

    def __init__(self, app):
        super().__init__(app)
        st = app.st
        self.glabels = {g[0]: g[1] for g in nec.GROUNDS}
        self.mlabels = {k: v[0] for k, v in nec.MATERIALS.items()}
        self.form = EditList([
            Field("units", "Units", "choice", ["feet", "metres"]),
            Field("ground", "Ground", "choice", list(self.glabels.values())),
            Field("material", "Conductor", "choice", list(self.mlabels.values())),
            Field("cable", "Feed line", "choice", ["None"] + list(X.CABLES)),
            Field("cable_len", f"Feed line {st.units}", "decimal", maxlen=8,
                  visible=lambda v: v["cable"] != "None"),
        ], {"units": "feet" if st.units == "ft" else "metres", "ground": self.glabels.get(st.ground, "Average"),
            "material": self.mlabels.get(st.material, "Copper"), "cable": st.cable,
            "cable_len": f"{st.cable_ft if st.units == 'ft' else st.cable_ft / FT:.4g}"})

    @property
    def text_entry(self):
        return self.form.editing

    @property
    def hint(self):
        return self.form.hint()

    def rows(self):
        return self.form.view(), None

    def key(self, k):
        ev = self.form.handle(k)
        v = self.form.values
        st = self.app.st
        st.units = "ft" if v["units"] == "feet" else "m"
        st.ground = next(k_ for k_, lab_ in self.glabels.items() if lab_ == v["ground"])
        st.material = next(k_ for k_, lab_ in self.mlabels.items() if lab_ == v["material"])
        st.cable = v["cable"]
        try:
            ln = float(v["cable_len"])
            if ln >= 0:
                st.cable_ft = ln if st.units == "ft" else ln * FT
        except ValueError:
            pass
        if ev == "back":
            st.save()
            self.app.pop(self)


class Design(Screen):
    """The antenna's settings, edited in place, with Run / Tune on keys 4-8."""
    help = HELP_DESIGN

    def __init__(self, app, t: TP.Template, mhz: float | None = None):
        super().__init__(app)
        self.t = t
        st = app.st
        if mhz:
            # opened from Band check: fresh starting sizes for that frequency
            self.mhz = float(mhz)
            self.p = dict(t.defaults(self.mhz))
        else:
            self.mhz = float(st.mhz.get(t.id) or t.default_mhz)
            saved = st.params.get(t.id)
            self.p = {**t.defaults(self.mhz), **(saved or {})}
        self.device = st.device.get(t.id) or t.device
        self.result: lab.Result | None = None
        self.title = t.name
        self.build_form()

    # -- form --
    def build_form(self, keep_sel: str | None = None):
        u = self.app.st.units
        fields = [Field("mhz", "Frequency MHz", "decimal", maxlen=10)]
        values = {"mhz": fmt_mhz(self.mhz)}
        self.pdefs = {}
        for pd in self.t.params(self.p):
            unit = (u if pd.kind == "length" else UNIT_OF.get(pd.kind, ""))
            label = f"{pd.label} {unit}".strip() if unit else pd.label
            self.pdefs[pd.id] = pd
            if pd.kind == "select":
                fields.append(Field(pd.id, pd.label, "choice", [lab_ for _v, lab_ in pd.options]))
            else:
                fields.append(Field(pd.id, label, "decimal", maxlen=10, help=pd.help))
            values[pd.id] = to_display(pd, self.p.get(pd.id, 0), u)
        fields.append(Field("device", "Match", "choice", [v[0] for v in lab.DEVICES.values()]))
        values["device"] = lab.DEVICES.get(self.device, lab.DEVICES["choke-1-1"])[0]
        fields += [Field("run", "Run the model", "action"), Field("tune", "Tune for me", "action")]
        if self.t.id == "yagi":
            fields.append(Field("optimize", "Optimize the beam", "action"))
        fields.append(Field("defaults", "Starting sizes for this frequency", "action"))
        if not self.t.tune:
            fields = [f for f in fields if f.key != "tune"]
        old = getattr(self, "form", None)
        self.form = EditList(fields, values)
        if keep_sel:
            self.form.select(keep_sel)
        elif old is not None:
            self.form.sel = old.sel

    def save(self):
        st = self.app.st
        st.mhz[self.t.id] = self.mhz
        st.params[self.t.id] = self.p
        st.device[self.t.id] = self.device
        st.tpl = self.t.id
        st.save()

    @property
    def text_entry(self):
        return self.form.editing

    @property
    def hint(self):
        return self.form.hint()

    def right(self):
        return f"{fmt_mhz(self.mhz)} MHz"

    def softkeys(self):
        return [(K("Run", "run"), self.run), (K("Tune", "tune"), self.tune) if self.t.tune else None,
                (K("SWR", "swr"), lambda: self.show(SwrChart)), (K("Pattern", "pattern"), lambda: self.show(Pattern)),
                (K("Cut", "cut"), self.cutlist)]

    def rows(self):
        return self.form.view(self.nrows), None

    def key(self, k):
        ev = self.form.handle(k)
        if not ev:
            return
        kind, _, key = ev.partition(":")
        if kind == "back":
            self.save()
            self.app.pop(self)
        elif kind == "action":
            {"run": self.run, "tune": self.tune, "defaults": self.reset, "optimize": self.optimize}[key]()
        elif kind == "changed":
            self.changed(key)

    def changed(self, key):
        v = self.form.values[key]
        u = self.app.st.units
        if key == "mhz":
            try:
                mhz = float(v)
                if not 0.1 <= mhz <= 3000:
                    raise ValueError
            except ValueError:
                self.app.push(Message(self.app, "Frequency", "Type a frequency in MHz, like 14.2 or 146.52.", L.BAD))
                self.form.values["mhz"] = fmt_mhz(self.mhz)
                return
            old = self.mhz
            self.mhz = mhz
            self.result = None
            if abs(math.log(mhz / old)) > 0.15:
                self.app.push(ConfirmNew(self.app, self, old))
            return
        if key == "device":
            self.device = next(k_ for k_, d in lab.DEVICES.items() if d[0] == v)
            self.result = None
            return
        pd = self.pdefs.get(key)
        if not pd:
            return
        try:
            nv = from_display(pd, v, u)
        except ValueError:
            self.app.push(Message(self.app, pd.label, "That is not a number.", L.BAD))
            self.form.values[key] = to_display(pd, self.p.get(key, 0), u)
            return
        prev = dict(self.p)
        self.p[key] = nv
        self.p = TP.adjust(self.t, prev, self.p, self.mhz)
        self.result = None
        self.build_form(keep_sel=key)

    def reset(self):
        self.p = self.t.defaults(self.mhz)
        self.device = self.t.device
        self.result = None
        self.build_form()
        self.save()

    # -- engine --
    def ground(self):
        return nec.ground_of(self.app.st.ground)

    def run(self, then=None):
        self.save()
        t, p, mhz, dev = self.t, dict(self.p), self.mhz, self.device
        g, mat = self.ground(), self.app.st.material

        def done(r):
            self.result = r
            if then:
                then()
            else:
                self.app.push(Results(self.app, self))
        self.app.task(t.name, "Running NEC2", lambda: lab.run_design(t, p, mhz, g, mat, dev), done)

    def tune(self):
        if not self.t.tune:
            return
        t, p, mhz, dev = self.t, dict(self.p), self.mhz, self.device
        g, mat = self.ground(), self.app.st.material

        def done(res):
            q, r = res
            if not r:
                self.app.push(Message(self.app, "Tune", "The engine could not find a better setting here. "
                                      "Check the sizes and the frequency.", L.WARN))
                return
            self.p = {**self.p, **{k: v for k, v in q.items()}}
            self.build_form()
            self.save()
            self.run()
        self.app.task(f"Tune {t.tune['label']}", "Tuning", lambda: lab.tune(t, p, mhz, g, mat, dev), done)

    def optimize(self):
        def go(goal):
            t, p, mhz, mat = self.t, dict(self.p), self.mhz, self.app.st.material
            self.app.task("Optimize", f"{goal}: searching",
                          lambda: X.optimize_beam(t, p, mhz, mat, goal), lambda r: self.app.push(Optimized(self.app, self, r)))
        self.app.push(Menu(self.app, "Optimize for", [(g, (lambda g=g: (self.app.pop(), go(g)))) for g in X.GOALS]))

    def show(self, cls):
        if self.result is None:
            self.run(then=lambda: self.app.push(cls(self.app, self)))
        else:
            self.app.push(cls(self.app, self))

    def cutlist(self):
        self.app.push(CutList(self.app, self))


class ConfirmNew(Screen):
    title = "New frequency"

    def __init__(self, app, design, old):
        super().__init__(app)
        self.d, self.old = design, old
        self.lines = wrap(app.panel, f"{fmt_mhz(design.mhz)} MHz is far from {fmt_mhz(old)} MHz. "
                                     "Start from the standard sizes for the new frequency?")
        self.hint = "OK new sizes   ESC keep sizes"

    def rows(self):
        return self.lines, None

    def key(self, k):
        if k.name in SELECT or k.char in ("y", "Y"):
            self.app.pop(self)
            self.d.reset()
        elif k.name in BACK or k.char in ("n", "N"):
            self.app.pop(self)


class Results(Screen):
    help = ("The model at your design frequency. Z is the feed impedance (resistance and reactance); "
            "SWR is into 50 ohm coax through the matching device. Gain is in dBi at the takeoff angle "
            "shown. 5 tunes, 6 shows SWR across the band, 7 the pattern, 8 the cut list.")

    def __init__(self, app, design):
        super().__init__(app)
        self.d = design
        self.title = design.t.name
        self.top = 0

    def right(self):
        return f"{fmt_mhz(self.d.mhz)} MHz"

    def softkeys(self):
        d = self.d
        return [(K("Design", "edit"), lambda: self.app.pop(self)), (K("Tune", "tune"), self.tune) if d.t.tune else None,
                (K("SWR", "swr"), lambda: self.app.push(SwrChart(self.app, d))),
                (K("Pattern", "pattern"), lambda: self.app.push(Pattern(self.app, d))), (K("Cut", "cut"), d.cutlist)]

    def tune(self):
        self.app.pop(self)
        self.d.tune()

    def lines(self):
        r, u = self.d.result, self.app.st.units
        if r is None:
            return [("Not run yet: press 4", L.DIM)]
        dev = lab.DEVICES.get(self.d.device, ("", 1))[0]
        out = [("SWR", swr_color(r.swr), f"{fmt_swr(r.swr)} : 1"),
               ("Feed Z ohm", L.FG, fmt_z(r.zr, r.zi))]
        if self.d.device not in ("choke-1-1", "none", "tuner"):
            out.append(("  through", L.DIM, dev))
        if r.resonances:
            near = min(r.resonances, key=lambda f: abs(f - r.mhz))
            out.append(("Resonant", L.FG, f"{fmt_mhz(near)} MHz"))
        else:
            out.append(("Resonant", L.DIM, "not in sweep"))
        out.append(("Lowest SWR", swr_color(r.min_swr[1]), f"{fmt_swr(r.min_swr[1])} @ {fmt_mhz(r.min_swr[0])}"))
        if r.bw2:
            out.append(("2:1 width", L.FG, f"{(r.bw2[1] - r.bw2[0]) * 1000:.0f} kHz"))
        if r.gain is not None:
            where = "" if r.free_space else f" @ {r.takeoff:.0f}°"
            out.append(("Gain", L.FG, f"{r.gain:.1f} dBi{where}"))
        if r.fb is not None and r.fb > 3:
            out.append(("Front/back", L.FG, f"{r.fb:.1f} dB"))
        if r.az_bw:
            out.append(("Beamwidth", L.FG, f"{r.az_bw:.0f}°"))
        if r.polarization:
            out.append(("Polarization", L.FG, r.polarization))
        if r.efficiency is not None:
            out.append(("Efficiency", L.FG, f"{r.efficiency:.0f}%"))
        st = self.app.st
        if st.cable in X.CABLES and st.cable_ft > 0 and r.swr < 900:
            fl = X.line_loss(st.cable, st.cable_ft, r.mhz, r.swr)
            ln = f"{st.cable_ft:.0f} ft" if u == "ft" else f"{st.cable_ft / FT:.0f} m"
            out.append((f"{st.cable} {ln}", L.FG,
                        f"{fl['total']:.1f} dB loss"))
            out.append(("  SWR at radio", swr_color(fl["swr_in"]), f"{fmt_swr(fl['swr_in'])} : 1"))
            out.append(("  Power out", L.FG, f"{fl['delivered_pct']:.0f}%"))
        out.append(("Engine time", L.DIM, f"{r.secs:.1f} s"))
        for w in r.warnings + r.errors:
            out += [(x, L.WARN) for x in wrap(self.app.panel, w)]
        return out

    def rows(self):
        ls = self.lines()
        n = self.nrows
        self.top = max(0, min(self.top, len(ls) - n))
        return ls[self.top:self.top + n], None

    @property
    def hint(self):
        return "↑↓ scroll  ESC back"

    def key(self, k):
        if k.name in UP:
            self.top = max(0, self.top - 1)
        elif k.name in DOWN:
            self.top += 1
        elif k.name in BACK:
            self.app.pop(self)


class Optimized(Screen):
    title = "Optimized"
    help = ("The beam optimizer changed the reflector and director lengths and the spacings, in free space, "
            "without making the boom longer. OK keeps the new sizes and tunes the driven element for "
            "resonance; ESC keeps your old ones.")
    hint = "OK use these  ESC keep mine"

    def __init__(self, app, design, r):
        super().__init__(app)
        self.d, self.r = design, r

    def rows(self):
        b, a = self.r["before"], self.r["after"]
        if not a or not b:
            return [("The engine didn't return a pattern.", L.BAD)], None
        return [(self.r["goal"] + ", free space", L.DIM),
                ("Gain dBi", L.FG, f"{b[0]:.1f} \u2192 {a[0]:.1f}"),
                ("Front/rear dB", L.FG, f"{b[1]:.1f} \u2192 {a[1]:.1f}"),
                ("Feed R ohm", L.FG, f"{b[2]:.0f} \u2192 {a[2]:.0f}"),
                ("Then: tune the driven element", L.DIM)], None

    def key(self, k):
        if k.name in SELECT and self.r["after"]:
            self.app.pop(self)
            self.d.p = {**self.d.p, **self.r["params"]}
            self.d.build_form()
            self.d.save()
            self.d.tune()
        elif k.name in BACK:
            self.app.pop(self)


class CutList(Screen):
    help = "What to cut and build. Lengths are starting points: cut a little long, then trim while checking SWR."

    def __init__(self, app, design):
        super().__init__(app)
        self.d = design
        self.title = "Cut list"
        self.top = 0

    def softkeys(self):
        return [(K("Design", "edit"), lambda: self.app.pop(self)), None, None, None, (K("Units", "wide"), self.flip)]

    def flip(self):
        st = self.app.st
        st.units = "m" if st.units == "ft" else "ft"
        st.save()
        self.d.build_form()

    def lines(self):
        u = self.app.st.units
        b = self.d.t.build(self.d.p, self.d.mhz)
        out = []
        for c in b.cut:
            q = f"{c.qty} x " if c.qty and c.qty > 1 else ""
            val = f"{q}{fmt_len(c.length, u)}" if c.length is not None else ""
            if val and self.app.panel.text_width(c.part) + self.app.panel.text_width(val) > 300:
                out += [(x, L.FG) for x in wrap(self.app.panel, c.part)]
                out.append(("", L.FG, val))
            else:
                out.append((c.part, L.FG, val))
            if c.note:
                out += [(x, L.DIM) for x in wrap(self.app.panel, c.note)]
        for note in b.notes:
            out += [(x, L.WARN) for x in wrap(self.app.panel, note)]
        return out

    def rows(self):
        ls = self.lines()
        n = self.nrows
        self.top = max(0, min(self.top, len(ls) - n))
        return ls[self.top:self.top + n], None

    def key(self, k):
        if k.name in UP:
            self.top = max(0, self.top - 1)
        elif k.name in DOWN:
            self.top += 1
        elif k.name == "pagedown":
            self.top += self.nrows
        elif k.name == "pageup":
            self.top = max(0, self.top - self.nrows)
        elif k.name in BACK:
            self.app.pop(self)


# ---- charts -------------------------------------------------------------------------

GRID = T.RULE
AXIS = T.DIM
TRACE = T.AMBER
GOOD = (0x1B, 0x3D, 0x2E)   # Ask Elmer green tint


class Chart(Screen):
    """A screen that draws over the row area (y 27..139)."""
    top_y, bot_y = T.TITLE_H + 2, T.H - T.KEYBAR_H - 2

    def __init__(self, app, design):
        super().__init__(app)
        self.d = design

    def right(self):
        return f"{fmt_mhz(self.d.mhz)} MHz"

    def rows(self):
        return [], None

    def softkeys(self):
        d = self.d
        return [(K("Design", "edit"), self.to_design), (K("3D", "3d"), lambda: self.swap(Pattern3D)),
                (K("SWR", "swr"), lambda: self.swap(SwrChart)), (K("Pattern", "pattern"), lambda: self.swap(Pattern)),
                (K("Cut", "cut"), d.cutlist)]

    def to_design(self):
        while self.app.stack and self.app.stack[-1] is not self.d:
            self.app.pop(self.app.stack[-1])

    def swap(self, cls):
        if isinstance(self, cls):
            return
        self.app.pop(self)
        self.app.push(cls(self.app, self.d))

    def key(self, k):
        if k.name in BACK:
            self.app.pop(self)


class SwrChart(Chart):
    help = HELP_SWR
    title = "SWR"

    def __init__(self, app, design):
        super().__init__(app, design)
        self.wide = None   # Result of a wide sweep

    def softkeys(self):
        d = self.d
        return [(K("Design", "edit"), self.to_design), (K("Wide", "wide"), self.toggle_wide),
                (K("Measure", "measure"), self.measure), (K("Pattern", "pattern"), lambda: self.swap(Pattern)),
                (K("Cut", "cut"), d.cutlist)]

    @property
    def measured(self):
        return self.app.measured.get(self.d.t.id)

    def measure(self):
        r = self.wide or self.d.result
        lo, hi = (r.sweep[0][0], r.sweep[-1][0]) if r and r.sweep else (self.d.mhz * 0.95, self.d.mhz * 1.05)
        tid = self.d.t.id

        def got(pts):
            self.app.measured[tid] = pts

        def vna():
            self.app.pop()
            self.app.task("NanoVNA", "Sweeping", lambda: X.nanovna_sweep(lo, hi, 101), got)

        def s1p():
            self.app.pop()
            files = X.find_s1p()
            if not files:
                self.app.push(Message(self.app, "No .s1p files", "Save a Touchstone .s1p file from your analyzer "
                                      "to the home folder or a USB stick, then try again.", L.WARN))
                return
            self.app.push(Menu(self.app, "Load .s1p", [(os.path.basename(f), (lambda f=f: (
                self.app.pop(), self.app.task("Load", "Reading", lambda: X.read_s1p(f), got)))) for f in files[:20]]))

        def clear():
            self.app.pop()
            self.app.measured.pop(tid, None)
        self.app.push(Menu(self.app, "Measure", [("NanoVNA sweep (USB)", vna), ("Load .s1p file", s1p),
                                                 ("Clear measurement", clear)]))

    def toggle_wide(self):
        if self.wide is not None:
            self.wide = None
            self.app.wake()
            return
        d = self.d
        t, p, mhz, dev, g, mat = d.t, dict(d.p), d.mhz, d.device, d.ground(), self.app.st.material

        def done(r):
            self.wide = r
        self.app.task("Wide sweep", "Sweeping", lambda: lab.run_design(t, p, mhz, g, mat, dev, wide=True,
                                                                         pattern_step=(15, 30)), done)

    def paint(self, surf, f):
        r = self.wide or self.d.result
        if not r or not r.sweep:
            surf.blit(f["small"].render("No sweep yet", True, L.DIM), (10, 60))
            return
        x0, x1 = 34, T.W - 8
        y0, y1 = self.top_y + 2, self.bot_y - 14
        pts = r.sweep
        lo, hi = pts[0][0], pts[-1][0]
        smax = 5.0

        def X_(mhz):
            return x0 + (mhz - lo) / (hi - lo) * (x1 - x0)

        def Y(s):
            return y1 - (min(s, smax) - 1) / (smax - 1) * (y1 - y0)
        surf.fill(GOOD, (x0, Y(2), x1 - x0, y1 - Y(2)))
        tiny = f["tiny"]
        for s in (1, 1.5, 2, 3, 5):
            y = Y(s)
            pygame.draw.line(surf, GRID, (x0, y), (x1, y))
            lab_ = tiny.render(f"{s:g}", True, AXIS)
            surf.blit(lab_, (x0 - 4 - lab_.get_width(), y - 7))
        b = TP.find_band(self.d.mhz)
        if b and not self.wide:
            for edge in (b[2], b[3]):
                if lo <= edge <= hi:
                    pygame.draw.line(surf, (90, 70, 40), (X_(edge), y0), (X_(edge), y1))
        xd = X_(self.d.mhz)
        for yy in range(int(y0), int(y1), 6):
            pygame.draw.line(surf, (200, 200, 120), (xd, yy), (xd, yy + 3))
        line = [(X_(p[0]), Y(p[1])) for p in pts]
        pygame.draw.lines(surf, TRACE, False, line, 2)
        for txt, x, anchor in ((fmt_mhz(lo), x0, 0), (fmt_mhz(hi), x1, 1)):
            img = tiny.render(txt, True, AXIS)
            surf.blit(img, (x - img.get_width() * anchor, y1 + 2))
        mn = r.min_swr
        info = f"min {fmt_swr(mn[1])} @ {fmt_mhz(mn[0])}"
        img = tiny.render(info, True, swr_color(mn[1]))
        surf.blit(img, ((x0 + x1) // 2 - img.get_width() // 2, y1 + 2))
        if self.wide:
            surf.blit(tiny.render("wide sweep", True, L.WARN), (x0 + 4, y0))
        m = self.measured
        if m:
            seg = [(X_(p[0]), Y(p[1])) for p in m if lo <= p[0] <= hi]
            if len(seg) >= 2:
                pygame.draw.lines(surf, L.OK, False, seg, 2)
            img = tiny.render("measured", True, L.OK)
            surf.blit(img, (x1 - img.get_width() - 2, y0))


class Pattern(Chart):
    help = HELP_PATTERN
    title = "Pattern"

    def paint(self, surf, f):
        r = self.d.result
        if not r or not r.az_slice:
            surf.blit(f["small"].render("No pattern yet", True, L.DIM), (10, 60))
            return
        tiny = f["tiny"]
        peak = r.gain
        cy = (self.top_y + self.bot_y) // 2 + 6
        rad = (self.bot_y - self.top_y) // 2 - 10

        def rr(g):
            return rad * max(0.0, 1 + (g - peak) / 30)   # 30 dB range

        def rings(cx, cy_, half=False):
            for db in (0, -3, -10, -20):
                R = int(rr(peak + db))
                if R <= 1:
                    continue
                if half:
                    pygame.draw.arc(surf, GRID, (cx - R, cy_ - R, 2 * R, 2 * R), 0, math.pi)
                else:
                    pygame.draw.circle(surf, GRID, (cx, cy_), R, 1)
        # azimuth (top view): phi 0 = +X = up on screen
        cxa = 78
        rings(cxa, cy)
        pygame.draw.line(surf, GRID, (cxa - rad, cy), (cxa + rad, cy))
        pygame.draw.line(surf, GRID, (cxa, cy - rad), (cxa, cy + rad))
        pts = [(cxa + rr(g) * math.sin(math.radians(ph)), cy - rr(g) * math.cos(math.radians(ph)))
               for ph, g in r.az_slice]
        if len(pts) > 2:
            pygame.draw.polygon(surf, TRACE, pts, 2)
        surf.blit(tiny.render("Azimuth", True, AXIS), (4, self.top_y))
        # elevation: elev 0..180 drawn as a half circle above the ground line
        cxe, cye = 236, self.bot_y - 16
        rade = min(rad + 14, 78)

        def re_(g):
            return rade * max(0.0, 1 + (g - peak) / 30)
        for db in (0, -3, -10, -20):
            R = int(re_(peak + db))
            if R > 1:
                pygame.draw.arc(surf, GRID, (cxe - R, cye - R, 2 * R, 2 * R), 0, math.pi)
        pygame.draw.line(surf, AXIS, (cxe - rade, cye), (cxe + rade, cye))
        ep = [(cxe + re_(g) * math.cos(math.radians(e)), cye - re_(g) * math.sin(math.radians(e)))
              for e, g in r.el_slice if 0 <= e <= 180]
        if len(ep) > 2:
            pygame.draw.lines(surf, TRACE, False, ep, 2)
        surf.blit(tiny.render("Elevation", True, AXIS), (cxe - 30, self.top_y))
        info = f"{r.gain:.1f} dBi" + ("" if r.free_space else f" @ {r.takeoff:.0f}°")
        img = tiny.render(info, True, L.OK)
        surf.blit(img, (T.W - img.get_width() - 4, self.bot_y - 12))
        if r.fb is not None and r.fb > 3:
            surf.blit(tiny.render(f"F/B {r.fb:.0f} dB", True, AXIS), (4, self.bot_y - 12))


# ---- 3D pattern -----------------------------------------------------------------------

RAMP = [(0.0, (0x1A, 0x3A, 0x5C)), (0.45, (0x1F, 0x7A, 0x8C)), (0.75, (0x5C, 0xC0, 0x8A)),
        (1.0, (0xE8, 0xA3, 0x3D))]   # navy, teal, green, amber


def ramp(t: float):
    t = max(0.0, min(1.0, t))
    for (a, ca), (b, cb) in zip(RAMP, RAMP[1:]):
        if t <= b:
            k = (t - a) / (b - a)
            return tuple(round(ca[i] + k * (cb[i] - ca[i])) for i in range(3))
    return RAMP[-1][1]


def pattern_mesh(r) -> tuple[list, list, list]:
    """(rows of (x, y, z, level) on the unit sphere scaled by gain, theta list,
    phi list) from r.pattern3d. level 0..1 over a 30 dB range."""
    grid = {(th, ph): g for th, ph, g in r.pattern3d}
    thetas = sorted({th for th, _ph in grid})
    phis = sorted({ph for _th, ph in grid})
    peak = r.gain if r.gain is not None else max(grid.values())
    rows = []
    for th in thetas:
        row = []
        for ph in phis:
            g = grid.get((th, ph), peak - 40)
            lv = max(0.0, 1 + (g - peak) / 30)
            t_, p_ = math.radians(th), math.radians(ph)
            row.append((lv * math.sin(t_) * math.cos(p_), lv * math.sin(t_) * math.sin(p_), lv * math.cos(t_), lv))
        rows.append(row)
    return rows, thetas, phis


class Pattern3D(Chart):
    help = HELP_3D
    title = "3D pattern"
    hint = "\u2190\u2192\u2191\u2193 turn  ESC back"

    def __init__(self, app, design):
        super().__init__(app, design)
        self.yaw, self.pitch = -40.0, 25.0
        self.spinning = False
        self._last = 0.0
        self._mesh = None

    def softkeys(self):
        d = self.d
        return [(K("Design", "edit"), self.to_design),
                (("Stop", L.WARN, "spin") if self.spinning else K("Spin", "spin"), self.toggle_spin),
                (K("SWR", "swr"), lambda: self.swap(SwrChart)), (K("2D", "2d"), lambda: self.swap(Pattern)),
                (K("Cut", "cut"), d.cutlist)]

    def toggle_spin(self):
        self.spinning = not self.spinning
        self.app.wake()

    def tick(self):
        if self.spinning and time.monotonic() - self._last > 0.12:
            self._last = time.monotonic()
            self.yaw = (self.yaw + 8) % 360
            self.app.wake()

    def key(self, k):
        n = k.name
        if n == "esc":
            self.app.pop(self)
        elif n in ("left", "right"):
            self.yaw = (self.yaw + (-15 if n == "left" else 15)) % 360
        elif n in UP or n in DOWN:
            self.pitch = max(-10.0, min(90.0, self.pitch + (10 if n in UP else -10)))
        elif n in SELECT:
            self.toggle_spin()

    def mesh(self):
        r = self.d.result
        if self._mesh is None or self._mesh[0] is not r:
            self._mesh = (r, pattern_mesh(r))
        return self._mesh[1]

    def view(self):
        cy_, sy = math.cos(math.radians(self.yaw)), math.sin(math.radians(self.yaw))
        ce, se = math.cos(math.radians(self.pitch)), math.sin(math.radians(self.pitch))

        def v(x, y, z):
            x1, y1 = x * cy_ - y * sy, x * sy + y * cy_
            return x1, z * ce + y1 * se, y1 * ce - z * se   # screen x, screen up, depth (far +)
        return v

    def paint(self, surf, f):
        r = self.d.result
        tiny = f["tiny"]
        if not r or not r.pattern3d:
            surf.blit(f["small"].render("No pattern yet: Run first", True, L.DIM), (10, 60))
            return
        rows, thetas, phis = self.mesh()
        v = self.view()
        free = r.free_space
        top, bot = self.top_y, self.bot_y
        cx = 138
        if free:
            size, cy = (bot - top) / 2 - 2, (top + bot) / 2
        else:
            # fit the dome and the ground disc between the title and the key bar
            ce, se = math.cos(math.radians(self.pitch)), abs(math.sin(math.radians(self.pitch)))
            zmax = max(q[2] for row in rows for q in row)
            above, below = zmax * ce + se, max(se, 0.08)
            size = min(125.0, (bot - top - 6) / (above + below))
            cy = top + 3 + above * size
        surf.set_clip((0, top - 1, T.W, bot - top + 2))

        def P(x, y, z):
            sx_, sy_, d = v(x, y, z)
            return cx + sx_ * size, cy - sy_ * size, d
        # ground disc and the forward mark
        if not free:
            ring = [P(math.cos(a / 18 * math.pi), math.sin(a / 18 * math.pi), 0) for a in range(36)]
            pygame.draw.polygon(surf, (0x17, 0x2E, 0x22), [(x, y) for x, y, _ in ring])
            pygame.draw.polygon(surf, GRID, [(x, y) for x, y, _ in ring], 1)
        fx, fy, _ = P(1.12, 0, 0)
        ox, oy, _ = P(0, 0, 0)
        pygame.draw.line(surf, AXIS, (ox, oy), (fx, fy))
        # faces, far to near
        light = (0.35, -0.45, 0.82)
        faces = []
        nth, nph = len(thetas), len(phis)
        wrap_phi = phis and (phis[-1] - phis[0]) >= 300
        for i in range(nth - 1):
            for j in range(nph if wrap_phi else nph - 1):
                j2 = (j + 1) % nph
                a, b, c, d_ = rows[i][j], rows[i][j2], rows[i + 1][j2], rows[i + 1][j]
                pa, pb, pc, pd = (P(*q[:3]) for q in (a, b, c, d_))
                lv = (a[3] + b[3] + c[3] + d_[3]) / 4
                if lv <= 0.01:
                    continue
                # normal from the diagonals (world space), for shading
                u = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
                w = (d_[0] - b[0], d_[1] - b[1], d_[2] - b[2])
                nx, ny, nz = u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]
                ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
                vx, vy, vz = v(nx / ln, ny / ln, nz / ln)
                shade = 0.55 + 0.45 * abs(vx * light[0] + vy * light[1] - vz * light[2])
                col = tuple(min(255, round(ch * shade)) for ch in ramp(lv))
                faces.append(((pa[2] + pb[2] + pc[2] + pd[2]) / 4, col,
                              [(pa[0], pa[1]), (pb[0], pb[1]), (pc[0], pc[1]), (pd[0], pd[1])]))
        faces.sort(key=lambda fc: -fc[0])
        for _d, col, poly in faces:
            pygame.draw.polygon(surf, col, poly)
            pygame.draw.polygon(surf, tuple(ch * 3 // 4 for ch in col), poly, 1)
        # the antenna, drawn on top so it shows through
        if r.wires:
            xs = [q[0] for w_ in r.wires for q in w_]
            ys = [q[1] for w_ in r.wires for q in w_]
            zs = [q[2] for w_ in r.wires for q in w_]
            ext = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-6)
            k = 0.55 / ext
            mx_, my_ = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            mz = (max(zs) + min(zs)) / 2 if free else min(zs) - 0.08 / k
            for a, b in r.wires:
                pa = P((a[0] - mx_) * k, (a[1] - my_) * k, (a[2] - mz) * k)
                pb = P((b[0] - mx_) * k, (b[1] - my_) * k, (b[2] - mz) * k)
                pygame.draw.line(surf, (255, 255, 255), pa[:2], pb[:2], 2)
        surf.set_clip(None)
        # labels and scale
        surf.blit(tiny.render("front", True, AXIS), (fx + 2, fy - 7))
        info = f"{r.gain:.1f} dBi" if r.gain is not None else ""
        img = tiny.render(info, True, L.OK)
        surf.blit(img, (T.W - img.get_width() - 4, top))
        if r.takeoff is not None and not free:
            img = tiny.render(f"{r.takeoff:.0f}\u00b0 up", True, AXIS)
            surf.blit(img, (T.W - img.get_width() - 4, top + 14))
        # colour key
        kx, ky = T.W - 12, bot - 58
        for i in range(48):
            surf.fill(ramp(1 - i / 47), (kx, ky + i, 6, 1))
        for txt, yy in (("0", ky - 6), ("-30", ky + 42)):
            img = tiny.render(txt, True, AXIS)
            surf.blit(img, (kx - img.get_width() - 3, yy))
        surf.blit(tiny.render("dB", True, AXIS), (kx - 18, ky + 18))
        if self.spinning:
            surf.blit(tiny.render("spinning", True, L.WARN), (4, top))
