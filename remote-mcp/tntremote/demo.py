"""Render sample screens to PNG (store screenshots, checks on a PC)."""
from __future__ import annotations

import os
import time

from . import app as A, lcd as L, oauth


def render_screens(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    A.control.is_on = lambda: True
    panel = L.Panel(headless=True)
    app = A.App(panel, None)
    app.refresh = lambda now=False: None
    app.on = True
    app.cfg["tunnel_kind"] = "ngrok"
    app.clients = [{"id": "x", "name": "Claude", "last_auth": time.time() - 300},
                   {"id": "y", "name": "ChatGPT", "last_auth": time.time() - 900}]
    app.status = {"tunnel": "connected", "tunnel_detail": "ngrok", "tunnel_kind": "ngrok",
                  "public_url": "https://tnt-demo-cp0.ngrok-free.dev", "recent": [
        {"t": time.time() - 4, "text": "run_command"}, {"t": time.time() - 4, "text": "$ git pull && ./build.sh"},
        {"t": time.time() - 40, "text": "net_tool"}, {"t": time.time() - 41, "text": "net: find_av_gear"},
        {"t": time.time() - 300, "text": "paired: Claude"}]}
    shots = []

    def shot():
        app.draw()
        p = os.path.join(out_dir, f"lcd_{len(shots)}.png")
        panel.save(p)
        shots.append(p)

    shot()
    app.push(A.PairScreen(app))
    shot()
    app.pop()
    app.push(A.TextScreen(app, "Status", [], live=app.status_lines))
    shot()
    app.pop()
    app.push(A.PermsScreen(app))
    shot()
    app.pop()
    app.push(A.SetupScreen(app))
    shot()
    app.pop()
    app.push(A.ConnectorScreen(app))
    shot()
    app.pop()
    app.push(A.TunnelPick(app))
    shot()
    app.pop()
    app.push(A.QRScreen(app, "ngrok 1/3: account", A.NGROK_SIGNUP,
                        "Scan and make a free ngrok account (or sign in). If it asks where to begin, pick Share localhost. Then press OK.", lambda: None))
    shot()
    oauth.clear_pairing()
