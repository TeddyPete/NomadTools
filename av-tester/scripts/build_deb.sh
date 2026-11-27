#!/usr/bin/env bash
# Builds the APPLaunch .deb for the AV tester: build/tnt-av-tester_<ver>_all.deb
# Needs: dpkg-deb, python3. Run from anywhere.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=tnt-av-tester
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/zeroav"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 zeroav/*.py "$A/lib/$PKG/zeroav/"
install -d "$ROOT/usr/share/polkit-1/rules.d"
install -m 644 packaging/60-tnt-av-tester.rules "$ROOT/usr/share/polkit-1/rules.d/60-tnt-av-tester.rules"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Architecture: all
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3, python3-pygame (>= 2.1), python3-numpy, alsa-utils
Recommends: polkitd, edid-decode, libdrm-tests
Installed-Size: $SIZE
Section: utils
Priority: optional
Homepage: https://TheTechNomad.com
Replaces: zeroav-tester
Conflicts: zeroav-tester
Provides: zeroav-tester
Description: TNT AV Tester for the M5Stack CardputerZero
 Part of the TNT (Tech Nomad Ted) tools, TheTechNomad.com.
 Lip-sync tester using the built-in camera and mic.
 HDMI test patterns (bars, crosshatch, ramps, solids, checkerboards,
 judder box) and audio test tones with left/right channel ID,
 controlled from the keyboard with status on the built-in screen.
 While running, it pauses the Pi desktop (lightdm) so it can drive HDMI
 directly, and restores the desktop on exit. A polkit rule lets local
 video-group users stop/start lightdm.service only.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
