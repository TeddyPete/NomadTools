#!/usr/bin/env bash
# Builds the store .deb: build/askelmer-morse_<ver>-1_arm64.deb
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=askelmer-morse
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
REV=${REV:-1}
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
L="$A/lib/$PKG/elmermorse"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$L/fonts" "$L/data" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 elmermorse/*.py "$L/"
install -m 644 elmermorse/fonts/* "$L/fonts/"
install -m 644 elmermorse/data/* "$L/data/"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER-$REV
Architecture: arm64
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-pygame (>= 2.1), python3-numpy, alsa-utils
Recommends: python3-libgpiod
Installed-Size: $SIZE
Section: hamradio
Priority: optional
Homepage: https://askelmer.com
Description: Ask Elmer Morse for the M5Stack CardputerZero
 Learn Morse code the Koch way and play the Morse games from askelmer.com:
 Copy the code, Send the code and a park hunt. Key with a paddle on the
 GPIO pins or with the keyboard, send typed text or your paddle to a radio
 (GPIO optocoupler key-out, or a QRP Labs QMX over USB), with transmit off
 until you switch it on. Decode CW off the air from the side jack or a USB
 sound card, with automatic tone and speed. Runs as the normal user;
 settings live in ~/.config/askelmer-morse/.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
