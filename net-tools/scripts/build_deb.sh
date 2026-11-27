#!/usr/bin/env bash
# Builds the APPLaunch .deb: build/nomad-net-tools_<ver>_all.deb
# Needs: dpkg-deb, python3. Run from anywhere.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
PKG=nomad-net-tools
VER=$(python3 -c "import json;print(json.load(open('app-builder.json'))['version'])")
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
chmod 755 "$ROOT"
A="$ROOT/usr/share/APPLaunch"
install -d "$ROOT/DEBIAN" "$A/applications" "$A/bin" "$A/share/images" "$A/lib/$PKG/nomadnet"
install -m 644 packaging/$PKG.desktop "$A/applications/$PKG.desktop"
install -m 755 packaging/$PKG "$A/bin/$PKG"
install -m 644 packaging/icon_100.png "$A/share/images/$PKG.png"
install -m 644 nomadnet/*.py "$A/lib/$PKG/nomadnet/"
install -m 755 packaging/postinst packaging/postrm "$ROOT/DEBIAN/"
install -m 644 packaging/triggers "$ROOT/DEBIAN/triggers"
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Architecture: all
Maintainer: TeddyPete <299527578+TeddyPete@users.noreply.github.com>
Depends: python3, python3-pygame (>= 2.1), python3-numpy, python3-paramiko, python3-serial, tcpdump, arp-scan, iputils-ping, iputils-arping, traceroute, iw, ethtool, libcap2-bin, fonts-dejavu-core
Replaces: tnt-av-net-tools
Conflicts: tnt-av-net-tools
Recommends: network-manager
Installed-Size: $SIZE
Section: net
Priority: optional
Homepage: https://TheTechNomad.com
Description: Nomad Net Tools for the M5Stack CardputerZero
 Part of the Nomad tools by Tech Nomad Ted, TheTechNomad.com.
 Network tools for AV techs: network basics, ping, traceroute, IP scan
 with MAC makers, Dante/NDI/AES67/mDNS discovery, PTP and multicast
 health, Find AV gear (Crestron, Extron, Q-SYS, Biamp, Shure, Netgear AV
 Line) with info pulls after login, a Telnet/SSH/TCP/UDP/serial terminal,
 a control-protocol sniffer, pcap capture, DHCP/IP-conflict/LLDP/cable
 checks and saved per-site reports. Results show on the built-in screen
 and in a window on the HDMI desktop.
 .
 On install, tcpdump, arp-scan and arping get CAP_NET_RAW (and tcpdump and
 ethtool CAP_NET_ADMIN) via setcap, so the app never runs as root. Removing
 the package takes these back.
CTL
mkdir -p build
OUT="build/${PKG}_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "$OUT"
