#!/usr/bin/env bash
# Builds the store .deb: build/askelmer-ham-exam_<ver>-1_arm64.deb
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=askelmer-ham-exam
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
REV=${REV:-1}
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
L="$A/lib/$PKG/hamexam"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$L/data/figures" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 hamexam/*.py "$L/"
install -d "$L/fonts"
install -m 644 hamexam/fonts/* "$L/fonts/"
# the NCVEC pools only (Ask Elmer explanations are not shipped)
install -m 644 hamexam/data/index.json hamexam/data/*-20??-20??.json "$L/data/"
install -m 644 hamexam/data/figures/*.png "$L/data/figures/"
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
Description: Ask Elmer Ham Exam for the M5Stack CardputerZero
 Study for the US amateur radio license exams with the official NCVEC
 question pools: Technician (2026-2030), General (2023-2027) and Amateur
 Extra (2024-2028). Practice exams drawn like the real test (one question
 from each group), study by subelement or group with the correct answer
 and rule reference after each question, your ten weakest questions,
 missed-question review, diagrams, and an estimate of your chance to pass.
 Works offline. Runs as the normal user; progress lives in
 ~/.config/askelmer-ham-exam/.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
