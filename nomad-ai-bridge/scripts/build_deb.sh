#!/usr/bin/env bash
# Builds the APPLaunch .deb: build/nomad-ai-bridge_<ver>_all.deb
# Nomad AI Bridge shares its code with TNT MCP Link (../remote-mcp/tntremote); only
# brand.py differs, so the two install side by side with separate folders,
# services (nomad-ai-bridge.service vs tnt-remote.service), ports (8775 vs 8765),
# root helpers and sudoers files.
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
SRC="$HERE/../remote-mcp/tntremote"
PKG=nomad-ai-bridge
OLD=nomad-mcp      # this app was called Nomad MCP until 0.2.0
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
L="$A/lib/$PKG/nomadbridge"   # own module name, so ps does not look like TNT MCP Link
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$L" "$ROOT/usr/bin" \
  "$ROOT/usr/lib/$PKG" "$ROOT/usr/lib/systemd/user" "$ROOT/etc/sudoers.d"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$OLD"      # old command name still works
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 "$SRC"/*.py "$L/"
install -m 644 brand.py "$L/brand.py"
sed -i "s/^__version__ = .*/__version__ = \"$VER\"/" "$L/__init__.py"
sed -i "1s/.*/\"\"\"Nomad AI Bridge for the M5Stack CardputerZero (TheTechNomad.com).\"\"\"/" "$L/__init__.py"
install -m 755 packaging/rootrun "$ROOT/usr/lib/$PKG/rootrun"
install -m 644 packaging/$PKG.service "$ROOT/usr/lib/systemd/user/$PKG.service"
install -m 440 packaging/sudoers "$ROOT/etc/sudoers.d/$PKG"
for s in preinst postinst prerm; do install -m 755 packaging/$s "$ROOT/DEBIAN/$s"; done
echo "/etc/sudoers.d/$PKG" > "$ROOT/DEBIAN/conffiles"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Architecture: all
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3, python3-pygame (>= 2.1), python3-numpy, sudo, systemd
Replaces: $OLD
Conflicts: $OLD
Provides: $OLD
Recommends: tnt-av-net-tools, fonts-dejavu-core
Installed-Size: $SIZE
Section: net
Priority: optional
Homepage: https://TheTechNomad.com
Description: Nomad AI Bridge: let your AI connect to and control your CardputerZero
 By Tech Nomad Ted, TheTechNomad.com. Formerly Nomad MCP.
 An MCP server for Claude, ChatGPT and Codex: AI apps (Claude, ChatGPT
 plugins, OpenAI Codex and other MCP clients) can use the
 CardputerZero from wherever it is plugged in: run commands, read and
 change files, install and run programs, and use TNT AV Net Tools.
 .
 It connects out through a free ngrok tunnel (no open ports). QR codes on
 the screen walk through making the ngrok account and pasting the token
 from a phone; a no-account quick test tunnel and Cloudflare are options.
 Each app signs in with OAuth plus a one-time pairing code shown on the
 device. Admin (sudo) mode uses a root helper allowed by
 /etc/sudoers.d/nomad-ai-bridge and is only used while switched on.
 .
 Powered by ngrok. Not affiliated with ngrok, Anthropic or OpenAI.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
