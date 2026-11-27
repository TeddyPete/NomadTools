"""Nomad MCP build of the shared server/app code in ../remote-mcp/tntremote.
scripts/build_deb.sh copies this over tntremote/brand.py in the package, so
Nomad MCP has its own folders, service, ports and root helper and can be
installed next to TNT MCP Link."""
APP_NAME = "Nomad MCP"
CMD = "nomad-mcp"
STATE = "nomad-mcp"
SERVICE = "nomad-mcp.service"
PORT = 8775
SETUP_PORT = 8776
ROOTRUN = "/usr/lib/nomad-mcp/rootrun"
MIGRATE_CLOUDFLARE = False      # new app: always starts on ngrok
