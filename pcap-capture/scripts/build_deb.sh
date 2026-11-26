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
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/tntcap" "$ROOT/usr/bin" \
  "$ROOT/usr/lib/$PKG" "$ROOT/usr/lib/systemd/system" "$ROOT/usr/lib/udev/rules.d" "$ROOT/usr/share/polkit-1/rules.d"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 tntcap/*.py "$A/lib/$PKG/tntcap/"
sed -i "s/^__version__ = .*/__version__ = \"$VER\"/" "$A/lib/$PKG/tntcap/__init__.py"
install -m 755 packaging/tap-helper "$ROOT/usr/lib/$PKG/tap-helper"
install -m 644 "packaging/tnt-packet-capture-tap@.service" "packaging/tnt-packet-capture-autotap@.service" \
  "$ROOT/usr/lib/systemd/system/"
install -m 644 packaging/90-$PKG.rules "$ROOT/usr/lib/udev/rules.d/90-$PKG.rules"
install -m 644 packaging/60-$PKG.rules "$ROOT/usr/share/polkit-1/rules.d/60-$PKG.rules"
for s in postinst postrm prerm; do install -m 755 packaging/$s "$ROOT/DEBIAN/$s"; done
install -m 644 packaging/triggers "$ROOT/DEBIAN/triggers"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Architecture: all
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3, python3-pygame (>= 2.1), python3-numpy, tcpdump, libcap2-bin, iproute2
Recommends: polkitd, network-manager, fonts-dejavu-core
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
 built-in screen. Inline tap mode bridges the built-in port with a USB
 Ethernet adapter (no IP, no STP, 802.1X/LLDP pass through) and can start
 by itself when the adapter is plugged in. With HDMI connected a live
 packet viewer opens on the desktop. Get files off through a web page
 (QR code on screen; download or delete) or a USB stick.
 .
 The package gives tcpdump capture rights (setcap), so the app never
 runs as root. A polkit rule lets netdev users start/stop the tap unit.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
