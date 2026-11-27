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
install -d "$L/data"
install -m 644 shacktools/data/* "$L/data/"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER-$REV
Architecture: arm64
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-pygame (>= 2.1), python3-numpy, python3-sgp4
Installed-Size: $SIZE
Section: hamradio
Priority: optional
Homepage: https://askelmer.com
Description: Ask Elmer Shack Tools for the M5Stack CardputerZero
 Ham radio tools in your pocket: band check with your US license
 privileges and what's usually nearby, RF math (dB and S-units, SWR,
 Ohm's law, LC, toroids, attenuator pads), where and when (distance,
 heading, zones, sunrise, sunset and greyline), propagation (solar data
 and an offline MUF estimate), satellite passes with Doppler, POTA and
 SOTA spots, parks and summits near you with an activation counter, a
 station clock with a 10-minute ID timer, and a searchable reference.
 A USB GPS gives the time and location, shared with the other Ask Elmer
 and Nomad apps. Runs as the normal user; settings live in
 ~/.config/askelmer-shack-tools/.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
