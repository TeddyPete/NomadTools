"""The TNT Remote server: OAuth + MCP on 127.0.0.1, plus the Cloudflare tunnel.

Run by the user service tnt-remote.service (python3 -m tntremote --serve).
Only cloudflared, running next to it, can reach the port; there is no open
port on the network.
"""
from __future__ import annotations

import html
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from . import __version__, config as C, mcp, oauth

MAX_BODY = 8 * 1024 * 1024


class Server:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = oauth.Store()
        self.started = time.time()
        self.recent: deque = deque(maxlen=8)
        self.tunnel = "off"
        self.tunnel_detail = ""
        self.tproc: subprocess.Popen | None = None
        self.stop = threading.Event()
        self.reg_times: deque = deque(maxlen=40)
        self.lock = threading.Lock()

    # ---- status for the LCD app ----
    def activity(self, text: str, client: str = "") -> None:
        with self.lock:
            self.recent.appendleft({"t": time.time(), "text": text[:80], "client": client[:40]})
        self.write_status()

    def write_status(self) -> None:
        with self.lock:
            st = {"pid": os.getpid(), "version": __version__, "started": self.started, "port": self.cfg["port"],
                  "public_url": self.cfg.get("public_url", ""), "tunnel": self.tunnel, "tunnel_detail": self.tunnel_detail,
                  "recent": list(self.recent), "updated": time.time()}
        try:
            C.write_json(C.STATUS_FILE, st)
        except OSError:
            pass

    # ---- cloudflared ----
    def run_tunnel(self) -> None:
        backoff = 3
        while not self.stop.is_set():
            token = C.tunnel_token()
            binary = C.CLOUDFLARED if os.access(C.CLOUDFLARED, os.X_OK) else (shutil_which("cloudflared") or "")
            if not token or not binary:
                self.tunnel = "not set up"
                self.tunnel_detail = "no tunnel token" if not token else "cloudflared not installed"
                self.write_status()
                self.stop.wait(10)
                continue
            env = dict(os.environ, TUNNEL_TOKEN=token, GOMEMLIMIT="48MiB", GOGC="50")
            self.tunnel, self.tunnel_detail = "connecting", ""
            self.write_status()
            try:
                log = open(C.TUNNEL_LOG, "ab")
                if log.tell() > 1_000_000:
                    log.close()
                    os.replace(C.TUNNEL_LOG, C.TUNNEL_LOG + ".1")
                    log = open(C.TUNNEL_LOG, "ab")
                self.tproc = subprocess.Popen(
                    [binary, "tunnel", "--no-autoupdate", "--protocol", self.cfg.get("tunnel_protocol") or "auto", "--metrics", "127.0.0.1:0", "run"],
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            except OSError as e:
                self.tunnel, self.tunnel_detail = "error", str(e)
                self.write_status()
                self.stop.wait(30)
                continue
            t0 = time.time()
            for raw in iter(self.tproc.stdout.readline, b""):
                log.write(raw)
                log.flush()
                line = raw.decode(errors="replace")
                if "Registered tunnel connection" in line:
                    proto = re.search(r"protocol=(\w+)", line)
                    self.tunnel = "connected"
                    self.tunnel_detail = proto.group(1) if proto else ""
                    backoff = 3
                    self.write_status()
                elif " ERR " in line and self.tunnel != "connected":
                    self.tunnel_detail = line.split(" ERR ", 1)[1].strip()[:120]
                    self.write_status()
                elif "Unauthorized" in line or "Invalid tunnel secret" in line:
                    self.tunnel_detail = "token rejected"
            self.tproc.wait()
            log.close()
            if self.stop.is_set():
                break
            self.tunnel = "reconnecting"
            self.write_status()
            if time.time() - t0 > 120:
                backoff = 3
            self.stop.wait(backoff)
            backoff = min(backoff * 2, 120)

    def shutdown(self) -> None:
        self.stop.set()
        if self.tproc and self.tproc.poll() is None:
            self.tproc.terminate()
            try:
                self.tproc.wait(5)
            except subprocess.TimeoutExpired:
                self.tproc.kill()
        from .tools import stop_all_jobs
        stop_all_jobs()
        for p in (C.ACTIVE_FLAG, C.STATUS_FILE):
            try:
                os.unlink(p)
            except OSError:
                pass


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


# ---- HTTP --------------------------------------------------------------------------

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TNT Remote</title><style>
body{{margin:0;font-family:system-ui,sans-serif;background:#0b0e14;color:#eee}}
header{{background:#127834;padding:14px 18px;font-size:20px;font-weight:700}}
main{{padding:18px;max-width:440px;margin:auto}} .who{{color:#9fb3c8}}
input[type=text]{{font-size:26px;letter-spacing:4px;text-transform:uppercase;width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:2px solid #1e5ac8;background:#141a26;color:#fff}}
button{{margin-top:16px;width:100%;padding:14px;font-size:18px;font-weight:700;border:0;border-radius:8px;background:#1e5ac8;color:#fff}}
.err{{background:#5a0808;padding:10px;border-radius:6px}} small{{color:#8899aa}}</style></head>
<body><header>TNT Remote &middot; CardputerZero</header><main>{body}</main></body></html>"""


def page(body: str) -> bytes:
    return PAGE.format(body=body).encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "TNT-Remote"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    app: Server = None   # set in serve()

    def log_message(self, fmt, *args):   # quiet; journal gets errors only
        pass

    # helpers
    def base(self) -> str:
        cfg = self.app.cfg
        if cfg.get("public_url"):
            return cfg["public_url"]
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or f"127.0.0.1:{cfg['port']}"
        proto = self.headers.get("X-Forwarded-Proto") or ("http" if host.startswith(("127.", "localhost")) else "https")
        return f"{proto}://{host}"

    def send(self, code: int, body: bytes = b"", ctype: str = "application/json", headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, code: int, obj, headers: dict | None = None) -> None:
        self.send(code, json.dumps(obj).encode(), "application/json", headers)

    def body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(n) if n else b""

    def form(self) -> dict:
        raw = self.body().decode(errors="replace")
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype:
            try:
                return {k: str(v) for k, v in json.loads(raw or "{}").items()}
            except ValueError:
                return {}
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def prm(self) -> dict:
        b = self.base()
        return {"resource": b + "/mcp", "authorization_servers": [b], "scopes_supported": [oauth.SCOPE],
                "bearer_methods_supported": ["header"], "resource_name": "TNT Remote (CardputerZero)"}

    def asm(self) -> dict:
        b = self.base()
        return {"issuer": b, "authorization_endpoint": b + "/authorize", "token_endpoint": b + "/token",
                "registration_endpoint": b + "/register", "revocation_endpoint": b + "/revoke",
                "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"],
                "revocation_endpoint_auth_methods_supported": ["none"], "scopes_supported": [oauth.SCOPE]}

    def challenge(self) -> None:
        meta = self.base() + "/.well-known/oauth-protected-resource/mcp"
        self.json(401, {"error": "invalid_token", "error_description": "sign in required"},
                  {"WWW-Authenticate": f'Bearer resource_metadata="{meta}", scope="{oauth.SCOPE}"'})

    # routes
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            return self.json(200, self.prm())
        if path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration",
                    "/.well-known/oauth-authorization-server/mcp"):
            return self.json(200, self.asm())
        if path == "/authorize":
            return self.authorize_page(parse_qs(urlparse(self.path).query))
        if path == "/mcp":
            return self.send(405, b"", headers={"Allow": "POST"})
        if path in ("/", "/health"):
            return self.send(200, page("<p>TNT Remote is running. Add <b>" + html.escape(self.base()) +
                                       "/mcp</b> as a custom connector in Claude.</p>"), "text/html; charset=utf-8")
        self.send(404, b'{"error":"not found"}')

    def do_DELETE(self):
        self.send(405, b"", headers={"Allow": "POST"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            if path == "/mcp":
                return self.mcp_post()
            if path == "/register":
                return self.register()
            if path == "/token":
                return self.token()
            if path == "/authorize":
                return self.authorize_post()
            if path == "/revoke":
                self.app.store.revoke(self.form().get("token", ""))
                return self.send(200, b"{}")
        except ValueError as e:
            return self.json(400, {"error": "invalid_request", "error_description": str(e)})
        self.send(404, b'{"error":"not found"}')

    # OAuth
    def register(self):
        now = time.time()
        recent = [t for t in self.app.reg_times if now - t < 3600]
        if len(recent) >= 20:
            return self.json(429, {"error": "slow_down"})
        self.app.reg_times.append(now)
        try:
            meta = json.loads(self.body() or b"{}")
            res = self.app.store.register(meta)
        except (ValueError, TypeError) as e:
            return self.json(400, {"error": "invalid_redirect_uri", "error_description": str(e)})
        self.json(201, res)

    def _auth_params(self, q: dict) -> tuple[dict, str]:
        g = {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}
        cid, ruri = g.get("client_id", ""), g.get("redirect_uri", "")
        client = self.app.store.client(cid)
        if not client:
            return g, "This connection request isn't known to the device. Remove the connector in Claude and add it again."
        if ruri not in client["redirect_uris"]:
            return g, "The return address doesn't match. Remove the connector in Claude and add it again."
        if g.get("response_type") != "code" or g.get("code_challenge_method") != "S256" or len(g.get("code_challenge", "")) < 43:
            return g, "This sign-in request is missing its security check (PKCE)."
        g["client_name"] = client.get("name", "")
        return g, ""

    def authorize_page(self, q: dict, msg: str = "") -> None:
        g, err = self._auth_params(q)
        if err:
            return self.send(400, page(f'<p class="err">{html.escape(err)}</p>'), "text/html; charset=utf-8")
        hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                         for k, v in g.items() if k in ("client_id", "redirect_uri", "state", "code_challenge",
                                                         "code_challenge_method", "response_type", "scope", "resource"))
        st = oauth.pairing_state()
        info = (f"A code is showing on the device ({st['left'] // 60} min left)." if st["active"] else
                "On the CardputerZero open <b>TNT Remote</b> and choose <b>Pair new connection</b>. A code appears on its screen.")
        body = (f'<p><b class="who">{html.escape(g.get("client_name") or "Claude")}</b> wants full control of this CardputerZero: '
                f'run commands, read and change files, use Net Tools.</p><p>{info}</p>'
                + (f'<p class="err">{html.escape(msg)}</p>' if msg else "") +
                f'<form method="post" action="/authorize" autocomplete="off">{hidden}'
                '<label>Pairing code from the device screen</label><br><br>'
                '<input type="text" name="pair_code" maxlength="9" placeholder="ABCD-EFGH" autofocus autocapitalize="characters">'
                '<button type="submit">Allow</button></form>'
                '<p><small>Only approve if you started this from your own Claude account. '
                'You can disconnect everyone from the device menu at any time.</small></p>')
        self.send(200, page(body), "text/html; charset=utf-8",
                  {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://claude.ai https://claude.com http://localhost:* http://127.0.0.1:*; frame-ancestors 'none'"})

    def authorize_post(self):
        f = self.form()
        g, err = self._auth_params(f)
        if err:
            return self.send(400, page(f'<p class="err">{html.escape(err)}</p>'), "text/html; charset=utf-8")
        ok, msg = oauth.check_pairing(f.get("pair_code", ""))
        if not ok:
            self.app.activity("pairing: wrong code" if "Wrong" in msg else "pairing refused")
            return self.authorize_page({k: v for k, v in f.items() if k != "pair_code"}, msg)
        code = self.app.store.new_code(g["client_id"], g["redirect_uri"], g["code_challenge"],
                                       g.get("scope") or oauth.SCOPE, g.get("resource", ""))
        self.app.activity(f"paired: {g.get('client_name', '')}")
        q = {"code": code}
        if g.get("state"):
            q["state"] = g["state"]
        q["iss"] = self.base()
        sep = "&" if "?" in g["redirect_uri"] else "?"
        self.send(302, b"", "text/plain", {"Location": g["redirect_uri"] + sep + urlencode(q)})

    def token(self):
        f = self.form()
        gt = f.get("grant_type")
        try:
            if gt == "authorization_code":
                res = self.app.store.exchange_code(f.get("code", ""), f.get("client_id", ""),
                                                   f.get("redirect_uri", ""), f.get("code_verifier", ""))
            elif gt == "refresh_token":
                res = self.app.store.refresh(f.get("refresh_token", ""), f.get("client_id", ""))
            else:
                return self.json(400, {"error": "unsupported_grant_type"})
        except PermissionError as e:
            return self.json(400, {"error": str(e)})
        self.json(200, res, {"Pragma": "no-cache"})

    # MCP
    def mcp_post(self):
        auth = self.headers.get("Authorization", "")
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        who = self.app.store.check_access(tok)
        if not who:
            return self.challenge()
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("claude.ai", "claude.com", "localhost", "127.0.0.1",
                                                        urlparse(self.base()).hostname):
            return self.json(403, {"error": "origin not allowed"})
        try:
            msg = json.loads(self.body() or b"null")
        except ValueError:
            return self.json(400, mcp._err(None, -32700, "parse error"))
        client = who.get("client_name") or who["client"]
        if isinstance(msg, list):
            res = [r for r in (mcp.handle(m, self.app, client) for m in msg) if r is not None]
            return self.json(200, res) if res else self.send(202, b"")
        res = mcp.handle(msg, self.app, client)
        if res is None:
            return self.send(202, b"")
        self.json(200, res)


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):   # broken pipes etc.: not worth a traceback
        pass


def serve() -> int:
    C.ensure_dirs()
    cfg = C.load()
    app = Server(cfg)
    Handler.app = app
    httpd = QuietServer(("127.0.0.1", int(cfg["port"])), Handler)
    def flag():
        with open(C.ACTIVE_FLAG, "w") as fh:
            fh.write("root" if app.cfg.get("allow_sudo") else "on")

    flag()
    app.write_status()

    def reload_cfg():
        while not app.stop.wait(3):
            app.cfg = C.load()
            flag()
            app.write_status()

    def bye(*_):
        app.shutdown()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    threading.Thread(target=app.run_tunnel, daemon=True).start()
    threading.Thread(target=reload_cfg, daemon=True).start()
    print(f"TNT Remote {__version__} on 127.0.0.1:{cfg['port']}  public: {cfg.get('public_url') or '(not set)'}", flush=True)
    try:
        httpd.serve_forever(poll_interval=1)
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(serve())
