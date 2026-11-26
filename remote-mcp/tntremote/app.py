"""TNT Remote: the app on the CardputerZero's own screen and keyboard.

Turns remote access on and off, shows the pairing code that approves a new
Claude connection, shows what Claude is doing, and holds the permission
switches (including Admin / sudo).
"""
from __future__ import annotations

import signal
import textwrap
import threading
import time

from . import __version__, config as C, control, oauth
from . import lcd as L
from . import tntui as T
from .keys import Keyboard

APP_TITLE = "TNT Remote"

HELP = (
    "TNT Remote lets Claude (phone app, claude.ai, Claude Code) use this CardputerZero "
    "from anywhere it has internet: run commands, read and change files, install and "
    "run programs, and use TNT AV Net Tools.\n"
    "It connects out through a Cloudflare tunnel, so no ports are opened on the network "
    "you plug into.\n"
    "To connect Claude: add the custom connector (address on the Status screen), then "
    "choose Pair new connection here and type the code on the Allow page.\n"
    "While it is on, every TNT app shows an orange dot in its title bar (red when Admin "
    "/ sudo is allowed). Turn Remote access Off to cut Claude off at once; Disconnect "
    "everyone forgets all sign-ins.\n"
    "TheTechNomad.com"
)


def ago(t: float) -> str:
    s = int(time.time() - t)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h"


def wrap(text: str, width: int = 30) -> list[str]:
    out = []
    for para in text.split("\n"):
        out += textwrap.wrap(para, width) or [""]
    return out


class Screen:
    title = APP_TITLE
    live = False   # redraw every second

    def __init__(self, app):
        self.app = app

    def rows(self) -> list:
        return []

    def hint(self) -> str:
        return "ESC back"

    def right(self) -> str:
        return ""

    def key(self, k) -> None:
        if T.nav_name(k.name, k.char) in T.BACK:
            self.app.pop()


class TextScreen(Screen):
    """Scrolling read-only text."""

    def __init__(self, app, title: str, lines: list, live=None):
        super().__init__(app)
        self.title, self._lines, self.top, self.fn = title, lines, 0, live
        self.live = live is not None

    def lines(self) -> list:
        return self.fn() if self.fn else self._lines

    def rows(self):
        ls = self.lines()
        self.top = max(0, min(self.top, len(ls) - T.ROWS))
        return ls[self.top:self.top + T.ROWS]

    def hint(self):
        return "↑↓ scroll  ESC back" if len(self.lines()) > T.ROWS else "ESC back"

    def key(self, k):
        n = T.nav_name(k.name, k.char)
        if n in T.UP:
            self.top -= 1
        elif n in T.DOWN:
            self.top += 1
        elif n == "pagedown":
            self.top += T.ROWS
        elif n == "pageup":
            self.top -= T.ROWS
        else:
            super().key(k)


class Confirm(Screen):
    def __init__(self, app, title: str, text: str, on_yes, color=T.WARN):
        super().__init__(app)
        self.title, self.text, self.on_yes, self.color = title, text, on_yes, color

    def rows(self):
        return [(line, self.color) for line in wrap(self.text, 30)][:T.ROWS]

    def hint(self):
        return "OK = yes   ESC = no"

    def key(self, k):
        if k.name == "enter":
            self.app.pop()
            self.on_yes()
        elif k.name == "esc" or T.nav_name(k.name, k.char) == "left":
            self.app.pop()


class FormScreen(Screen):
    def __init__(self, app, title: str, form: T.EditList):
        super().__init__(app)
        self.title, self.form = title, form

    def rows(self):
        return self.form.view(T.ROWS)

    def hint(self):
        return self.form.hint()

    def key(self, k):
        ev = self.form.handle(k)
        if ev == "back":
            self.app.pop()
        elif ev:
            self.event(ev)

    def event(self, ev: str) -> None:
        pass


class Home(FormScreen):
    live = True

    def __init__(self, app):
        fields = [T.Field("remote", "Remote access", "bool"),
                  T.Field("pair", "Pair new connection", "action"),
                  T.Field("status", "Status & activity", "action"),
                  T.Field("clients", "Connected", "action"),
                  T.Field("perms", "Permissions", "action"),
                  T.Field("setup", "Setup", "action"),
                  T.Field("help", "Help", "action")]
        super().__init__(app, APP_TITLE, T.EditList(fields, {"remote": control.is_on()}))

    def right(self):
        if not self.app.on:
            return "OFF"
        return "ROOT" if self.app.cfg.get("allow_sudo") else "ON"

    def rows(self):
        self.form.values["remote"] = self.app.on
        rows = self.form.view(T.ROWS)
        for r in rows:
            if r.label == "Remote access":
                r.color = T.OK if self.app.on else T.FG
            if r.label == "[ Connected ]":
                r.value = str(len(self.app.clients))
        return rows

    def hint(self):
        return "↑↓ move  OK select  ESC quit"

    def key(self, k):
        if k.name == "esc":
            self.app.quit = True
            return
        super().key(k)

    def event(self, ev):
        app = self.app
        if ev == "changed:remote":
            want = bool(self.form.values["remote"])
            if want and not C.tunnel_token():
                app.toast("No tunnel set up yet. The server runs, but only on this device until Setup is done.")
            err = control.set_on(want)
            if err:
                app.toast("Could not switch: " + err)
            app.refresh(now=True)
        elif ev == "action:pair":
            app.push(PairScreen(app))
        elif ev == "action:status":
            app.push(TextScreen(app, "Status", [], live=app.status_lines))
        elif ev == "action:clients":
            app.push(ClientsScreen(app))
        elif ev == "action:perms":
            app.push(PermsScreen(app))
        elif ev == "action:setup":
            app.push(SetupScreen(app))
        elif ev == "action:help":
            app.push(TextScreen(app, "Help", wrap(HELP, 30) + [f"Version {__version__}"]))


class PairScreen(Screen):
    """Big one-time code to type on the Allow page in Claude."""
    title = "Pair new connection"
    live = True

    def __init__(self, app):
        super().__init__(app)
        self.code = oauth.new_pairing_code()
        app.refresh(now=True)

    def rows(self):
        st = oauth.pairing_state()
        if not st["active"]:
            return [("Code used or expired.", T.WARN), ("", T.FG), ("OK = make a new code", T.FG)]
        return [("Type this on the Allow page:", T.DIM), "", "", "",
                (f"Valid {st['left'] // 60}:{st['left'] % 60:02d} min, one use", T.DIM),
                ("" if self.app.on else "Remote access is OFF!", T.BAD)]

    def draw_extra(self, surf):
        if oauth.pairing_state()["active"]:
            import pygame
            f = big_font()
            img = f.render(self.code, True, (255, 255, 255))
            x = (T.W - img.get_width()) // 2
            y = T.TITLE_H + T.ROW_H + 6
            pygame.draw.rect(surf, T.SEL_BG, (x - 10, y - 4, img.get_width() + 20, img.get_height() + 8), border_radius=6)
            surf.blit(img, (x, y))

    def hint(self):
        return "OK new code   ESC back"

    def key(self, k):
        if k.name == "enter":
            self.code = oauth.new_pairing_code()
        else:
            super().key(k)


_big = []


def big_font():
    if not _big:
        import os
        import pygame
        path = next((p for p in T.FONT_PATHS if os.path.exists(p)), None)
        _big.append(pygame.font.Font(path, 40) if path else pygame.font.Font(None, 56))
    return _big[0]


class ClientsScreen(Screen):
    title = "Connected"

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0

    def items(self):
        return [(c["name"] or c["id"][:12], ago(c["last_auth"]) if c["last_auth"] else "") for c in self.app.clients]

    def rows(self):
        its = self.items()
        rows = [T.RowView(n, a, "selected" if False else "normal") for n, a in its[:T.ROWS - 1]]
        if not its:
            rows = [T.RowView("Nobody is connected", "", "normal", T.DIM)]
        rows.append(T.RowView("[ Disconnect everyone ]", "", "selected", T.BAD))
        return rows

    def hint(self):
        return "OK disconnect everyone  ESC back"

    def key(self, k):
        if k.name == "enter":
            def yes():
                oauth.revoke_all()
                self.app.refresh(now=True)
                self.app.toast("Everyone disconnected. Claude must pair again.")
            self.app.push(Confirm(self.app, "Disconnect everyone",
                                  "Forget every Claude sign-in? Each one has to pair again with a new code.", yes))
        else:
            super().key(k)


class PermsScreen(FormScreen):
    def __init__(self, app):
        cfg = app.cfg
        fields = [T.Field("allow_commands", "Run commands", "bool"),
                  T.Field("allow_sudo", "Admin (sudo)", "bool", color=T.BAD),
                  T.Field("allow_writes", "Change files", "bool"),
                  T.Field("allow_net_tools", "Net Tools", "bool")]
        super().__init__(app, "Permissions", T.EditList(fields, {f.key: bool(cfg.get(f.key)) for f in fields}))

    def event(self, ev):
        if not ev.startswith("changed:"):
            return
        key = ev.split(":", 1)[1]
        if key == "allow_sudo" and self.form.values["allow_sudo"]:
            self.form.values["allow_sudo"] = False

            def yes():
                self.form.values["allow_sudo"] = True
                self.save()
                self.app.toast("Admin is ON: Claude can run commands as root. The dot in the title bar turns red.")
            self.app.push(Confirm(self.app, "Admin (sudo)",
                                  "Let Claude run commands as root (apt install, system settings)? Turn it off when you're done.",
                                  yes, T.BAD))
            return
        self.save()

    def save(self):
        cfg = C.load()
        cfg.update(self.form.values)
        C.save(cfg)
        self.app.cfg = cfg


class SetupScreen(FormScreen):
    live = True

    def __init__(self, app):
        fields = [T.Field("public_url", "Address", "text", maxlen=120, help="https://..."),
                  T.Field("token", "Tunnel token", "action"),
                  T.Field("cf", "cloudflared", "action"),
                  T.Field("log", "Recent tool calls", "action")]
        super().__init__(app, "Setup", T.EditList(fields, {"public_url": app.cfg.get("public_url", "")}))
        self.cfv = control.cloudflared_version()

    def rows(self):
        rows = self.form.view(T.ROWS)
        for r in rows:
            if r.label == "[ Tunnel token ]":
                r.value = "set" if C.tunnel_token() else "missing"
            elif r.label == "[ cloudflared ]":
                r.value = self.cfv or "install"
        return rows

    def event(self, ev):
        app = self.app
        if ev == "changed:public_url":
            cfg = C.load()
            v = self.form.values["public_url"].strip().rstrip("/")
            if v and not v.startswith("https://"):
                v = "https://" + v
            cfg["public_url"] = v
            self.form.values["public_url"] = v
            C.save(cfg)
            app.cfg = cfg
            control.restart()
        elif ev == "action:token":
            app.push(TextScreen(app, "Tunnel token", wrap(
                "The token comes from Cloudflare (Workers VPC > Tunnels). It is too long to type, so it is "
                "loaded over SSH or by Claude on Ted's PC:\n"
                "tnt-remote --set-token  (paste, then Ctrl+D)\n"
                + ("A token is saved." if C.tunnel_token() else "No token saved yet."), 30)))
        elif ev == "action:cf":
            def job():
                try:
                    self.cfv = control.install_cloudflared(lambda m: None)
                    control.restart()
                    return f"cloudflared {self.cfv} installed."
                except Exception as e:
                    return f"Install failed: {e}"
            app.busy("Installing cloudflared", job)
        elif ev == "action:log":
            def lines():
                try:
                    import json
                    out = []
                    for raw in open(C.AUDIT_LOG).readlines()[-60:][::-1]:
                        d = json.loads(raw)
                        out.append((f"{d['t'][11:16]} {d['tool']}", T.FG if d.get("ok") else T.BAD))
                    return out or ["(nothing yet)"]
                except (OSError, ValueError):
                    return ["(nothing yet)"]
            app.push(TextScreen(app, "Recent tool calls", [], live=lines))


class App:
    def __init__(self, panel: L.Panel, kb: Keyboard | None):
        self.panel, self.kb = panel, kb
        self.cfg = C.load()
        self.on = control.is_on()
        self.status: dict = {}
        self.clients: list = []
        self.stack: list[Screen] = []
        self.quit = False
        self._toast = ("", 0.0)
        self._last = 0.0
        self.refresh(now=True)
        self.push(Home(self))

    def push(self, s: Screen) -> None:
        self.stack.append(s)

    def pop(self) -> None:
        if len(self.stack) > 1:
            self.stack.pop()

    def toast(self, text: str) -> None:
        self.push(TextScreen(self, "TNT Remote", [(l, T.WARN) for l in wrap(text, 30)]))

    def busy(self, label: str, fn) -> None:
        scr = TextScreen(self, label, [("Working...", T.DIM)])
        self.push(scr)

        def run():
            res = fn()
            scr._lines = [(l, T.OK if "fail" not in res.lower() else T.BAD) for l in wrap(res, 30)]
        threading.Thread(target=run, daemon=True).start()

    def refresh(self, now: bool = False) -> None:
        if not now and time.time() - self._last < 1.5:
            return
        self._last = time.time()
        self.on = control.is_on()
        self.status = (C.read_json(C.STATUS_FILE) or {}) if self.on else {}
        self.cfg = C.load()
        try:
            self.clients = oauth.Store().summary()
        except Exception:
            self.clients = []

    def status_lines(self) -> list:
        st, cfg = self.status, self.cfg
        tun = st.get("tunnel", "off") if self.on else "off"
        col = T.OK if tun == "connected" else (T.WARN if self.on else T.DIM)
        url = cfg.get("public_url") or "(no address set)"
        out = [("Server: " + ("running" if self.on else "OFF"), T.OK if self.on else T.BAD),
               (f"Tunnel: {tun} {st.get('tunnel_detail', '')}".strip(), col),
               ("Connector address:", T.DIM)]
        out += [(l, T.FG) for l in wrap(url + ("/mcp" if cfg.get("public_url") else ""), 30)]
        out.append((f"Connected: {len(self.clients)}   Admin: {'ON' if cfg.get('allow_sudo') else 'off'}",
                    T.BAD if cfg.get("allow_sudo") else T.FG))
        out.append(("Recent activity:", T.DIM))
        for r in st.get("recent", []):
            out.append((f"{ago(r['t']):>3} {r['text']}", T.FG))
        if not st.get("recent"):
            out.append(("  (none yet)", T.DIM))
        return out

    def draw(self) -> None:
        s = self.stack[-1]
        T.render(self.panel.surf, s.title, s.rows(), s.hint(), None, s.right(), self.panel.fonts)
        if hasattr(s, "draw_extra"):
            s.draw_extra(self.panel.surf)
        self.panel.flush()

    def run(self) -> None:
        next_draw = 0.0
        while not self.quit:
            keys = self.kb.poll(0.25) if self.kb else []
            for k in keys:
                self.stack[-1].key(k)
                next_draw = 0
            self.refresh()
            if time.time() >= next_draw:
                self.draw()
                next_draw = time.time() + (1.0 if self.stack[-1].live else 3.0)


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
            panel.draw(APP_TITLE, [("No keyboard found.", T.BAD)], "")
            time.sleep(4)
            return 1
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        msg = "Remote access stays ON." if control.is_on() else "Remote access is off."
        panel.draw(APP_TITLE, [(msg, T.OK), ("Bye!", T.FG)], "")
        kb.close()
    return 0
