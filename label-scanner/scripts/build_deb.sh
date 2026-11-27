#!/usr/bin/env bash
# Builds the store .deb: build/nomad-label-scanner_<ver>-1_arm64.deb
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=nomad-label-scanner
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
REV=${REV:-1}
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/nomadscan" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 nomadscan/*.py "$A/lib/$PKG/nomadscan/"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER-$REV
Architecture: arm64
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3 (>= 3.9), python3-pygame (>= 2.1), python3-numpy, python3-pil, python3-zbar, tesseract-ocr, tesseract-ocr-eng, rpicam-apps-core | rpicam-apps, iproute2, iputils-ping
Recommends: arp-scan
Installed-Size: $SIZE
Section: utils
Priority: optional
Homepage: https://TheTechNomad.com
Description: Nomad Label Scanner for the M5Stack CardputerZero
 Part of the Nomad tools by Tech Nomad Ted, TheTechNomad.com.
 Scans AV gear labels with the camera: barcodes and QR codes are read
 live, and the printed text is read on the device (OCR) to pick out MAC
 addresses, IP addresses, serial and model numbers. Looks the MAC maker
 up, finds the device on the local network, and builds a per-job
 inventory you download as Excel (.xlsx) or CSV from a QR web page or a
 USB stick. Runs as the normal user; scans live in ~/Nomad-Label-Scans/.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
