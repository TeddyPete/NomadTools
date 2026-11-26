# TNT Remote

Part of the TNT (Tech Nomad Ted) tools, [TheTechNomad.com](https://TheTechNomad.com).

TNT Remote turns the M5Stack CardputerZero into a **remote MCP server**. Claude (the phone app,
claude.ai or Claude Code) can then use the device from anywhere it has internet. Claude can:

* run commands and long background jobs (`run_command`, `start_background`, ...), and run them as root with `sudo: true` while **Admin (sudo)** is on
* read, write, edit, move and delete files, and list folders
* take a screenshot of the built-in 320x170 screen
* run TNT AV Net Tools checks (`net_tool`) and AV device info pulls (`av_device_info`) on the network the device is plugged into

## How it connects

```
Claude ──https──> Worker cp0.<you>.workers.dev ──Workers VPC──> Cloudflare Tunnel ──> cloudflared on the Pi ──> 127.0.0.1:8765 (TNT Remote)
```

* `cloudflared` only dials **out**, so no ports are opened on the network the device is plugged into. It works over QUIC (UDP 7844) or HTTP/2 (TCP 7844). The VPC Service points at the IP `127.0.0.1`, not a name, so HTTP/2-only networks work too.
* The Worker (`worker/`) only forwards requests and holds no secrets.
* Sign-in is OAuth 2.1 run on the device: dynamic client registration, PKCE S256, and redirects allowed only to claude.ai, claude.com or localhost. To approve a connection you type a **one-time pairing code** that the device shows on its own screen. A code is valid for 10 minutes and one use, and 5 wrong tries cancel it. Tokens are stored only as SHA-256 hashes. Access tokens last 1 hour and refresh tokens last 60 days, rotating on each use.
* Every tool call is logged to `~/.local/state/tnt-remote/audit.log`. The device's Status screen shows live activity.
* Turning **Remote access** off stops the server and the tunnel at once. **Disconnect everyone** forgets all sign-ins.
* While it is on, TNT apps that use the shared `tntui.py` show a dot at the right end of the title bar: orange when it is on, red when Admin (sudo) is also on.

**Security note:** the permission switches stop accidents and misuse by a client, but they are not a hard boundary. Anything Claude runs as `pi` could change them. Treat *Remote access On* as handing Claude full control of the device.

## On the device

`TNT Remote` in the launcher:

| Item | What it does |
|---|---|
| Remote access | On/Off. On also means it starts at boot (systemd user service `tnt-remote`, `pi` lingers). |
| Pair new connection | Shows the one-time code for the Allow page |
| Status & activity | Tunnel state, connector address, what Claude did recently |
| Connected | Signed-in clients, plus *Disconnect everyone* |
| Permissions | Run commands, **Admin (sudo)**, Change files, Net Tools |
| Setup | Public address, tunnel token status, install cloudflared, recent tool calls |

The keys follow the TNT standard: F/X (or Fn arrows) move, OK/→ select, ←/Esc back, and Esc quits on the main page.

Command line, over SSH: `tnt-remote --status | --on | --off | --pair | --set-url URL | --set-token (stdin) | --install-cloudflared | --revoke-all | --log`

## Setup (done once)

1. Cloudflare, from a PC where wrangler is logged in:
   ```
   npx wrangler tunnel create tnt-cp0
   npx wrangler vpc service create tnt-cp0 --type http --tunnel-id <TUNNEL_ID> --ipv4 127.0.0.1 --http-port 8765
   # put the service id in worker/wrangler.jsonc, then
   cd worker && npx wrangler deploy        # -> https://cp0.<you>.workers.dev
   ```
2. Pi: run `sudo dpkg -i tnt-remote_<ver>_all.deb`, then `tnt-remote --install-cloudflared` (downloads to `~/.local/lib/tnt-remote`, no root needed) and `tnt-remote --set-url https://cp0.<you>.workers.dev`. Give it the tunnel token with `tnt-remote --set-token` on stdin (the API endpoint is `GET /accounts/<acct>/cfd_tunnel/<id>/token`).
3. In the TNT Remote app, turn Remote access On.
4. In claude.ai, go to Settings > Connectors > Add custom connector and enter `https://cp0.<you>.workers.dev/mcp`. Click Connect, then on the device choose Pair new connection and type the code it shows.

## Files

* `tntremote/server.py`: HTTP server (OAuth + MCP endpoints) and the cloudflared supervisor
* `tntremote/oauth.py`: client registration, pairing codes, tokens
* `tntremote/mcp.py`: MCP JSON-RPC and the tool list
* `tntremote/tools.py`, `nettools.py`, `netrun.py`, `fbshot.py`: the tools
* `tntremote/app.py`: the LCD app. `tntui.py` is the shared TNT UI, now with the remote dot.
* `packaging/`: the APPLaunch wrapper, the user service, the root helper `rootrun`, and the sudoers drop-in
* `worker/`: the Cloudflare Worker relay

Build the package with `scripts/build_deb.sh`, which writes `build/tnt-remote_<ver>_all.deb`. The stdlib server uses about 24 MB of RAM and cloudflared about 38 MB.
