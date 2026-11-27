#!/usr/bin/env bash
# Builds the APPLaunch .deb: build/tnt-wifi-share_<ver>_all.deb
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=tnt-wifi-share
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/tntshare" \
  "$ROOT/usr/lib/$PKG" "$ROOT/usr/lib/systemd/system" "$ROOT/usr/share/polkit-1/rules.d" "$ROOT/usr/bin"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 tntshare/*.py "$A/lib/$PKG/tntshare/"
install -m 755 packaging/nat-helper "$ROOT/usr/lib/$PKG/nat-helper"
install -m 644 "packaging/tnt-wifi-share-nat@.service" "$ROOT/usr/lib/systemd/system/tnt-wifi-share-nat@.service"
install -m 644 packaging/60-$PKG.rules "$ROOT/usr/share/polkit-1/rules.d/60-$PKG.rules"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Architecture: all
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3, python3-pygame (>= 2.1), python3-numpy, network-manager, dnsmasq-base, nftables, iw, iproute2
Recommends: polkitd, chromium | firefox-esr | firefox
Installed-Size: $SIZE
Section: net
Priority: optional
Homepage: https://TheTechNomad.com
Description: TNT WiFi Share for the M5Stack CardputerZero
 Part of the TNT (Tech Nomad Ted) tools, TheTechNomad.com.
 Shares Wi-Fi internet to the Ethernet port (NAT, DHCP on or off) to get
 standalone AV racks online, or turns Ethernet into a Wi-Fi hotspot.
 Join Wi-Fi, log in to guest Wi-Fi pages and set every address from the
 keyboard, with status on the built-in screen.
 .
 All profiles it creates are in-memory only, and quitting the app restores
 the previous network setup; a reboot always does. A polkit rule lets
 netdev-group users manage NetworkManager and the app's NAT unit.
CTL
cat > "$ROOT/DEBIAN/prerm" <<'SH'
#!/bin/sh
# Undo any sharing still running before the files go away.
set +e
for u in $(systemctl list-units --plain --no-legend 'tnt-wifi-share-nat@*' 2>/dev/null | awk '{print $1}'); do
  systemctl stop "$u"
done
for c in $(nmcli -t -f NAME connection show 2>/dev/null | grep '^tnt-share-'); do
  nmcli connection delete id "$c" >/dev/null 2>&1
done
exit 0
SH
cat > "$ROOT/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if [ -d /run/systemd/system ]; then systemctl daemon-reload || true; fi
exit 0
SH
chmod 755 "$ROOT/DEBIAN/prerm" "$ROOT/DEBIAN/postinst"
mkdir -p build
OUT="build/${PKG}_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
