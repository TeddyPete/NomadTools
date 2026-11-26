# TNT AV Net Tools

Network tools for AV techs on the [M5Stack CardputerZero](https://docs.m5stack.com/en/CardputerZero).
Part of the TNT (Tech Nomad Ted) tools, [TheTechNomad.com](https://TheTechNomad.com).

Everything runs from the keyboard with results on the built-in screen. When the Pi desktop is
running on HDMI, the same results also show, larger and wider, in a **TNT AV Net Tools** window
on the desktop.

## Install

From the M5Stack app store, or build the package yourself on the device:

```bash
git clone https://github.com/TeddyPete/ZeroAVTools.git
cd ZeroAVTools/net-tools
./scripts/build_deb.sh
sudo apt install ./build/tnt-av-net-tools_*_all.deb
```

The app appears on the home screen as **TNT AV Net Tools**. `apt` pulls in tcpdump, arp-scan,
traceroute, iw, ethtool, paramiko and pyserial.

**Rights, not root.** The app runs as the normal user. On install, the package gives tcpdump,
arp-scan and arping `CAP_NET_RAW` (plus `CAP_NET_ADMIN` for tcpdump and ethtool) with `setcap`,
so capture and scans work without sudo. Removing the package takes those back.

## Tools

| Menu | What it does |
| --- | --- |
| Network basics | Each interface: IP/mask, gateway, DHCP or static, DNS, Ethernet link speed/duplex, Wi-Fi SSID, signal, band and rate; then gateway / internet / DNS reachability |
| Ping, Traceroute | Live ping (count or until X) and traceroute with reverse names |
| IP scan | arp-scan plus a kernel ARP sweep; MAC maker (IEEE list), names via DNS, mDNS and NetBIOS; flags duplicate IPs. Enter on a device for actions |
| Find AV gear | Crestron (UDP autodiscovery: model, firmware, hostname), Extron (Telnet banner), Q-SYS (QDP announcements / QRC), Biamp (Tesira TTP), Shure (command port 2202), Netgear **AV Line only** (M4250/M4300/M4350/M4500 by mDNS, SNMP or web title). Shows open control ports |
| AV discovery | Dante devices (mDNS), Dante health, NDI sources, AES67/SAP streams (SDP: format, multicast address, PTP clock), PTP leader view, Multicast/IGMP, all mDNS services |
| Device login & info pull | Crestron: SSH (falls back to console 41795 for old gear) and pulls `VER`, `IPCONFIG`, `PROGCOMMENTS`, `UPTIME`, `IPTABLE` (never `ERRLOG`). Extron SIS (model, firmware, name, MAC, IP). Q-SYS QRC (`StatusGet`, design, components). Biamp Tesira (`DEVICE get ...`, faults). Shure (`< GET ... >`). Netgear AV Line: switch IP, then per port link/speed, PoE status and watts, and MACs with maker, matched to names from the last scan |
| Terminal | Hercules-style SSH / Telnet / TCP / UDP / serial (USB-RS232: baud, data bits, parity, stop bits). ASCII or HEX view and send, CR/LF/CRLF/none, Ctrl+C etc., saved command strings per device, log to the site report |
| Capture | Control-protocol sniffer: Crestron CIP joins, Crestron console, Q-SYS QRC/ECP, Extron SIS, PJLink (decoded). pcap capture to the site folder for Wireshark. Use a switch **mirror (SPAN) port**; inline bridging is not built |
| Network checks | DHCP rogue server check (sends a DISCOVER, lists every server that offers), IP conflict check (arping + duplicate scan), LLDP/CDP (switch, port, VLAN, PoE), link/cable errors (speed/duplex, error counters while pinging the gateway, TDR cable test where the chip supports it), control-port check |
| Site & reports | Set the site name. **S** on any result saves it to `~/TNT-Net-Reports/<site>/`. Browse saved reports on the device |

### Dante health

Watches the wired port (default `eth0`) for PTP and multicast:

- PTPv1 (Dante) and PTPv2 (AES67) leaders per domain, Sync rate, worst gap
- **Leader changes** with times, and **sync dropouts** (gaps over 3x normal), which go with clock errors
- More than one clock sending Sync in a domain (election fight, or two networks joined)
- IGMP querier present or missing, and which groups other devices joined
- **Multicast flooding**: multicast reaching this port that it never asked for, in Mb/s per group

## Keys

The CardputerZero's arrows are on the Fn layer: Fn+F up, Fn+X down, Fn+Z left, Fn+C right.
In lists (menus and results) F, X, Z and C work without Fn too, as do `;` and `.` for up/down.

| Key | Action |
| --- | --- |
| Up / Down | Move |
| OK (Enter) or Right | Open / run / pick a device |
| Esc or Left | Back one level (Esc quits from the main menu; Left does not) |
| Hold Esc | Exit the app (CardputerZero standard) |
| `1`-`9` | Jump to a menu item |
| OK or Right on a field | Start typing (highlight turns red). OK again keeps it, Esc puts the old text back |
| Z / C on a choice | Change the choice |
| `,` `/` | Scroll wide results sideways on the small screen |
| PgUp / PgDn, Home / End | Page through results |
| S / R / Q | Save to site report / run again / stop |

Keys are read straight from the CardputerZero keyboard, so they work whether or not the desktop
window has focus.

## Logins

Logins are typed on the keyboard and are **not saved** unless you set *Save this login* to Yes on
the login form. Saved logins are kept in `~/.config/tnt-av-net-tools/logins.json` (owner-only).
*Settings → Forget all saved logins* clears them.

## Notes

- The desktop window uses software drawing (`LIBGL_ALWAYS_SOFTWARE=1`): SDL's Wayland window
  surface crashes in the vc4 GPU driver on this device.
- Over Wi-Fi, many access points hide devices from ARP scans; plug into Ethernet for full lists.
  PTP, multicast and LLDP checks are meant for the built-in Ethernet port.
- Run `python3 -m tntnet.app` from `net-tools/` to try it on a Linux PC (keys come from the window).
