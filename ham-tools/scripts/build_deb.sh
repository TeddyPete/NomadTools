#!/usr/bin/env bash
# Builds the store .deb: build/askelmer-ham-tools_<ver>-1_arm64.deb
# It replaces the older askelmer-shack-tools and askelmer-antenna-lab packages.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=$(python3 -c "import json;print(json.load(open('app-builder.json'))['package_name'])")
NAME=$(python3 -c "import json;print(json.load(open('app-builder.json'))['app_name'])")
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
OLD="askelmer-shack-tools, askelmer-antenna-lab"
REV=${REV:-1}
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
L="$A/lib/$PKG/hamtools"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$L/fonts" "$L/data" "$L/lab" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 hamtools/*.py "$L/"
install -m 644 hamtools/lab/*.py "$L/lab/"
install -m 644 hamtools/fonts/* "$L/fonts/"
install -m 644 hamtools/data/* "$L/data/"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER-$REV
Architecture: arm64
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-pygame (>= 2.1), python3-numpy, python3-sgp4, nec2c
Provides: $OLD
Replaces: $OLD
Conflicts: $OLD
Breaks: $OLD
Installed-Size: $SIZE
Section: hamradio
Priority: optional
Homepage: https://askelmer.com
Description: $NAME for the M5Stack CardputerZero
 Ham radio tools in your pocket, with Antenna Lab up front: model real
 antennas with the NEC2 engine (dipoles, end-feds, verticals, Yagis,
 Moxons, quads, loops) for impedance, SWR, gain, a 3D pattern, a beam
 optimizer and a cut list. Also band check with your US license
 privileges, RF math, where and when (distance, heading, greyline),
 propagation (solar data and an offline MUF estimate), satellite passes
 with Doppler, POTA and SOTA, a station clock with a 10-minute ID timer
 and a searchable reference. A GPS gives the time and location, shared
 with the other Ask Elmer and Nomad apps. Replaces Ask Elmer Shack Tools
 and Ask Elmer Antenna Lab and keeps their settings. Runs as the normal
 user; settings live in ~/.config/$PKG/.
CTL
# The old apps' folders can outlive their packages when Python left __pycache__ in them
# (dpkg does not remove files it did not install), and a stale folder still shows as an app.
cat > "$ROOT/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
for old in askelmer-shack-tools askelmer-antenna-lab; do
  d=/usr/share/APPLaunch/lib/$old
  if [ -d "$d" ] && ! dpkg -S "$d" >/dev/null 2>&1; then rm -rf "$d"; fi
done
exit 0
SH
cat > "$ROOT/DEBIAN/postrm" <<SH
#!/bin/sh
set -e
if [ "\$1" = remove ] || [ "\$1" = purge ]; then
  find /usr/share/APPLaunch/lib/$PKG -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  rmdir --ignore-fail-on-non-empty -p /usr/share/APPLaunch/lib/$PKG/hamtools/lab 2>/dev/null || true
fi
exit 0
SH
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
