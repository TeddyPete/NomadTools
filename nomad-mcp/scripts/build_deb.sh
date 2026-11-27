#!/usr/bin/env bash
# Builds the APPLaunch .deb: build/nomad-mcp_<ver>_all.deb
# Nomad MCP shares its code with TNT MCP Link (../remote-mcp/tntremote); only
# brand.py differs, so the two install side by side with separate folders,
# services (nomad-mcp.service vs tnt-remote.service), ports (8775 vs 8765),
# root helpers and sudoers files.
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
SRC="$HERE/../remote-mcp/tntremote"
PKG=nomad-mcp
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
L="$A/lib/$PKG/tntremote"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$L" "$ROOT/usr/bin" \
  "$ROOT/usr/lib/$PKG" "$ROOT/usr/lib/systemd/user" "$ROOT/etc/sudoers.d"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 "$SRC"/*.py "$L/"
install -m 644 brand.py "$L/brand.py"
sed -i "s/^__version__ = .*/__version__ = \"$VER\"/" "$L/__init__.py"
sed -i "1s/.*/\"\"\"Nomad MCP for the M5Stack CardputerZero (TheTechNomad.com).\"\"\"/" "$L/__init__.py"
install -m 755 packaging/rootrun "$ROOT/usr/lib/$PKG/rootrun"
install -m 644 packaging/$PKG.service "$ROOT/usr/lib/systemd/user/$PKG.service"
install -m 440 packaging/sudoers "$ROOT/etc/sudoers.d/$PKG"
for s in postinst prerm; do install -m 755 packaging/$s "$ROOT/DEBIAN/$s"; done
echo "/etc/sudoers.d/$PKG" > "$ROOT/DEBIAN/conffiles"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Architecture: all
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3, python3-pygame (>= 2.1), python3-numpy, sudo, systemd
Recommends: tnt-av-net-tools, fonts-dejavu-core
Installed-Size: $SIZE
Section: net
Priority: optional
Homepage: https://TheTechNomad.com
Description: Nomad MCP: an MCP server you can take anywhere
 By Tech Nomad Ted, TheTechNomad.com.
 Turns the CardputerZero into an MCP server that AI apps (Claude, ChatGPT
 developer mode, OpenAI Codex and other MCP clients) can use from wherever
 it is plugged in: run commands, read and change files, install and run
 programs, and use TNT AV Net Tools when installed.
 .
 It connects out through a free ngrok tunnel (no open ports). QR codes on
 the screen walk through making the ngrok account and pasting the token
 from a phone; a no-account quick test tunnel and Cloudflare are options.
 Each app signs in with OAuth plus a one-time pairing code shown on the
 device. Admin (sudo) mode uses a root helper allowed by
 /etc/sudoers.d/nomad-mcp and is only used while switched on at the device.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
