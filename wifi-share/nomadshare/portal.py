"""Internet check and guest Wi-Fi (captive portal) login.

check() asks a plain-HTTP "generate_204" URL. If something answers with a
redirect or a web page instead of 204, a captive portal is in the way.

Portal pages are fetched with a cookie jar and their HTML forms parsed, so
simple portals (accept terms, maybe type an email or room number) can be
completed from the keyboard. Portals that need JavaScript are opened in a
browser on the HDMI desktop instead (open_on_hdmi).
"""
from __future__ import annotations

import glob
import html
import http.client
import http.cookiejar
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

PROBES = ["http://connectivitycheck.gstatic.com/generate_204",
          "http://clients3.google.com/generate_204"]
UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
ACCEPT_WORDS = re.compile(r"accept|agree|connect|continue|login|log in|sign in|start|free|internet|access|get online|proceed|submit|go", re.I)


def check(timeout: float = 5) -> tuple[str, str]:
    """('online' | 'portal' | 'offline', portal_url_or_detail)."""
    last = "no answer"
    for url in PROBES:
        u = urllib.parse.urlsplit(url)
        try:
            c = http.client.HTTPConnection(u.hostname, timeout=timeout)
            c.request("GET", u.path, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
            r = c.getresponse()
            body = r.read(65536)
            c.close()
        except OSError as e:
            last = str(e)[:60]
            continue
        if r.status == 204:
            return "online", ""
        if r.status in (301, 302, 303, 307, 308):
            return "portal", urllib.parse.urljoin(url, r.getheader("Location", url))
        if r.status == 200 and len(body) == 0:
            return "online", ""
        return "portal", _redirect_in(body.decode("utf-8", "replace"), url) or url
    return "offline", last


def _redirect_in(text: str, base: str) -> str | None:
    """URL from a meta refresh or a simple JavaScript redirect, if any."""
    m = re.search(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*content=["\']?\s*\d*\s*;?\s*url=([^"\'>\s]+)', text, re.I)
    if not m:
        m = re.search(r'(?:window\.|document\.)?location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        m = re.search(r'location\.replace\(\s*["\']([^"\']+)["\']', text)
    return urllib.parse.urljoin(base, html.unescape(m.group(1))) if m else None


# ---- HTML form parsing -----------------------------------------------------

@dataclass
class Field:
    kind: str          # text, email, password, tel, number, checkbox, radio, select, hidden, submit
    name: str
    value: str = ""
    label: str = ""
    checked: bool = False
    options: list[tuple[str, str]] = field(default_factory=list)  # (value, text) for select
    required: bool = False

    @property
    def editable(self) -> bool:
        return self.kind in ("text", "email", "password", "tel", "number", "checkbox", "select", "radio")


@dataclass
class Form:
    action: str
    method: str
    fields: list[Field] = field(default_factory=list)

    @property
    def submits(self) -> list[Field]:
        return [f for f in self.fields if f.kind == "submit"]


@dataclass
class Page:
    url: str
    title: str = ""
    text: str = ""
    forms: list[Form] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (text, url)
    scripts: int = 0

    def best_form(self) -> Form | None:
        def score(f: Form) -> int:
            s = sum(1 for x in f.fields if x.kind in ("checkbox", "submit"))
            if any(x.kind == "password" for x in f.fields):
                s += 1
            if any(ACCEPT_WORDS.search(x.value or x.label) for x in f.submits):
                s += 3
            if re.search(r"search", f.action, re.I):
                s -= 5
            return s
        forms = [f for f in self.forms if f.fields]
        return max(forms, key=score) if forms else None

    def accept_links(self) -> list[tuple[str, str]]:
        return [(t, u) for t, u in self.links if ACCEPT_WORDS.search(t)][:6]

    @property
    def needs_browser(self) -> bool:
        return not self.best_form() and not self.accept_links()


class _Parser(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.page = Page(base)
        self.form: Form | None = None
        self.select: Field | None = None
        self.option: list | None = None
        self.button: Field | None = None
        self.link: list | None = None
        self.in_title = self.in_script = self.in_style = False
        self.labels_for: dict[str, str] = {}
        self.ids: dict[str, Field] = {}
        self.label_buf: list[str] | None = None
        self.label_for: str | None = None
        self.label_fields: list[Field] = []
        self.recent = ""

    def _form(self) -> Form:
        if self.form is None:  # inputs outside any <form>: collect them anyway
            self.form = Form(self.base, "get")
            self.page.forms.append(self.form)
        return self.form

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag == "title":
            self.in_title = True
        elif tag == "script":
            self.in_script = True
            self.page.scripts += 1
        elif tag == "style":
            self.in_style = True
        elif tag == "form":
            self.form = Form(urllib.parse.urljoin(self.base, a.get("action") or self.base),
                             (a.get("method") or "get").lower())
            self.page.forms.append(self.form)
        elif tag == "input":
            kind = (a.get("type") or "text").lower()
            if kind in ("image", "button"):
                kind = "submit" if kind == "image" else "button"
            if kind in ("button", "reset", "file"):
                return
            if kind not in ("hidden", "checkbox", "radio", "submit", "password", "email", "tel", "number"):
                kind = "text"
            f = Field(kind, a.get("name", ""), a.get("value", "" if kind != "checkbox" else "on"),
                      a.get("aria-label") or a.get("placeholder") or a.get("title") or "",
                      "checked" in a, required="required" in a)
            if kind == "submit" and not f.value:
                f.value = a.get("alt") or "Submit"
            if not f.label and kind not in ("hidden", "submit"):
                f.label = self.recent
            self._form().fields.append(f)
            if a.get("id"):
                self.ids[a["id"]] = f
            if self.label_buf is not None:
                self.label_fields.append(f)
        elif tag == "select":
            self.select = Field("select", a.get("name", ""), label=self.recent, required="required" in a)
            self._form().fields.append(self.select)
            if a.get("id"):
                self.ids[a["id"]] = self.select
        elif tag == "option" and self.select is not None:
            self.option = [a.get("value"), [], "selected" in a]
        elif tag == "textarea":
            f = Field("text", a.get("name", ""), label=a.get("placeholder") or self.recent)
            self._form().fields.append(f)
        elif tag == "button":
            t = (a.get("type") or "submit").lower()
            if t == "submit":
                self.button = Field("submit", a.get("name", ""), a.get("value", ""), "")
                self._form().fields.append(self.button)
        elif tag == "a" and a.get("href") and not a["href"].startswith(("javascript:", "#", "mailto:")):
            self.link = [urllib.parse.urljoin(self.base, a["href"]), []]
        elif tag == "label":
            self.label_buf, self.label_for, self.label_fields = [], a.get("for"), []
        elif tag == "meta" and (a.get("http-equiv") or "").lower() == "refresh":
            m = re.search(r"url=(.+)", a.get("content", ""), re.I)
            if m:
                self.page.links.append(("(auto redirect)", urllib.parse.urljoin(self.base, m.group(1).strip("'\" "))))

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "script":
            self.in_script = False
        elif tag == "style":
            self.in_style = False
        elif tag == "form":
            self.form = None
        elif tag == "select":
            self.select = None
        elif tag == "option" and self.option is not None and self.select is not None:
            text = " ".join("".join(self.option[1]).split())
            val = self.option[0] if self.option[0] is not None else text
            self.select.options.append((val, text))
            if self.option[2] or len(self.select.options) == 1:
                self.select.value = val
            self.option = None
        elif tag == "button" and self.button is not None:
            if not self.button.label:
                self.button.label = self.button.value or "Submit"
            self.button = None
        elif tag == "a" and self.link is not None:
            text = " ".join("".join(self.link[1]).split())
            if text:
                self.page.links.append((text[:40], self.link[0]))
            self.link = None
        elif tag == "label" and self.label_buf is not None:
            text = " ".join("".join(self.label_buf).split())
            if self.label_for:
                self.labels_for[self.label_for] = text
            for f in self.label_fields:
                f.label = text
            self.label_buf = None

    def handle_data(self, data):
        if self.in_script or self.in_style:
            return
        if self.in_title:
            self.page.title += data
            return
        if self.option is not None:
            self.option[1].append(data)
            return
        if self.button is not None:
            self.button.label += data.strip()
            return
        if self.link is not None:
            self.link[1].append(data)
        if self.label_buf is not None:
            self.label_buf.append(data)
        t = " ".join(data.split())
        if t:
            self.recent = t[:60]
            if len(self.page.text) < 600:
                self.page.text += t + " "

    def close(self):
        super().close()
        for fid, text in self.labels_for.items():
            if fid in self.ids and text:
                self.ids[fid].label = text
        for f in (x for fm in self.page.forms for x in fm.fields):
            f.label = " ".join(f.label.split())[:60]
            if f.kind == "submit" and not f.label:
                f.label = f.value or "Submit"
        self.page.title = " ".join(self.page.title.split())


def parse(text: str, url: str) -> Page:
    p = _Parser(url)
    p.feed(text)
    p.close()
    return p.page


# ---- fetching and submitting -------------------------------------------------

class Session:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.insecure = False
        self._build()

    def _build(self):
        ctx = ssl.create_default_context()
        if self.insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                                  urllib.request.HTTPSHandler(context=ctx))
        self.opener.addheaders = [("User-Agent", UA), ("Accept", "text/html,*/*")]

    def fetch(self, url: str, data: bytes | None = None, follow_meta: int = 3) -> Page:
        try:
            r = self.opener.open(url, data=data, timeout=15)
        except urllib.error.HTTPError as e:
            r = e  # portals often answer 401/403 with the login page
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLError) and not self.insecure:
                # Many portals use self-signed certificates; retry without checks.
                self.insecure = True
                self._build()
                return self.fetch(url, data, follow_meta)
            raise
        body = r.read(512 * 1024)
        charset = r.headers.get_content_charset() or "utf-8"
        text = body.decode(charset, "replace")
        final = r.geturl() if hasattr(r, "geturl") else url
        page = parse(text, final)
        if follow_meta and not page.forms:
            nxt = _redirect_in(text, final)
            if nxt and nxt != final:
                return self.fetch(nxt, None, follow_meta - 1)
        return page

    def submit(self, form: Form, button: Field | None = None) -> Page:
        pairs = []
        radios_done = set()
        for f in form.fields:
            if not f.name:
                continue
            if f.kind == "submit":
                continue
            if f.kind == "checkbox":
                if f.checked:
                    pairs.append((f.name, f.value or "on"))
            elif f.kind == "radio":
                if f.checked and f.name not in radios_done:
                    pairs.append((f.name, f.value))
                    radios_done.add(f.name)
            else:
                pairs.append((f.name, f.value))
        # radio groups with nothing checked: pick the first option
        for f in form.fields:
            if f.kind == "radio" and f.name and f.name not in radios_done:
                pairs.append((f.name, f.value))
                radios_done.add(f.name)
        b = button or (form.submits[0] if form.submits else None)
        if b and b.name:
            pairs.append((b.name, b.value))
        q = urllib.parse.urlencode(pairs).encode()
        if form.method == "post":
            return self.fetch(form.action, data=q)
        sep = "&" if "?" in form.action else "?"
        return self.fetch(form.action.split("#")[0] + (sep + q.decode() if pairs else ""))


# ---- HDMI desktop browser ---------------------------------------------------

BROWSERS = ["chromium", "chromium-browser", "firefox", "firefox-esr", "epiphany-browser", "x-www-browser"]


def _desktop_env() -> dict | None:
    env = dict(os.environ)
    rt = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env["XDG_RUNTIME_DIR"] = rt
    socks = sorted(p for p in glob.glob(os.path.join(rt, "wayland-*")) if not p.endswith(".lock"))
    if socks:
        env["WAYLAND_DISPLAY"] = os.path.basename(socks[0])
        return env
    if os.path.exists("/tmp/.X11-unix/X0"):
        env["DISPLAY"] = ":0"
        return env
    return None


def open_on_hdmi(url: str) -> str:
    """Open url in a browser on the Pi's HDMI desktop. Returns a status line."""
    browser = next((shutil.which(b) for b in BROWSERS if shutil.which(b)), None)
    if not browser:
        return "No web browser installed (try: sudo apt install chromium)"
    env = _desktop_env()
    if env is None:
        # The desktop isn't running: try to start it (allowed by our polkit rule).
        subprocess.run(["systemctl", "--no-ask-password", "start", "lightdm.service"],
                       capture_output=True, timeout=30)
        for _ in range(40):
            time.sleep(0.5)
            env = _desktop_env()
            if env:
                time.sleep(3)  # let the compositor finish starting
                break
    if env is None:
        return "HDMI desktop is not running"
    args = [browser]
    if "chromium" in browser:
        args += ["--new-window", "--no-first-run", "--password-store=basic"]
    elif "firefox" in browser:
        args += ["--new-window"]
    subprocess.Popen(args + [url], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return f"Opened on HDMI in {os.path.basename(browser)}"
