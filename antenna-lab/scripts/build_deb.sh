#!/usr/bin/env bash
# Builds the store .deb: build/askelmer-antenna-lab_<ver>-1_arm64.deb
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=askelmer-antenna-lab
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
REV=${REV:-1}
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/elmerlab" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 elmerlab/*.py "$A/lib/$PKG/elmerlab/"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER-$REV
Architecture: arm64
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-pygame (>= 2.1), python3-numpy, nec2c
Installed-Size: $SIZE
Section: hamradio
Priority: optional
Homepage: https://askelmer.com
Description: Ask Elmer Antenna Lab for the M5Stack CardputerZero
 Models ham radio antennas with the NEC2 engine (nec2c): dipoles, inverted
 Vs, OCFDs, end-fed half waves, fan and trap dipoles, G5RV, verticals,
 ground planes, J-poles, Yagis, Moxons, quads, delta and sky loops and
 small magnetic loops. Shows feed impedance, SWR across the band, gain,
 takeoff angle and the radiation pattern, tunes the main size for
 resonance and lists what to cut. Runs as the normal user; settings live
 in ~/.config/askelmer-antenna-lab/.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
