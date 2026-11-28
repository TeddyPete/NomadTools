#!/usr/bin/env bash
# Builds the store .deb: build/nomad-sdr_<ver>-1_arm64.deb
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=nomad-sdr
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
REV=${REV:-1}
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/nomadsdr" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 nomadsdr/*.py "$A/lib/$PKG/nomadsdr/"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER-$REV
Architecture: arm64
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-pygame (>= 2.1), python3-numpy, librtlsdr0, multimon-ng, alsa-utils
Recommends: rtl-sdr
Installed-Size: $SIZE
Section: hamradio
Priority: optional
Homepage: https://www.TheTechNomad.com
Description: Nomad SDR, a ham radio receiver for RTL-SDR dongles (CardputerZero)
 Part of the Nomad tools by Tech Nomad Ted, TheTechNomad.com.
 Listen with FM, AM, SSB and CW on an RTL-SDR (V3 HF by direct sampling),
 with a US ham band plan that shows your license privileges and repeater
 offsets, WAV recording with a QR download page and USB copy, bias-tee
 control, APRS receive that feeds Rig Companion's map, and a fox-hunt
 signal meter. Runs as the normal user; settings live in
 ~/.config/nomad-sdr/, recordings in ~/.local/share/nomad-sdr/.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
