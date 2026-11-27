# TNT WiFi Share

Part of the TNT (Tech Nomad Ted) tools, [TheTechNomad.com](https://TheTechNomad.com).
Gets a standalone AV rack online from the M5Stack CardputerZero, all from its keyboard and screen.

## Two modes

| Mode | What it does |
| --- | --- |
| **Wi-Fi to Ethernet** | Shares the Wi-Fi internet out of the Ethernet port to a switch (NAT). DHCP server on by default; turn it off for static networks and set the gear's gateway to the Pi's address. Optional 802.1Q VLAN tag for a trunk or tagged switch port. |
| **Hotspot from Ethernet** | Shares a wired connection as a WPA2 Wi-Fi hotspot (2.4 GHz, channel 1, 6 or 11). **Own network** (the Pi hands out addresses, NAT) or **Bridge** (Wi-Fi devices join the wired network itself and get its DHCP, no NAT). The uplink can use DHCP or a static IP. |

## Screens (LCD + keyboard)

- **First-run setup wizard**: pick the job, join Wi-Fi, choose DHCP or static gear, start. Runs again from Settings.
- **Status**: mode, internet (online / login page / offline), Wi-Fi SSID, signal and IP, Ethernet link and IP, VLAN, VPN, client count.
- **Dashboard**: live download / upload graph for the last minute, Wi-Fi signal and bit rate, Ethernet link speed, gateway ping and loss, internet check.
- **Share Wi-Fi to Ethernet** / **Hotspot from Ethernet**: start or stop a mode.
- **Join Wi-Fi**: scan, pick, type the password. Hidden networks too. `D` forgets a saved network.
- **Guest Wi-Fi login**: finds the captive portal page. Simple pages (accept terms, room number, email) are filled in on the small screen. Anything that needs JavaScript opens in a browser on the HDMI desktop (`H`).
- **Devices**: everything on the shared side with its maker (from the MAC). Rename, block internet (key 4), fixed IP (DHCP reservation), download and upload speed limits. Devices you set up stay listed when unplugged.
- **Switch port (LLDP)**: switch name, port, port VLAN, VLAN name and switch IP (Netgear AV Line and most managed switches). Updates by itself while sharing to Ethernet; otherwise key 4 listens for 35 s.
- **VPN (WireGuard)**: send the shared devices (and the Pi) out through your WireGuard server. Load the `.conf` from a phone or laptop (QR code web page) or a USB stick.
- **Settings**: Ethernet side (address, mask, DHCP, VLAN tag, LLDP, hotspot uplink), Hotspot (SSID, password, channel, NAT or bridge), DHCP reservations (add gear by MAC before it's plugged in), Port forwards (uplink port to a device's IP and port, TCP/UDP), Local DNS names (like `dsp1.av`), Speed limit for all devices, Setup wizard.
- **Stop sharing**: back to the normal network.

Changes to devices, reservations, forwards, names and limits load straight into a running share. Reservations and names restart the Pi's DHCP server, which blips the shared side for a second.

Keys and colors (TNT standard, same in every TNT app; the shared code is `tntshare/tntui.py`):

| Key on the CardputerZero | Does |
| --- | --- |
| F / X (no Fn needed), or Fn+F / Fn+X | Up / Down |
| OK, or C / Fn+C (Right) | Open, select, or start editing a field |
| Z / Fn+Z (Left) | Back one level |
| ESC/HOME, short press | Back one level; on the main page, quit (asks first only while sharing). Hold it to exit to HOME. |
| 1-8 | Jump to a menu item |

The title bar is green and the highlighted row is blue. Editing happens right in the list: OK (or Right) on a
field turns the row red and every key types, including F/X/Z/C. OK saves the field and gives the arrow letters
back; ESC cancels the edit. Fn+Z / Fn+C move the cursor, DEL deletes. On On/Off and choice rows OK just flips
the value. IP fields only take digits and dots.
Dots, dashes and other symbols come from the Sym layer as printed on the keys (Sym+B = `.`, Sym+R = `-`, Sym+N = `/`).

## Safe by design

- Every connection the app creates is in-memory only (`nmcli ... save no`), named `tnt-share-*`. **A reboot always brings back the normal network.**
- Before changing an interface the app records what was active on it. Quitting (Esc on the home screen, the launcher closing it, or a crash, via the launcher wrapper) removes the app's profiles, stops NAT and reconnects what was there before.
- The app itself never runs as root. NAT, IP forwarding, device blocks, speed limits, port forwards, DHCP reservations and local names are loaded by one small root helper, `/usr/lib/tnt-wifi-share/net-helper`, run only by `tnt-wifi-share-nat@<iface>.service`. That unit is never enabled at boot. The app writes its rules to `/run/tnt-wifi-share-policy/` (group `netdev`) and the helper checks every value (MAC, IPv4, port, number, host name) before use. Rules only touch traffic on the shared side. `ip_forward` is put back to its old value and the dnsmasq file is removed when sharing stops.
- Bridge mode and VLAN profiles are in-memory too. A WireGuard config is imported only while the VPN is on, with autoconnect off, and deleted when it goes off or the app quits.
- Joined Wi-Fi networks are saved like any other Wi-Fi network, so you don't retype guest passwords.
- A polkit rule (`/usr/share/polkit-1/rules.d/60-tnt-wifi-share.rules`) lets `netdev` users manage NetworkManager and start, reload or stop the NAT unit without a password, and lets `video` users start the desktop to show a portal page. Nothing else is allowed.

Careful when working on the Pi remotely: the hotspot takes over the Wi-Fi radio, so an SSH session over Wi-Fi drops while it runs. Mode 1 takes over the Ethernet port.

## Command line (over SSH)

```bash
tnt-wifi-share --status      # JSON status
tnt-wifi-share --check       # internet / captive portal check
tnt-wifi-share --restore     # undo anything the app changed
# Start a mode without the UI and restore it automatically after N seconds:
setsid nohup tnt-wifi-share --start hotspot --revert-after 90 > /tmp/tnt-share-test.log 2>&1 &
```

## Build and install

```bash
cd wifi-share
./scripts/build_deb.sh                # -> build/tnt-wifi-share_<ver>-1_arm64.deb
sudo apt install ./build/tnt-wifi-share_*_arm64.deb
```

Needs NetworkManager, `dnsmasq-base`, `nftables`, `iw` (all on the stock image) and `python3-pygame`.
Settings are kept in `~/.config/tnt-wifi-share/settings.json`; the hotspot gets a random password on first run.

Tests (offline): `python3 -m unittest discover tests`. Store screenshots and icon: `python3 scripts/make_assets.py`.

## Limits

- Hotspot is 2.4 GHz only and replaces the Wi-Fi client connection (the radio can do both only on one channel; not used yet).
- Enterprise (802.1X) Wi-Fi isn't supported yet.
- With DHCP off in mode 1 the Pi doesn't answer DNS; give the gear a public DNS server such as 1.1.1.1. Local DNS names need DHCP on.
- Blocks, limits and forwards apply in NAT modes; a bridged hotspot passes traffic straight through.
- Speed limits drop traffic over the limit (policing), which works well for TCP downloads and streams.
- LLDP only (NetworkManager); CDP-only switches show nothing.
