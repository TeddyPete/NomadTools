"""TNT Packet Capture: the app. Screens on the LCD, input from the keyboard."""
from __future__ import annotations

import os
import signal
import threading
import time

from . import capture as C
from . import files as F
from . import lcd as L
from . import netinfo, pcapread, web
from . import settings as S
from .keys import Keyboard
from .ui import BACK, DOWN, SELECT, UP, Busy, Confirm, Form, Menu, Message, Prompt, Screen, nav_key, wrap

APP_TITLE = "TNT Packet Capture"

HELP = (
    "Plug the Ethernet port into a switch mirror (SPAN) port to see other devices' traffic. "
    "On a normal port you only see broadcast, multicast and this device's own traffic.\n"
    "Pick a Filter, then Start capture. Live view shows counters and what's on the wire.\n"
    "Captures keep running if you leave the app, and always stop at their time/size limit "
    "or when the card is nearly full.\n"
    "Get files off: Share over network (open the address in a laptop browser), a USB drive, "
    "or scp from ~/TNT-Captures. Open them in Wireshark.\n"
    "TheTechNomad.com"
)


def hms(s: float) -> str:
    s = int(s or 0)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def rate(bps: float) -> str:
    if bps >= 1e6:
        return f"{bps / 1e6:.1f} Mb/s"
    return f"{bps / 1e3:.0f} kb/s"


class App:
    def __init__(self, panel: L.Panel, kb: Keyboard | None):
        self.panel, self.kb = panel, kb
        self.cfg = S.load()
        self.stack: list[Screen] = []
        self.dirty = True
        self.quit = False
        self.state: dict = C.read_state()
        self.share = web.Share()
        self.follower = pcapread.Follower()
        self._follow_file = None
        self._wake = threading.Event()

    # ---- stack ----
    def push(self, s: Screen) -> None:
        self.stack.append(s)
        self.dirty = True

    def pop(self, s: Screen | None = None) -> None:
        if s is None:
            if len(self.stack) > 1:
                self.stack.pop()
        elif s in self.stack:
            self.stack.remove(s)
        self.dirty = True

    def wake(self) -> None:
        self._wake.set()
        self.dirty = True

    @property
    def capturing(self) -> bool:
        return bool(self.state.get("running"))

    def badge(self) -> str:
        if self.capturing:
            return f"● REC {hms(self.state.get('elapsed', 0))}"
        return "WEB ON" if self.share.on else ""

    def run_task(self, title, label, fn, after=None):
        def done(result, error):
            if error is not None:
                self.push(Message(self, "Problem", str(error), L.BAD))
            elif after:
                after(result)
            elif result:
                self.push(Message(self, title, str(result), L.OK))
        self.push(Busy(self, title, label, fn, done))

    def save_cfg(self) -> None:
        try:
            S.save(self.cfg)
        except OSError as e:
            self.push(Message(self, "Problem", f"Could not save settings: {e}", L.BAD))

    # ---- capture ----
    def start_capture(self) -> None:
        if self.capturing:
            self.push(LiveView(self))
            return
        iface = self.cfg["iface"]
        link = netinfo.link(iface)

        def go():
            def started(job):
                self.follower.reset()
                self._follow_file = None
                self.state = C.read_state()
                self.push(LiveView(self))
            self.run_task("Start capture", "Starting", lambda: C.start(self.cfg), after=started)

        if link["exists"] and not link["up"]:
            self.push(Confirm(self, "No link", f"{iface} has no link (no cable or switch port off). "
                                               "Start anyway? It will capture once the link comes up.",
                              go, yes="OK start", no="ESC cancel"))
        else:
            go()

    def stop_capture(self) -> None:
        def done(st):
            self.state = st
            self.dirty = True
        self.run_task("Stop capture", "Stopping", C.stop, after=done)

    def poll(self) -> None:
        st = C.read_state()
        was = self.capturing
        self.state = st
        if st.get("running"):
            files = st.get("files") or []
            cur = files[-1] if files else None
            if cur != self._follow_file and cur:
                if self._follow_file is None:
                    self.follower.reset()
                self._follow_file = cur
            self.follower.poll(cur)
        elif was:
            self._follow_file = None
        self.dirty = True

    # ---- main loop ----
    def run(self) -> None:
        self.push(Home(self))
        last_draw = last_poll = 0.0
        while not self.quit:
            keys = self.kb.poll(0.1) if self.kb else (time.sleep(0.1) or [])
            for k in keys:
                if self.stack:
                    top = self.stack[-1]
                    top.key(k if top.text_entry else nav_key(k))
                self.dirty = True
            if not self.stack:
                break
            now = time.monotonic()
            if now - last_poll > 0.5:
                self.poll()
                last_poll = now
            self.stack[-1].tick()
            if self.dirty or now - last_draw > 1.0:
                self.draw()
                last_draw = now
                self.dirty = False

    def draw(self) -> None:
        if not self.stack:
            return
        s = self.stack[-1]
        rows, sel = s.rows()
        self.panel.draw(s.title, rows, s.hint, sel, s.right())


# ---------------------------------------------------------------------------

class Home(Menu):
    def __init__(self, app):
        self.app = app
        c = app.cfg
        items = [
            (lambda: "Stop capture" if app.capturing else "Start capture", self.start_stop,
             lambda: hms(app.state.get("elapsed", 0)) if app.capturing else f"{c['iface']} {netinfo.link_text(c['iface'])}",
             lambda: L.BAD if app.capturing else L.OK),
            ("Live view", lambda: app.push(LiveView(app)), lambda: "REC" if app.capturing else ""),
            ("Filter", lambda: app.push(FilterMenu(app)), lambda: C.PRESET[c["preset"]][2] +
             (" +" if c.get("host") or c.get("port") else "")),
            ("Settings", lambda: open_settings(app), lambda: limits_text(c)),
            ("Saved captures", lambda: app.push(FilesMenu(app)), lambda: str(len(F.listing()))),
            ("Share over network", lambda: app.push(ShareScreen(app)), lambda: "ON" if app.share.on else ""),
            ("Help", lambda: app.push(Message(app, "Help", HELP))),
        ]
        super().__init__(app, APP_TITLE, items, "↑↓ move  OK/→ open  ESC quit", numbered=True)

    @property
    def title(self):
        return "Packet Capture" if self.app.capturing else APP_TITLE

    @title.setter
    def title(self, v):
        pass

    def start_stop(self):
        if self.app.capturing:
            self.app.stop_capture()
        else:
            self.app.start_capture()

    def key(self, k):
        if k.name == "left":
            return
        if k.name == "esc":
            if self.app.capturing:
                self.app.push(LeaveMenu(self.app))
            else:
                self.app.quit = True
            return
        super().key(k)


class LeaveMenu(Menu):
    def __init__(self, app):
        def keep():
            app.quit = True

        def stop_quit():
            C.stop()
            app.quit = True
        super().__init__(app, "Capture running", [
            ("Keep capturing, quit app", keep),
            ("Stop capture and quit", stop_quit, "", L.BAD),
            ("Back to the app", lambda: app.pop(self)),
        ])


def limits_text(c: dict) -> str:
    d = c["duration"] if c["duration"] != "No limit" else ""
    s = ("ring " if c["mode"] == "Ring buffer" else "") + c["size"].replace(" ", "")
    return " ".join(x for x in (d.replace(" ", ""), s) if x)


class FilterMenu(Menu):
    def __init__(self, app):
        self.app = app
        items = []
        for key, label, short, expr, help_ in C.PRESETS:
            items.append((label, (lambda k=key: self.pick(k)),
                          (lambda k=key: "✓" if app.cfg["preset"] == k else ""),
                          (lambda k=key: L.OK if app.cfg["preset"] == k else L.FG)))
        items.append(("Host IP", self.host, lambda: app.cfg.get("host") or "any"))
        items.append(("Port", self.port, lambda: str(app.cfg.get("port") or "any")))
        super().__init__(app, "Filter", items, "↑↓ move  OK pick  ESC back")
        self.sel = next((i for i, p in enumerate(C.PRESETS) if p[0] == app.cfg["preset"]), 0)

    @property
    def hint(self):
        if self.sel < len(C.PRESETS):
            return C.PRESETS[self.sel][4]
        return "OK edit  ESC back"

    @hint.setter
    def hint(self, v):
        pass

    def pick(self, key):
        app = self.app
        if key == "custom":
            def done(v):
                v = v.strip()
                err = C.check_filter(v)
                if err:
                    app.push(Message(app, "Filter problem", err, L.BAD))
                    return
                app.cfg["custom"] = v
                app.cfg["preset"] = "custom" if v else "all"
                app.save_cfg()
            app.push(Prompt(app, "Custom filter", "Filter", app.cfg.get("custom", ""), done,
                            help_text="tcpdump syntax, e.g. udp port 5004 or host 10.0.0.5"))
            return
        app.cfg["preset"] = key
        app.save_cfg()
        app.pop(self)

    def host(self):
        app = self.app

        def done(v):
            v = v.strip()
            if v and not C.valid_ip(v):
                app.push(Message(app, "Host IP", f"'{v}' is not an IP address like 192.168.1.20", L.BAD))
                return
            app.cfg["host"] = v
            app.save_cfg()
        app.push(Prompt(app, "Host IP", "IP", app.cfg.get("host", ""), done,
                        help_text="Only packets to or from this IP. Blank = any."))

    def port(self):
        app = self.app

        def done(v):
            v = v.strip()
            if v and not (v.isdigit() and 0 < int(v) < 65536):
                app.push(Message(app, "Port", "Use a number from 1 to 65535.", L.BAD))
                return
            app.cfg["port"] = v
            app.save_cfg()
        app.push(Prompt(app, "Port", "Port", str(app.cfg.get("port", "")), done,
                        help_text="Only this TCP/UDP port (e.g. 41794 Crestron). Blank = any."))


def open_settings(app):
    c = app.cfg
    fields = [
        ("iface", "Capture port", "choice", netinfo.names()),
        ("tag", "Name tag", "text", "added to file names"),
        ("duration", "Stop after", "choice", C.DURATIONS),
        ("size", "Max size", "choice", C.SIZES),
        ("mode", "When full", "choice", ["Stop at limit", "Ring buffer"]),
        ("snap", "Save", "choice", ["Full packets", "Headers only"]),
        ("promisc", "Promiscuous", "bool"),
        ("host", "Host IP", "ip", "blank = any"),
        ("port", "Port", "number", "blank = any"),
        ("custom", "Custom filter", "text", "tcpdump syntax"),
    ]

    def validate(v):
        if v.get("host") and not C.valid_ip(v["host"]):
            return f"Host IP '{v['host']}' is not an IP address."
        if v.get("port") and not (str(v["port"]).isdigit() and 0 < int(v["port"]) < 65536):
            return "Port must be 1 to 65535."
        if v.get("custom"):
            err = C.check_filter(v["custom"])
            if err:
                return f"Custom filter: {err}"
        return None

    def save(v):
        c.update(v)
        if c["preset"] == "custom" and not c.get("custom"):
            c["preset"] = "all"
        app.save_cfg()

    form = Form(app, "Capture settings", fields, {k: c.get(k) for k, *_ in fields}, save, validate)
    for f in form.form.fields:
        if f.key in ("custom", "tag"):
            f.maxlen = 200 if f.key == "custom" else 24
    app.push(form)


class LiveView(Screen):
    title = "Live view"

    def __init__(self, app):
        super().__init__(app)
        self.top = 0

    @property
    def hint(self):
        return "OK stop  ↑↓ scroll  ESC back" if self.app.capturing else \
            "OK new capture  ↑↓ scroll  ESC back"

    def lines(self) -> list:
        a, st = self.app, self.app.state
        job = st.get("job") or {}
        out = []
        if not job:
            return [("No capture yet.", L.DIM), "", ("OK starts one with the", L.DIM),
                    (f"'{C.PRESET[a.cfg['preset']][1]}' filter.", L.DIM)]
        if st.get("running"):
            out.append((f"● REC {job.get('iface')}", L.BAD, hms(st.get("elapsed", 0))))
        else:
            why = st.get("error") or st.get("reason") or "stopped"
            out.append(("Stopped: " + why, L.BAD if st.get("error") else L.WARN))
        out.append(("Packets", L.FG, f"{st.get('packets', 0):,}"))
        size = F.nice_size(st.get("bytes", 0))
        if job.get("ring"):
            out.append(("Ring", L.FG, f"{size} of {job['max_mb']} MB"))
        else:
            out.append(("Size", L.FG, f"{size} of {job.get('max_mb')} MB"))
        if st.get("running"):
            bps = st.get("bps")
            out.append(("Rate", L.FG, f"{st.get('pps', 0):.0f} pkt/s" + (f"  {rate(bps)}" if bps is not None else "")))
        drops = st.get("drops", 0)
        out.append(("Dropped", L.WARN if drops else L.FG, f"{drops:,}"))
        out.append(("Filter", L.DIM, job.get("preset_name", "")[:18]))
        if job.get("seconds"):
            left = max(0, job["seconds"] - st.get("elapsed", 0))
            out.append(("Time left" if st.get("running") else "Time limit", L.DIM,
                        hms(left if st.get("running") else job["seconds"])))
        fl = a.follower
        if fl.seen:
            tot = sum(fl.protos.values()) or 1
            out.append(("Protocols" + (" (sample)" if fl.skipped else ""), L.WARN))
            for name, n in fl.protos.most_common(8):
                out.append((f"  {name}", L.FG, f"{n * 100 / tot:.0f}%  {n:,}"))
            if fl.talkers:
                out.append(("Top senders", L.WARN))
                for ip, n in fl.talkers.most_common(5):
                    out.append((f"  {ip}", L.FG, f"{n:,}"))
        files = st.get("files") or []
        if files and not st.get("running"):
            out.append(("Saved as", L.WARN))
            for f in files[-3:]:
                for l in wrap(a.panel, os.path.basename(f)):
                    out.append((l, L.DIM))
        if st.get("running") and job.get("filter") and st.get("packets", 0) == 0 and st.get("elapsed", 0) > 5:
            out.append(("No packets match yet.", L.DIM))
        return out

    def rows(self):
        ls = self.lines()
        n = L.Panel.ROWS
        self.top = max(0, min(self.top, len(ls) - n))
        return ls[self.top:self.top + n], None

    def key(self, k):
        if k.name in UP:
            self.top = max(0, self.top - 1)
        elif k.name in DOWN:
            self.top += 1
        elif k.name == "pagedown":
            self.top += L.Panel.ROWS
        elif k.name == "pageup":
            self.top = max(0, self.top - L.Panel.ROWS)
        elif k.name == "enter":
            if self.app.capturing:
                self.app.stop_capture()
            else:
                self.app.pop(self)
                self.app.start_capture()
        elif k.name in BACK:
            self.app.pop(self)

    def tick(self):
        if self.app.capturing:
            self.app.dirty = True


class FilesMenu(Menu):
    def __init__(self, app):
        self.app = app
        super().__init__(app, "Saved captures", [], "↑↓ move  OK open  ESC back")
        self.reload()

    def reload(self):
        app = self.app
        self.saved = F.listing()
        self.items = [(s.label(), (lambda s=s: app.push(FileInfo(app, s, self))), F.nice_size(s.size))
                      for s in self.saved]
        if self.saved:
            self.items.append(("Delete all captures", self.delete_all, "", L.BAD))
        else:
            self.items = [("No saved captures yet.", None, "", L.DIM)]
        self.sel = min(self.sel, len(self.items) - 1)
        self.app.dirty = True

    def right(self):
        return f"{C.free_mb() / 1000:.1f} GB free"

    def delete_all(self):
        total = F.nice_size(sum(s.size for s in self.saved))

        def yes():
            for s in self.saved:
                F.delete(s)
            self.reload()
        self.app.push(Confirm(self.app, "Delete all", f"Delete all {len(self.saved)} captures ({total})? "
                                                      "This can't be undone.", yes, yes="OK delete", no="ESC keep"))


class FileInfo(Menu):
    def __init__(self, app, s: F.Saved, parent: FilesMenu):
        self.app, self.s, self.parent = app, s, parent
        m = s.meta
        info = []
        if m.get("started"):
            info.append(("Started", L.DIM, time.strftime("%m-%d %H:%M:%S", time.localtime(m["started"]))))
        if m.get("seconds") is not None:
            info.append(("Length", L.DIM, hms(m["seconds"])))
        info.append(("Size", L.DIM, F.nice_size(s.size)))
        if m.get("packets") is not None:
            info.append(("Packets", L.DIM, f"{m['packets']:,}"))
        if m.get("drops"):
            info.append(("Dropped", L.WARN, f"{m['drops']:,}"))
        if m.get("preset"):
            info.append(("Filter", L.DIM, m["preset"][:18]))
        if m.get("iface"):
            info.append(("Port", L.DIM, m["iface"]))
        if m.get("reason"):
            info.append(("Ended by", L.DIM, m["reason"]))
        items = [("Summary (protocols)", self.summary)]
        for mnt in F.usb_drives():
            items.append((f"Copy to USB {os.path.basename(mnt)[:12]}", (lambda mnt=mnt: self.copy(mnt))))
        items.append(("Delete", self.delete, "", L.BAD))
        items += [(t, None, v, col) for t, col, v in info]
        items.append((s.name[:60], None, "", L.DIM))
        super().__init__(app, s.label(), items, "↑↓ move  OK open  ESC back")

    def summary(self):
        s = self.s

        def show(r):
            if not r.get("ok"):
                self.app.push(Message(self.app, "Summary", "Can't read this file.", L.BAD))
                return
            lines = [f"{r['packets']:,} packets" + ("" if r["complete"] else " (first 50 MB)")]
            if r["first"] and r["last"]:
                lines.append(f"{hms(r['last'] - r['first'])} long")
            tot = sum(n for _, n in r["protos"]) or 1
            lines.append("Protocols:")
            lines += [f"  {n * 100 / tot:3.0f}% {p}" for p, n in r["protos"]]
            if r["talkers"]:
                lines.append("Top senders:")
                lines += [f"  {ip} {n:,}" for ip, n in r["talkers"]]
            self.app.push(Message(self.app, "Summary", "\n".join(lines)))
        self.app.run_task("Summary", "Reading", lambda: pcapread.summarize(s.path), after=show)

    def copy(self, mnt):
        self.app.run_task("Copy to USB", "Copying", lambda: "Copied to " + F.copy_to(self.s, mnt))

    def delete(self):
        def yes():
            F.delete(self.s)
            self.app.pop(self)
            self.parent.reload()
        self.app.push(Confirm(self.app, "Delete", f"Delete {self.s.label()} ({F.nice_size(self.s.size)})?",
                              yes, yes="OK delete", no="ESC keep"))


class ShareScreen(Screen):
    title = "Share over network"

    def __init__(self, app):
        super().__init__(app)
        if not app.share.on:
            app.share.start()
        self.addrs = netinfo.addresses()
        self.t = time.monotonic()

    @property
    def hint(self):
        return ("OK turn off" if self.app.share.on else "OK turn on") + "  ESC back"

    def rows(self):
        sh = self.app.share
        if not sh.on:
            return [("Sharing is OFF", L.WARN), "",
                    ("OK shares saved captures as", L.DIM), ("a web page on this network.", L.DIM)], None
        out = [("Open in a laptop browser:", L.FG)]
        for ifc, ip in sorted(self.addrs.items()):
            out.append((f"http://{ip}:{sh.port}", L.OK, ifc))
        if not self.addrs:
            out.append(("No IP address yet", L.BAD))
        out.append(("Same network as this device.", L.DIM))
        out.append(("Stays on until you quit.", L.DIM))
        return out, None

    def key(self, k):
        if k.name == "enter":
            if self.app.share.on:
                self.app.share.stop()
            elif not self.app.share.start():
                self.app.push(Message(self.app, "Problem", self.app.share.error, L.BAD))
        elif k.name in BACK:
            self.app.pop(self)

    def tick(self):
        if time.monotonic() - self.t > 5:
            self.addrs = netinfo.addresses()
            self.t = time.monotonic()


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
        app.share.stop()
        msg = "Capture keeps running. Bye!" if C.running() else "Bye!"
        panel.draw(APP_TITLE, [(msg, L.OK)], "")
        kb.close()
    return 0
