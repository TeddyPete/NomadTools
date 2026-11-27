"""Nomad Label Scanner: the screens on the 320x170 LCD.

Home > Scan a label (live camera, barcodes read as you aim, OK takes the
shot and reads the printed text) > the item (edit, find on network, save)
> back to the camera for the next label. Items collect in the current job;
Export gives Excel + CSV through a QR web page or a USB stick.
"""
from __future__ import annotations

import os
import signal
import threading
import time

import pygame

from . import camera as C
from . import decode, export, netfind, oui, parse, share, store
from . import lcd as L
from . import nomadui as T
from . import qr
from .keys import Keyboard
from .nomadui import BACK, DOWN, SELECT, UP, EditList, Field, RowView
from .ui import Busy, Confirm, Form, Message, Prompt, Screen, nav_key

APP_TITLE = "Nomad Label Scanner"

HELP_MAIN = ("Scan gear labels with the camera. Barcodes and QR codes are read as you aim; "
             "OK takes a shot and also reads the printed text (MAC, IP, serial, model). "
             "Each scan becomes an item in the current job. Export the job as Excel or CSV "
             "from the QR web page or to a USB stick.")
HELP_SCAN = ("Hold the label 10-20 cm from the camera (the lens is fixed focus: too close is blurry). "
             "Codes found so far show at the top. OK or 4 takes the shot and reads the label; "
             "5 zooms 2x for small stickers; 6 turns text reading (OCR) on/off; 7 flips the picture.")
HELP_ITEM = ("Check what was read. OK or Right on a line edits it (red), OK saves the edit. "
             "4 saves the item. 5 finds it on the network: by MAC it sweeps the local subnet, "
             "by IP it pings. 6 lists every code found so you can put one in another field. "
             "7 shows the label photo.")
HELP_LIST = "Every item in this job. OK opens one. 5 checks which ones are on the network now."


class App:
    def __init__(self, panel: L.Panel, kb: Keyboard | None):
        self.panel, self.kb = panel, kb
        self.cfg = store.load_settings()
        store.create(self.job)
        self.items: list[store.Item] = store.load(self.job)
        self.cam = C.Camera(int(self.cfg.get("rotation", 0)), int(self.cfg.get("zoom", 1)))
        self.cam.on_frame = self.wake
        self.share = share.Share()
        self.stack: list[Screen] = []
        self.helpview = None
        self.dirty = True
        self.quit = False
        self._flash = ("", L.FG, 0.0)

    # ---- data ----
    @property
    def job(self) -> str:
        return self.cfg.get("job") or "Job 1"

    def set_job(self, job: str) -> None:
        self.cfg["job"] = job
        store.save_settings(self.cfg)
        store.create(job)
        self.items = store.load(job)

    def save_items(self) -> None:
        store.save(self.job, self.items)

    def save_cfg(self) -> None:
        store.save_settings(self.cfg)

    # ---- stack ----
    def push(self, s: Screen) -> None:
        self.stack.append(s)
        self.dirty = True

    def pop(self, s: Screen | None = None) -> None:
        if s is None:
            if len(self.stack) > 1:
                self.stack.pop()
            else:
                self.quit = True
        elif s in self.stack:
            self.stack.remove(s)
        self.dirty = True

    def wake(self) -> None:
        self.dirty = True

    def flash(self, text: str, color=L.OK, secs: float = 3.0) -> None:
        self._flash = (text, color, time.monotonic() + secs)
        self.dirty = True

    def flash_line(self):
        text, color, until = self._flash
        return (text, color) if text and time.monotonic() < until else None

    def task(self, title, label, fn, done):
        def finish(result, error):
            if error is not None:
                self.push(Message(self, "Problem", str(error), L.BAD))
            else:
                done(result)
        self.push(Busy(self, title, label, fn, finish))

    # ---- main loop ----
    def run(self) -> None:
        self.push(Home(self))
        last_draw = 0.0
        while not self.quit:
            keys = self.kb.poll(0.04) if self.kb else (time.sleep(0.04) or [])
            for k in keys:
                if self.stack:
                    self.dispatch(k)
                self.dirty = True
            if self.stack:
                self.stack[-1].tick()
            now = time.monotonic()
            if self.dirty or now - last_draw > 1.0:
                self.draw()
                last_draw = now
                self.dirty = False
        self.cam.stop()
        self.share.stop()

    def dispatch(self, k) -> None:
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

    def draw(self) -> None:
        if not self.stack:
            return
        if self.helpview is not None:
            self.helpview.render(self.panel.surf, self.panel.fonts)
            self.panel.flush()
            return
        s = self.stack[-1]
        if hasattr(s, "paint"):
            s.paint(self.panel.surf)
            self.panel.flush()
            return
        rows, sel = s.rows()
        fl = self.flash_line()
        if fl and not s.keybar():
            self.panel.draw(s.title, rows, fl[0], sel, s.right(), None)
            return
        self.panel.draw(s.title, rows, s.hint, sel, s.right(), s.keybar())


# ---------------------------------------------------------------------------

class List(Screen):
    """Menu with optional non-selectable lines at the top.
    items: (label, action, right, color) where any of them may be callable."""
    hint = "↑↓ move  OK/→ open  ESC back"

    def __init__(self, app, title=""):
        super().__init__(app)
        if title:
            self.title = title
        self.sel = 0
        self.top = 0

    def items(self) -> list:
        return []

    def header(self) -> list:
        return []

    def rows(self):
        head = self.header()
        its = self.items()
        n = max(1, self.nrows - len(head))
        if its:
            self.sel = max(0, min(self.sel, len(its) - 1))
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + n:
            self.top = self.sel - n + 1
        self.top = max(0, min(self.top, max(0, len(its) - n)))
        out = list(head)
        for it in its[self.top:self.top + n]:
            ev = [x() if callable(x) and i != 1 else x for i, x in enumerate(it)]
            label, right = ev[0], ev[2] if len(ev) > 2 else ""
            color = ev[3] if len(ev) > 3 and ev[3] else L.FG
            out.append((label, color, right or ""))
        return out, (len(head) + self.sel - self.top) if its else None

    def key(self, k):
        its = self.items()
        if k.name in UP and its:
            self.sel = (self.sel - 1) % len(its)
        elif k.name in DOWN and its:
            self.sel = (self.sel + 1) % len(its)
        elif k.name == "pageup":
            self.sel = max(0, self.sel - self.nrows)
        elif k.name == "pagedown" and its:
            self.sel = min(len(its) - 1, self.sel + self.nrows)
        elif k.name in SELECT and its:
            act = its[self.sel][1]
            if act:
                act()
        elif k.name in BACK:
            self.app.pop(self)


class Home(List):
    title = APP_TITLE

    def items(self):
        a = self.app
        return [
            ("Scan a label", lambda: open_scan(a), "", L.OK),
            ("Inventory", lambda: a.push(Inventory(a)), f"{len(a.items)} items"),
            ("Job", lambda: a.push(Jobs(a)), a.job),
            ("Export & download", lambda: a.push(ExportMenu(a)), "Excel/CSV"),
            ("Settings", lambda: open_settings(a)),
            ("About", lambda: a.push(Message(a, "About", ABOUT))),
        ]

    def softkeys(self):
        a = self.app
        return [("Scan", lambda: open_scan(a)), ("Items", lambda: a.push(Inventory(a))),
                ("Jobs", lambda: a.push(Jobs(a))), ("Share", lambda: a.push(ShareScreen(a))), None]

    def key(self, k):
        if k.name in BACK:
            self.app.pop()
        else:
            super().key(k)


ABOUT = ("Nomad Label Scanner 0.1 by Tech Nomad Ted, TheTechNomad.com. "
         "Reads barcodes and QR codes (zbar) and label text (tesseract OCR) on the device; "
         "nothing leaves it unless you turn on the download page. "
         "Scans are in ~/Nomad-Label-Scans.")


# ---------------------------------------------------------------- camera

def open_scan(app):
    if not C.available():
        app.push(Message(app, "No camera program", "rpicam-vid is missing. Install rpicam-apps.", L.BAD))
        return
    app.push(ScanScreen(app))


class ScanScreen(Screen):
    title = "Scan"
    help = HELP_SCAN
    LIVE_SECS = 4.0

    def __init__(self, app):
        super().__init__(app)
        self.live: dict[str, tuple[str, float]] = {}   # data -> (symbology, last seen)
        self.decoding = False
        self.last_seq = 0
        self.sharp = 0.0
        self.bright = 128.0
        self.paused = False
        self.started = time.monotonic()
        self.app.cam.rotation = int(app.cfg.get("rotation", 0))
        self.app.cam.zoom = int(app.cfg.get("zoom", 1))
        self.app.cam.start()

    def softkeys(self):
        a = self.app
        return [("Shot", self.capture),
                (lambda: "Zoom 1x" if int(a.cfg.get("zoom", 1)) == 2 else "Zoom 2x", self.toggle_zoom),
                (lambda: "Text on" if not a.cfg.get("ocr") else "Text off", self.toggle_ocr),
                ("Flip", self.flip), ("Done", lambda: self.leave())]

    def leave(self):
        self.app.cam.stop()
        self.app.pop(self)

    def toggle_zoom(self):
        a = self.app
        a.cfg["zoom"] = 1 if int(a.cfg.get("zoom", 1)) == 2 else 2
        a.save_cfg()
        a.cam.zoom = a.cfg["zoom"]
        a.cam.restart()
        a.flash(f"Zoom {a.cfg['zoom']}x")

    def toggle_ocr(self):
        a = self.app
        a.cfg["ocr"] = not a.cfg.get("ocr")
        a.save_cfg()
        a.flash("Text reading " + ("on" if a.cfg["ocr"] else "off (barcodes only)"))

    def flip(self):
        a = self.app
        a.cfg["rotation"] = 0 if int(a.cfg.get("rotation", 0)) == 180 else 180
        a.save_cfg()
        a.cam.rotation = a.cfg["rotation"]
        a.cam.restart()

    def recent_codes(self) -> list[tuple[str, str]]:
        now = time.monotonic()
        return [(sym, d) for d, (sym, t) in self.live.items() if now - t < self.LIVE_SECS]

    def tick(self):
        cam = self.app.cam
        if self.paused:
            return
        if not cam.running and not cam.error:
            cam.start()
        f = cam.latest()
        if f and f.seq != self.last_seq and not self.decoding:
            self.last_seq = f.seq
            self.decoding = True
            threading.Thread(target=self._decode, args=(f,), daemon=True).start()

    def _decode(self, f):
        try:
            y = f.y
            if f.seq % 3 == 0:
                self.sharp = decode.sharpness(y)
                self.bright = float(y[::8, ::8].mean())
            for sym, data in decode.barcodes(y):
                new = data not in self.live
                self.live[data] = (sym, time.monotonic())
                if new:
                    self.app.wake()
        except Exception:  # noqa: BLE001 - never stop the preview over one bad frame
            pass
        finally:
            self.decoding = False

    def capture(self):
        cam = self.app.cam
        f = cam.latest()
        if not f:
            if cam.error:
                cam.error = ""
                cam.restart()
            return
        codes = self.recent_codes()
        a = self.app
        self.paused = True
        cam.stop()                     # frees memory for OCR
        do_ocr = bool(a.cfg.get("ocr")) and decode.have_ocr()

        def work():
            found_codes = decode.barcodes(f.y)
            for c in codes:
                if c[1] not in [x[1] for x in found_codes]:
                    found_codes.append(c)
            text = decode.ocr(f.y) if do_ocr else ""
            found = parse.extract(found_codes, text)
            item = store.Item(model=found.model, serial=found.serial, mac=found.mac, ip=found.ip,
                              room=a.cfg.get("room", ""), codes=[d for _, d in found_codes])
            item.vendor = oui.vendor(item.mac) if item.mac else ""
            if a.cfg.get("photo", True):
                name = time.strftime("%Y%m%d-%H%M%S") + f"-{item.id}.jpg"
                p = store.photo_path(a.job, name)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                f.rgb_image(1024).save(p, quality=82)
                item.photo = name
            if a.cfg.get("auto_find") and (item.mac or item.ip):
                apply_check(item, netfind.check(item.mac, item.ip))
            return item, found, text

        def finish(r, error):
            self.paused = False
            self.live.clear()
            if error is not None:
                a.push(Message(a, "Problem", str(error), L.BAD))
                return
            item, found, text = r
            a.push(ItemScreen(a, item, found=found, ocr_text=text))

        a.push(Busy(a, "Reading label", "Reading the label" if do_ocr else "Reading codes", work, finish))

    def key(self, k):
        if k.name == "enter":
            self.capture()
        elif k.name in BACK:
            self.leave()

    def paint(self, surf):
        f = self.app.panel.fonts
        cam = self.app.cam
        fr = cam.latest()
        if fr and not self.paused:
            try:
                pygame.surfarray.blit_array(surf, C.preview(fr))
            except (ValueError, TypeError):
                surf.fill(T.BG)
        else:
            surf.fill(T.BG)
            msg = cam.error or ("Starting camera..." if not self.paused else "")
            if msg:
                for i, line in enumerate(T.wrap_text(f["small"], msg, 300)[:3]):
                    surf.blit(f["small"].render(line, True, T.BAD if cam.error else T.DIM), (10, 50 + i * 18))
                if cam.error:
                    surf.blit(f["small"].render("OK to try again", True, T.DIM), (10, 110))
        # viewfinder brackets
        c, L_, x0, y0, x1, y1 = (255, 255, 255), 18, 30, 30, 290, 132
        for (x, y, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            surf.fill(c, (min(x, x + sx * L_), y - (2 if sy < 0 else 0), L_, 2))
            surf.fill(c, (x - (2 if sx < 0 else 0), min(y, y + sy * L_), 2, L_))
        # top strip: what was read, or how to aim
        strip = pygame.Surface((320, 22), pygame.SRCALPHA)
        strip.fill((0, 0, 0, 170))
        surf.blit(strip, (0, 0))
        codes = self.recent_codes()
        fl = self.app.flash_line()
        if fl:
            text, color = fl
        elif codes:
            fd = parse.extract(codes)
            parts = [f"{lab} {v}" for lab, v in (("S/N", fd.serial), ("MAC", fd.mac), ("IP", fd.ip),
                                                   ("Model", fd.model)) if v]
            parts += [v for _, v in fd.others]
            text = f"{len(codes)} code{'s' if len(codes) > 1 else ''}: " + "  ".join(parts)
            color = T.OK
        elif fr and self.bright < 18 and time.monotonic() - self.started > 3:
            text, color = "Too dark: more light on the label", T.WARN
        elif fr and self.sharp and self.sharp < 25 and time.monotonic() - self.started > 3:
            text, color = "Blurry: move back to 15-20 cm", T.WARN
        else:
            text, color = "Aim at the label, OK = shot", (230, 235, 245)
        surf.blit(f["small"].render(text, True, color), (5, 3), (0, 0, 250, 22))
        tags = []
        if int(self.app.cfg.get("zoom", 1)) == 2:
            tags.append("2x")
        tags.append("TXT" if self.app.cfg.get("ocr") else "BAR")
        tag = f["tiny"].render(" ".join(tags), True, T.HINT_FG)
        surf.blit(tag, (316 - tag.get_width(), 5))
        T.draw_keybar(surf, self.keybar(), f)


# ---------------------------------------------------------------- one item

def apply_check(item: store.Item, r: dict) -> None:
    if r.get("ip") and (not item.ip or r.get("online")):
        item.ip = r["ip"]
    if r.get("mac") and not item.mac:
        item.mac = r["mac"]
        item.vendor = oui.vendor(item.mac)
    item.online = r.get("text", "")
    item.checked = time.strftime("%Y-%m-%d %H:%M")


FIELDS = [("name", "Device"), ("model", "Model"), ("serial", "Serial"), ("mac", "MAC"),
          ("vendor", "Vendor"), ("ip", "IP"), ("room", "Room"), ("notes", "Notes")]


class ItemScreen(Screen):
    help = HELP_ITEM

    def __init__(self, app, item: store.Item, index: int | None = None, found: parse.Found | None = None,
                 ocr_text: str = ""):
        super().__init__(app)
        self.item, self.index, self.found, self.ocr_text = item, index, found, ocr_text
        self.title = "New scan" if index is None else f"Item {index + 1}"
        fields = [Field(k, lab, "ip" if k == "ip" else "text", maxlen=80) for k, lab in FIELDS]
        fields.append(Field("online", "Network", "info"))
        fields += [Field("save", "Save", "action"), Field("find", "Find on network", "action"),
                   Field("codes", "Codes found", "action"), Field("photo", "Label photo", "action")]
        if index is not None:
            fields.append(Field("delete", "Delete item", "action", color=T.BAD))
        vals = {k: getattr(item, k) for k, _ in FIELDS}
        vals["online"] = item.online or "-"
        self.form = EditList(fields, vals)
        self.dirty_item = index is None

    @property
    def text_entry(self):
        return self.form.editing

    @property
    def hint(self):
        return self.form.hint()

    def right(self):
        n = len(self.candidates())
        return f"{n} codes" if n else ""

    def candidates(self):
        out = list(self.found.candidates()) if self.found else []
        for c in self.item.codes:
            if c not in [v for _, v in out]:
                out.append(("code", c))
        return out

    def softkeys(self):
        return [("Save", self.save), ("Find", self.find), ("Codes", self.codes), ("Photo", self.photo),
                ("Delete", self.delete) if self.index is not None else ("Discard", self.discard)]

    def rows(self):
        return self.form.view(self.nrows), None

    def sync(self):
        for k, _ in FIELDS:
            setattr(self.item, k, self.form.values.get(k, ""))

    def set(self, key: str, value: str):
        self.form.values[key] = value
        if key == "mac":
            m = parse.norm_mac(value)
            if m:
                self.form.values["mac"] = m
                v = oui.vendor(m)
                if v:
                    self.form.values["vendor"] = v
        self.dirty_item = True

    def save(self):
        self.sync()
        a = self.app
        if self.index is None:
            a.items.append(self.item)
            n = len(a.items)
        else:
            a.items[self.index] = self.item
            n = self.index + 1
        a.save_items()
        if self.item.room != a.cfg.get("room", "") and self.item.room:
            a.cfg["room"] = self.item.room     # next scans default to this room
            a.save_cfg()
        a.pop(self)
        a.flash(f"Saved item {n}: {self.item.title[:26]}")

    def discard(self):
        if self.item.photo:
            try:
                os.unlink(store.photo_path(self.app.job, self.item.photo))
            except OSError:
                pass
        self.app.pop(self)
        self.app.flash("Scan discarded", L.WARN)

    def delete(self):
        def go():
            a = self.app
            it = a.items.pop(self.index)
            if it.photo:
                try:
                    os.unlink(store.photo_path(a.job, it.photo))
                except OSError:
                    pass
            a.save_items()
            a.pop(self)
            a.flash("Item deleted", L.WARN)
        self.app.push(Confirm(self.app, "Delete item?", f"Delete {self.item.title}? This can't be undone.", go))

    def find(self):
        self.sync()
        it = self.item
        if not it.mac and not it.ip:
            self.app.push(Message(self.app, "Find on network", "No MAC or IP on this item yet. "
                                  "Type one in, or pick one from Codes.", L.WARN))
            return

        def work():
            return netfind.check(it.mac, it.ip)

        def done(r):
            apply_check(it, r)
            for k in ("ip", "mac", "vendor"):
                self.form.values[k] = getattr(it, k)
            self.form.values["online"] = it.online
            self.dirty_item = True
            lines = [it.online or "no result"]
            if r.get("ip"):
                lines.append(f"IP {r['ip']}" + (f" on {r['iface']}" if r.get("iface") else ""))
            if r.get("host"):
                lines.append(f"Name {r['host']}")
            if r.get("mac"):
                lines.append(f"MAC {r['mac']}")
            self.app.push(Message(self.app, "Network", "\n".join(lines), L.OK if r.get("online") else L.WARN))

        self.app.task("Find on network", "Looking for it", work, done)

    def codes(self):
        c = self.candidates()
        if not c and not self.ocr_text:
            self.app.push(Message(self.app, "Codes found", "No barcodes or text were read from this label.", L.WARN))
            return
        self.app.push(CodesScreen(self.app, self, c))

    def photo(self):
        if not self.item.photo:
            self.app.push(Message(self.app, "Label photo", "No photo saved for this item "
                                  "(Settings: Keep label photos).", L.WARN))
            return
        self.app.push(PhotoScreen(self.app, store.photo_path(self.app.job, self.item.photo)))

    def leave(self):
        self.sync()
        if self.index is None:
            conf = Confirm(self.app, "Save this scan?", f"{self.item.title}\nOK saves it, ESC throws it away.",
                           self.save, yes="OK save", no="ESC discard")
            orig = conf.key

            def k2(kk, conf=conf, orig=orig):
                if kk.name in BACK or kk.char in ("n", "N"):
                    self.app.pop(conf)
                    self.discard()
                else:
                    orig(kk)
            conf.key = k2
            self.app.push(conf)
        elif self.form.changed or self.dirty_item:
            conf = Confirm(self.app, "Unsaved changes", "Save your changes?", self.save,
                           yes="OK save", no="ESC discard")
            orig = conf.key

            def k3(kk, conf=conf, orig=orig):
                if kk.name in BACK or kk.char in ("n", "N"):
                    self.app.pop(conf)
                    self.app.pop(self)
                else:
                    orig(kk)
            conf.key = k3
            self.app.push(conf)
        else:
            self.app.pop(self)

    def key(self, k):
        ev = self.form.handle(k)
        if ev and ev.startswith("changed:"):
            key = ev.split(":", 1)[1]
            self.set(key, self.form.values[key])
        elif ev and ev.startswith("action:"):
            {"save": self.save, "find": self.find, "codes": self.codes, "photo": self.photo,
             "delete": self.delete}.get(ev[7:], lambda: None)()
        elif ev == "back":
            self.leave()


class CodesScreen(List):
    title = "Codes found"
    help = "Everything read from the label. OK puts the highlighted value into a field of the item."

    def __init__(self, app, item_screen: ItemScreen, cands: list):
        super().__init__(app)
        self.its, self.cands = item_screen, cands
        if item_screen.ocr_text:
            self.cands = cands + [("text", "(all label text)")]

    def items(self):
        names = {"mac": "MAC", "ip": "IP", "serial": "Serial", "model": "Model", "code": "Code",
                 "text": "Text", "url": "Link"}
        out = []
        for kind, v in self.cands:
            if v == "(all label text)":
                out.append(("Show all label text", self.show_text, "", L.DIM))
            else:
                out.append((v, lambda v=v: self.pick(v), names.get(kind, kind)))
        return out

    def show_text(self):
        self.app.push(Message(self.app, "Label text (OCR)", self.its.ocr_text.strip() or "(none)"))

    def pick(self, value: str):
        def put(key):
            self.its.set(key, value)
            self.app.pop(chooser)
            self.app.pop(self)
            self.app.flash(f"{dict(FIELDS)[key]} set")
        chooser = List(self.app, "Put it in")
        chooser.items = lambda: [(lab, (lambda k=k: put(k))) for k, lab in FIELDS if k != "vendor"]
        self.app.push(chooser)


class PhotoScreen(Screen):
    title = "Label photo"

    def __init__(self, app, path: str):
        super().__init__(app)
        try:
            img = pygame.image.load(path)
            w, h = img.get_size()
            s = min(320 / w, 170 / h)
            self.img = pygame.transform.smoothscale(img, (int(w * s), int(h * s)))
        except (pygame.error, OSError, FileNotFoundError):
            self.img = None

    def paint(self, surf):
        surf.fill((0, 0, 0))
        if self.img:
            surf.blit(self.img, ((320 - self.img.get_width()) // 2, (170 - self.img.get_height()) // 2))
        else:
            surf.blit(self.app.panel.fonts["small"].render("Photo not found.", True, T.BAD), (10, 70))

    def key(self, k):
        if k.name in BACK | SELECT:
            self.app.pop(self)


# ---------------------------------------------------------------- lists

class Inventory(List):
    help = HELP_LIST

    @property
    def title(self):
        return f"{self.app.job}"

    def right(self):
        return f"{len(self.app.items)}"

    def items(self):
        a = self.app
        out = []
        for i, it in enumerate(a.items):
            right = it.serial or it.mac or it.ip
            color = T.OK if it.online.startswith("online") else (T.WARN if it.online and it.online != "-" else L.FG)
            out.append((f"{i + 1} {it.name or it.model or it.serial or it.mac or '(blank)'}",
                        (lambda i=i: a.push(ItemScreen(a, store.Item.from_dict(vars(a.items[i]).copy()), i))),
                        right[-12:], color))
        if not out:
            out.append(("No items yet. 4 = scan", lambda: open_scan(a), "", L.DIM))
        return out

    def softkeys(self):
        a = self.app
        return [("Scan", lambda: open_scan(a)), ("Check", self.check_all), None,
                ("Share", lambda: a.push(ShareScreen(a))), None]

    def check_all(self):
        a = self.app
        if not a.items:
            return

        def work():
            seen = netfind.sweep()
            by_ip = {ip: mac for mac, (ip, _) in seen.items()}
            on = 0
            for it in a.items:
                m = parse.norm_mac(it.mac)
                if m and m in seen:
                    ip, iface = seen[m]
                    ok, t = netfind.ping(ip, 1)
                    apply_check(it, {"ip": ip, "online": True, "text": f"online {t}" if ok else "online"})
                    on += 1
                elif it.ip:
                    ok, t = netfind.ping(it.ip, 1)
                    apply_check(it, {"ip": it.ip, "online": ok, "mac": by_ip.get(it.ip, ""),
                                     "text": f"online {t}" if ok else "no reply"})
                    on += ok
                elif m:
                    apply_check(it, {"text": "not found"})
            a.save_items()
            return on, sum(1 for it in a.items if it.mac or it.ip)

        def done(r):
            on, n = r
            a.push(Message(a, "Network check", f"{on} of {n} items with a MAC or IP are on the network now.\n"
                           "Green = online. Details are on each item and in the export.", L.OK))
        a.task("Network check", "Sweeping the network", work, done)


class Jobs(List):
    title = "Jobs"
    help = "A job is one inventory (a site, a room, a rack). OK switches to it. 4 starts a new job."

    def items(self):
        a = self.app
        js = store.jobs()
        if a.job not in js:
            js.insert(0, a.job)
        out = [(j, (lambda j=j: self.switch(j)), "current" if j == a.job else f"{len(store.load(j))}",
                T.OK if j == a.job else None) for j in js]
        out.append(("[ New job ]", self.new, "", T.OK))
        return out

    def switch(self, j):
        self.app.set_job(j)
        self.app.pop(self)
        self.app.flash(f"Job: {j}")

    def new(self):
        a = self.app
        n = len(store.jobs()) + 1

        def made(name):
            name = name.strip()
            if not name:
                return
            if name in store.jobs():
                a.push(Message(a, "New job", f"There is already a job called {name}.", L.WARN))
                return
            self.switch(name)
        a.push(Prompt(a, "New job", "Name", time.strftime("%Y-%m-%d ") + f"Job {n}", made,
                      help_text="Site or room name, for example Hotel Ballroom."))

    def current_job(self):
        its = self.items()
        if self.sel >= len(its) - 1:
            return None
        return its[self.sel][0]

    def rename(self):
        j = self.current_job()
        if not j:
            return
        a = self.app

        def done(name):
            name = name.strip()
            if not name or name == j:
                return
            if not store.rename(j, name):
                a.push(Message(a, "Rename", f"There is already a job called {name}.", L.WARN))
                return
            if a.job == j:
                a.set_job(name)
        a.push(Prompt(a, "Rename job", "Name", j, done))

    def delete(self):
        j = self.current_job()
        if not j:
            return
        a = self.app

        def go():
            store.delete(j)
            if a.job == j:
                rest = store.jobs()
                a.set_job(rest[0] if rest else "Job 1")
            a.flash(f"Deleted {j}", L.WARN)
        n = len(store.load(j))
        a.push(Confirm(a, "Delete job?", f"Delete {j} and its {n} items and photos? This can't be undone.", go))

    def softkeys(self):
        return [("New", self.new), ("Rename", self.rename), ("Delete", self.delete), None, None]


# ---------------------------------------------------------------- export

class ExportMenu(List):
    title = "Export & download"
    help = ("Excel (.xlsx) and CSV for each job. The web page shows a QR code: scan it with a phone "
            "or laptop on the same network and tap a file. Or copy everything to a USB stick.")

    def items(self):
        a = self.app
        return [("Web page + QR code", lambda: a.push(ShareScreen(a)), "on" if a.share.on else ""),
                ("Copy all to USB stick", self.usb),
                ("Save Excel + CSV on device", self.save_now)]

    def usb(self):
        self.app.task("Copy to USB", "Copying", share.copy_all,
                      lambda r: self.app.push(Message(self.app, "Copy to USB", r, L.OK)))

    def save_now(self):
        a = self.app

        def work():
            paths = export.export_job(a.job)
            allp = export.export_all()
            return paths + [allp]

        def done(paths):
            rel = [os.path.relpath(p, os.path.expanduser("~")) for p in paths]
            a.push(Message(a, "Saved", "In your home folder:\n" + "\n".join(rel), L.OK))
        a.task("Export", "Writing files", work, done)


class ShareScreen(Screen):
    title = "Download"
    help = ("While this is on, any phone or laptop on the same network can open the page and download "
            "each job as Excel or CSV (and a zip with the photos). OK turns it off. F/X picks another address.")

    def __init__(self, app):
        super().__init__(app)
        if not app.share.on:
            app.share.start()
        self.pick = 0

    def addrs(self):
        return [(ifc, ip) for ifc, ip, _ in sorted(netfind.local_nets(), key=lambda a: (not a[0].startswith("wl"), a[0]))]

    def softkeys(self):
        a = self.app
        return [(lambda: "Turn off" if a.share.on else "Turn on", self.toggle), None, None, None, None]

    def toggle(self):
        a = self.app
        if a.share.on:
            a.share.stop()
        elif not a.share.start():
            a.flash(a.share.error or "Couldn't start the web page.", L.BAD)

    def key(self, k):
        if k.name == "enter":
            self.toggle()
        elif k.name in UP:
            self.pick -= 1
        elif k.name in DOWN:
            self.pick += 1
        elif k.name in BACK:
            self.app.pop(self)

    def paint(self, surf):
        f = self.app.panel.fonts
        a = self.app
        surf.fill(T.BG)
        surf.fill(T.TITLE_BG, (0, 0, 320, T.TITLE_H))
        img = T.title_image("Download Excel / CSV", f=f)
        surf.blit(img, (6, (T.TITLE_H - img.get_height()) // 2))
        y = T.TITLE_H + 6
        if not a.share.on:
            for i, (t, c) in enumerate([("Web page is OFF", T.WARN), ("4 or OK turns it on.", T.DIM)]):
                surf.blit(f["row"].render(t, True, c), (8, y + i * 22))
        else:
            ad = self.addrs()
            if not ad:
                surf.blit(f["row"].render("No network address.", True, T.BAD), (8, y))
                surf.blit(f["small"].render("Join Wi-Fi or plug in a cable.", True, T.DIM), (8, y + 24))
            else:
                ifc, ip = ad[self.pick % len(ad)]
                url = f"http://{ip}:{a.share.port}/"
                qr.draw(surf, url, 4, y - 2, 110)
                x = 122
                lines = [("Scan with a phone", T.DIM, "small"), (ip, T.OK, "row"), (f":{a.share.port}  {ifc}", T.OK, "small"),
                         ("Tap Excel or CSV", T.DIM, "small"), (f"{len(store.jobs())} job(s)", T.DIM, "small")]
                if len(ad) > 1:
                    lines.append(("F/X: other address", T.HINT_FG, "tiny"))
                yy = y
                for t, c, fn in lines:
                    surf.blit(f[fn].render(t, True, c), (x, yy))
                    yy += 22 if fn == "row" else 18
        T.draw_keybar(surf, self.keybar(), f)


# ---------------------------------------------------------------- settings

def open_settings(app):
    c = app.cfg
    fields = [
        ("ocr", "Read label text", "bool"),
        ("photo", "Keep label photos", "bool"),
        ("auto_find", "Find on network", "bool", ("After scan", "Off")),
        ("room", "Room (next scans)", "text"),
        ("zoom", "Camera zoom", "choice", ["1x", "2x"]),
        ("rotation", "Picture", "choice", ["Normal", "Upside down"]),
    ]
    vals = {"ocr": bool(c.get("ocr")), "photo": bool(c.get("photo", True)), "auto_find": bool(c.get("auto_find")),
            "room": c.get("room", ""), "zoom": f"{int(c.get('zoom', 1))}x",
            "rotation": "Upside down" if int(c.get("rotation", 0)) == 180 else "Normal"}

    def save(v):
        c.update(ocr=v["ocr"], photo=v["photo"], auto_find=v["auto_find"], room=v["room"],
                 zoom=2 if v["zoom"] == "2x" else 1, rotation=180 if v["rotation"] == "Upside down" else 0)
        app.save_cfg()
        app.flash("Settings saved")
    app.push(Form(app, "Settings", fields, vals, save))


def main_ui() -> int:
    panel = L.Panel()
    kb = Keyboard()
    app = App(panel, kb)

    def on_term(*_):
        app.quit = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGHUP, on_term)
    try:
        if not kb.ok:
            panel.draw(APP_TITLE, [("No keyboard found.", L.BAD)], "")
            time.sleep(4)
            return 1
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.cam.stop()
        panel.draw(APP_TITLE, [("Bye!", L.OK)], "")
        kb.close()
    return 0
