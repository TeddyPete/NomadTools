"""Command line for TNT Remote.

  tnt-remote                     the app (LCD + keyboard)
  tnt-remote --serve             the server (run by tnt-remote.service)
  tnt-remote --status            server, tunnel and connection status
  tnt-remote --on / --off        start (and start at boot) / stop the server
  tnt-remote --pair              make a pairing code (to approve Claude)
  tnt-remote --set-url URL       public address, e.g. https://cp0.ted4ff.workers.dev
  tnt-remote --set-token         read the Cloudflare tunnel token from stdin
  tnt-remote --install-cloudflared
  tnt-remote --revoke-all        disconnect every client
  tnt-remote --log               last tool calls
  tnt-remote --screens DIR       render sample LCD screens to PNG
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag in ("--serve", "--status", "--on", "--off", "--pair", "--set-token", "--install-cloudflared",
                 "--revoke-all", "--log"):
        ap.add_argument(flag, action="store_true")
    ap.add_argument("--set-url")
    ap.add_argument("--screens", metavar="DIR")
    a = ap.parse_args(argv)
    from . import config as C, control, oauth
    if a.serve:
        from .server import serve
        return serve()
    if a.status:
        st = C.read_json(C.STATUS_FILE) or {}
        cfg = C.load()
        print(json.dumps({"running": control.is_on(), "public_url": cfg["public_url"], "mcp_url": (cfg["public_url"] + "/mcp") if cfg["public_url"] else "",
                          "tunnel": st.get("tunnel"), "tunnel_detail": st.get("tunnel_detail"),
                          "token_set": bool(C.tunnel_token()), "cloudflared": control.cloudflared_version(),
                          "clients": [c["name"] for c in oauth.Store().summary()], "pairing": oauth.pairing_state(),
                          "allow_sudo": cfg["allow_sudo"], "recent": st.get("recent", [])[:5]}, indent=1))
        return 0
    if a.on or a.off:
        err = control.set_on(bool(a.on))
        print(err or ("on" if a.on else "off"))
        return 1 if err else 0
    if a.pair:
        print(oauth.new_pairing_code(), "(valid 10 minutes, one use)")
        return 0
    if a.set_url is not None:
        cfg = C.load()
        cfg["public_url"] = a.set_url.strip().rstrip("/")
        C.save(cfg)
        print("public URL:", cfg["public_url"] or "(cleared)")
        return 0
    if a.set_token:
        tok = sys.stdin.read().strip()
        if tok.startswith("cloudflared") or " " in tok:
            tok = tok.split()[-1]
        if len(tok) < 40:
            print("that doesn't look like a tunnel token", file=sys.stderr)
            return 1
        C.set_tunnel_token(tok)
        print("tunnel token saved;", control.restart() or "server restarted if it was on")
        return 0
    if a.install_cloudflared:
        control.install_cloudflared()
        return 0
    if a.revoke_all:
        oauth.revoke_all()
        print("all clients disconnected")
        return 0
    if a.log:
        try:
            print("".join(open(C.AUDIT_LOG).readlines()[-30:]), end="")
        except OSError:
            print("(no calls yet)")
        return 0
    if a.screens:
        from .demo import render_screens
        render_screens(a.screens)
        return 0
    from .app import main_ui
    return main_ui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
