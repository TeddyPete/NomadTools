# Nomad MCP

**An MCP server you can take anywhere.** By Tech Nomad Ted, [TheTechNomad.com](https://TheTechNomad.com).

Nomad MCP turns an M5Stack CardputerZero into a remote **MCP server**. You plug it in anywhere with internet, and these apps can use it:
* Claude (phone app, claude.ai, Claude Code)
* ChatGPT (developer mode)
* OpenAI Codex
* any other MCP client

The connected app can:

* run commands and long background jobs, and run them as root while **Admin (sudo)** is switched on at the device
* read, write, edit, move and delete files
* take a screenshot of the built-in screen
* run TNT AV Net Tools checks when that app is installed

## Setup on the device (about 3 minutes)

1. Open **Nomad MCP**. The first time, it shows what the app does and how, with **Start setup** already selected. Press OK. Later you can rerun it from **Setup > ngrok setup**. Three QR codes follow:
   1. Scan it and make a free ngrok account, or sign in. Then press OK.
   2. Scan it to open your ngrok authtoken page and tap **Copy**. Then press OK.
   3. Scan it with your phone, on the same Wi-Fi/LAN as the device. Paste the token and tap Save. If your phone can't reach the device, press OK and type the token on the keyboard instead.
3. It switches Remote access on and shows your **connector address**, `https://<name>.ngrok-free.dev/mcp`, as text and as a QR code. This address is fixed and stays the same after restarts. Press OK there to get the pairing code.

No account? Pick **Quick test** instead. It works right away, but the address changes every time the device restarts. **Cloudflare** is there for people who already run Cloudflare tunnels. Its command-line steps are in [../remote-mcp/README.md](../remote-mcp/README.md).

## Add it to your AI app

* **Claude**: go to Settings > Connectors > Add custom connector, paste the address, and click Connect.
* **ChatGPT** (web):
  1. Go to Settings > Apps & Connectors > Advanced and turn on **Developer mode**.
  2. Choose **Create**. Name it *Nomad MCP*, paste the address as the MCP server URL, and set Authentication to **OAuth**.
  3. Tick that you trust it, then click Create.
* **Codex CLI**: run `codex mcp add nomad --url <address>`, then `codex mcp login nomad`.

The app then opens an **Allow** page. On the device, choose **Pair new connection** and type the code it shows on that page.

With the free ngrok plan, your browser may first show an ngrok "You are about to visit" page. Tap **Visit Site**.

## Safety

* Nomad MCP only dials **out**, so it opens no ports on the network.
* Every app has to be approved with a one-time code shown on the device's own screen. A code is valid for 10 minutes and one use.
* Tokens are stored only as hashes. Refresh tokens last 60 days and renew while the app is in use.
* **Remote access Off** cuts everyone off at once. **Connected > Disconnect everyone** forgets all sign-ins.
* Admin (sudo) stays off until you switch it on at the device. The title bar dot turns red while it is on.
* Every tool call is logged to `~/.local/state/nomad-mcp/audit.log`.
* The switches are guardrails, not a hard boundary. Treat Remote access On as giving the connected app full control of the device.

## Command line (over SSH)

```
nomad-mcp --status | --url | --on | --off | --pair | --tunnel ngrok|quick|cloudflare
          --set-ngrok-token (stdin) | --install-ngrok | --revoke-all | --log
```

## How it is built

Nomad MCP uses the same code as TNT MCP Link (`../remote-mcp/tntremote`). Only `brand.py` differs. That file gives Nomad MCP its own:
* config folders (`~/.config/nomad-mcp`, `~/.local/state/nomad-mcp`)
* user service (`nomad-mcp.service`)
* ports (server `127.0.0.1:8775`, token page `:8776`)
* root helper (`/usr/lib/nomad-mcp/rootrun`)

That is why both apps can be installed side by side.

`scripts/build_deb.sh` writes `build/nomad-mcp_<ver>_all.deb`.
