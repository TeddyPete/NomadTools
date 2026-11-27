#!/usr/bin/env bash
# Builds the APPLaunch .deb: build/nomad-wifi-share_<ver>-<rev>_arm64.deb (store naming)
# Needs: dpkg-deb, python3. Run from anywhere (use an LF checkout).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=nomad-wifi-share
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
REV=1
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/nomadshare" \
  "$ROOT/usr/lib/$PKG" "$ROOT/usr/lib/systemd/system" "$ROOT/usr/share/polkit-1/rules.d" "$ROOT/usr/bin" "$ROOT/usr/lib/tmpfiles.d"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
ln -s /usr/share/APPLaunch/bin/$PKG "$ROOT/usr/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 nomadshare/*.py "$A/lib/$PKG/nomadshare/"
install -m 755 packaging/net-helper "$ROOT/usr/lib/$PKG/net-helper"
install -m 644 packaging/$PKG.tmpfiles "$ROOT/usr/lib/tmpfiles.d/$PKG.conf"
install -m 644 "packaging/nomad-wifi-share-nat@.service" "$ROOT/usr/lib/systemd/system/nomad-wifi-share-nat@.service"
install -m 644 packaging/60-$PKG.rules "$ROOT/usr/share/polkit-1/rules.d/60-$PKG.rules"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER-$REV
Architecture: arm64
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3, python3-pygame (>= 2.1), python3-numpy, network-manager, dnsmasq-base, nftables, iw, iproute2
Replaces: tnt-wifi-share
Conflicts: tnt-wifi-share
Recommends: polkitd, wireguard-tools, chromium | firefox-esr | firefox
Installed-Size: $SIZE
Section: net
Priority: optional
Homepage: https://TheTechNomad.com
Description: Nomad WiFi Share for the M5Stack CardputerZero
 Part of the Nomad tools by Tech Nomad Ted, TheTechNomad.com.
 Shares Wi-Fi internet to the Ethernet port (NAT, DHCP on or off) to get
 standalone AV racks online, or turns Ethernet into a Wi-Fi hotspot.
 Join Wi-Fi, log in to guest Wi-Fi pages and set every address from the
 keyboard, with status on the built-in screen. Also: device list with
 rename / block / speed limit, DHCP reservations, port forwards, local DNS
 names, live speed dashboard, switch port (LLDP) and VLAN tagging, hotspot
 bridge mode, WireGuard VPN for shared devices and a first-run wizard.
 .
 All profiles it creates are in-memory only, and quitting the app restores
 the previous network setup; a reboot always does. A polkit rule lets
 netdev-group users manage NetworkManager and the app's NAT unit, whose
 root helper only loads checked rules for the shared side.
CTL
cat > "$ROOT/DEBIAN/prerm" <<'SH'
#!/bin/sh
# Undo any sharing still running before the files go away.
set +e
for u in $(systemctl list-units --plain --no-legend 'nomad-wifi-share-nat@*' 2>/dev/null | awk '{print $1}'); do
  systemctl stop "$u"
done
rm -f /etc/NetworkManager/dnsmasq-shared.d/nomad-wifi-share-*.conf
for c in $(nmcli -t -f NAME connection show 2>/dev/null | grep '^nomad-share-'); do
  nmcli connection delete id "$c" >/dev/null 2>&1
done
exit 0
SH
cat > "$ROOT/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
  systemd-tmpfiles --create /usr/lib/tmpfiles.d/nomad-wifi-share.conf || true
fi
exit 0
SH
chmod 755 "$ROOT/DEBIAN/prerm" "$ROOT/DEBIAN/postinst"
mkdir -p build
OUT="build/${PKG}_${VER}-${REV}_arm64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
