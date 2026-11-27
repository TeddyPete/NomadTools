#!/usr/bin/env bash
# Builds the store .deb: build/askelmer-shack-tools_<ver>-1_arm64.deb
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=askelmer-shack-tools
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
REV=${REV:-1}
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
L="$A/lib/$PKG/shacktools"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$L/fonts" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 shacktools/*.py "$L/"
install -m 644 shacktools/fonts/* "$L/fonts/"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER-$REV
Architecture: arm64
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-pygame (>= 2.1), python3-numpy
Installed-Size: $SIZE
Section: hamradio
Priority: optional
Homepage: https://askelmer.com
Description: Ask Elmer Shack Tools for the M5Stack CardputerZero
 Everyday ham radio calculators: frequency and wavelength with your US
 license privileges (Technician, General, Extra), the band plan, Ohm's
 law, decibels and dBm, SWR and mismatch loss, coax loss, Maidenhead grid
 squares with distance and beam heading, a UTC clock, phonetics and Q
 signals. Works offline. Runs as the normal user; settings live in
 ~/.config/askelmer-shack-tools/.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
