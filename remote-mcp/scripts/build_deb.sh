#!/usr/bin/env bash
# Builds the APPLaunch .deb: build/tnt-remote_<ver>_all.deb
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=tnt-remote
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/tntremote" "$ROOT/usr/bin" \
  "$ROOT/usr/lib/$PKG" "$ROOT/usr/lib/systemd/user" "$ROOT/etc/sudoers.d"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 tntremote/*.py "$A/lib/$PKG/tntremote/"
sed -i "s/^__version__ = .*/__version__ = \"$VER\"/" "$A/lib/$PKG/tntremote/__init__.py"
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
Description: TNT Remote: use the CardputerZero from Claude, anywhere
 Part of the TNT (Tech Nomad Ted) tools, TheTechNomad.com.
 A remote MCP server that lets Claude (phone app, claude.ai, Claude Code)
 run commands, read and change files, install and run programs and use
 TNT AV Net Tools on this CardputerZero, wherever it is plugged in.
 It connects out through a Cloudflare tunnel (no open ports) and signs
 Claude in with OAuth plus a one-time pairing code shown on the device.
 .
 On/off switch, live activity and permission switches on the built-in
 screen; other TNT apps show a dot in their title bar while it is on.
 Admin (sudo) mode uses a root helper allowed by /etc/sudoers.d/tnt-remote
 and is only used while switched on at the device.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
