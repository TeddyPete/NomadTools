#!/usr/bin/env bash
# Builds the APPLaunch .deb: build/tnt-packet-capture_<ver>_all.deb
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=tnt-packet-capture
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/tntcap" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 tntcap/*.py "$A/lib/$PKG/tntcap/"
sed -i "s/^__version__ = .*/__version__ = \"$VER\"/" "$A/lib/$PKG/tntcap/__init__.py"
for s in postinst postrm prerm; do install -m 755 packaging/$s "$ROOT/DEBIAN/$s"; done
install -m 644 packaging/triggers "$ROOT/DEBIAN/triggers"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Architecture: all
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3, python3-pygame (>= 2.1), python3-numpy, tcpdump, libcap2-bin, iproute2
Installed-Size: $SIZE
Section: net
Priority: optional
Homepage: https://TheTechNomad.com
Description: TNT Packet Capture for the M5Stack CardputerZero
 Part of the TNT (Tech Nomad Ted) tools, TheTechNomad.com.
 Saves .pcap files for Wireshark from the Ethernet port (plug it into a
 switch mirror/SPAN port). AV filter presets (Dante, PTP, AES67, NDI,
 control systems, multicast), host/port filters, time and size limits or
 a ring buffer, live packet counters and a protocol breakdown on the
 built-in screen. Get files off over a web page, a USB drive or scp.
 .
 The package gives tcpdump capture rights (setcap), so the app never
 runs as root.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
