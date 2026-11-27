# Nomad Packet Capture

Pocket packet capture for AV networks on the M5Stack CardputerZero.
Part of the Nomad tools by Tech Nomad Ted, [TheTechNomad.com](https://TheTechNomad.com).

Two ways to see the traffic, both saving a `.pcap` you can open in Wireshark:

- **Mirror port:** plug the Ethernet port into a switch mirror (SPAN) port. On a normal
  switch port you only see broadcast, multicast and the device's own traffic.
- **Inline tap:** plug a USB Ethernet adapter in and put the CardputerZero in the cable
  between two devices. The built-in port and the adapter are bridged as an invisible
  wire (no IP address, IPv6 off, no spanning tree, 802.1X/EAPOL and LLDP forwarded) and
  everything that passes is recorded. Max 100 Mb/s (the built-in port's speed). With
  **Auto tap** on (default) plugging the adapter in bridges and starts a capture by itself,
  even when the app is closed; unplugging it stops the capture and gives the built-in
  port back to NetworkManager. Stopping a capture leaves the bridge up, so the two
  devices stay connected. Wi-Fi is never touched (SSH over Wi-Fi keeps working), and the
  app refuses to bridge a port that carries the device's own default route.

## What it does

- **Filter presets:** Everything, Dante (all), Dante control (no audio), PTP clock,
  AES67 / RTP / SAP, NDI, Control systems (Crestron CIP, Q-SYS QRC, Extron SIS, PJLink,
  Shure, Yamaha, Telnet, SSH, web), Multicast / IGMP, ARP / DHCP / broadcast,
  Discovery (mDNS, SSDP, LLDP, CDP), or a custom tcpdump filter.
  Host IP and Port filters add on top of any preset.
- **Limits:** stop after a time (30 s to 24 h) and/or a size (10 MB to 4 GB), or keep a
  **ring buffer** of the last N MB (10 files) for waiting on an intermittent fault.
  Captures always stop when the card has less than 150 MB free.
- **Headers only** option (128 bytes per packet) for long Dante captures.
- **Live view:** packets, size, packet rate and bit rate, kernel drops, time left, a
  protocol breakdown (Dante audio, PTP, mDNS, Crestron CIP, ...) and top senders.
- **Runs in the background:** a capture keeps going if you leave the app (you're asked
  first) and still stops at its limits. Open the app again to watch or stop it.
- **Saved captures:** list, protocol summary, copy to a USB drive, delete.
- **Getting files off (Nomad standard):** *Share files* shows a QR code and address for a
  web page (port 8080) that lists every capture, including one still recording, to
  download or delete from a phone or laptop browser. Plug in a USB stick and the app
  offers to copy the captures that aren't on it yet (folder `Nomad-Captures`); *Saved
  captures* also has *Copy all to USB* and *Clear all captures* (asks twice).
- **Power-loss safe:** tcpdump writes each packet as it arrives and the file is synced to
  the SD card every 5 s, so a power cut loses only the last few seconds. Ring-buffer
  pieces left behind are renamed to `.pcap` on the next start.
- **HDMI live viewer:** with HDMI and the desktop up, a window opens on the desktop for
  each capture: scrolling packet list, protocol bars, top senders, and details + hex of a
  clicked packet. The CardputerZero keyboard types into whatever has focus, so the
  viewer is mouse-only; set its filter on the small screen (*Filter > Desktop view
  filter*, e.g. `ptp !follow_up`). It is light enough for the CM0's 352 MB RAM; for full
  decoding open the file in Wireshark on a PC.

Files are in `~/Nomad-Captures/` named like `20261126-140312_Dante_eth0.pcap`, each with a
`.pcap.json` note (filter, port, length, packets, drops, why it stopped).

## Keys (Nomad standard)

Up/Down (or plain F/X) move, OK or Right selects, Esc goes back and quits on the main
page. In settings OK/Right starts editing a field (red), OK saves, Esc cancels.
Hold Esc to go to the launcher.

## Command line (over SSH)

```
nomad-packet-capture --start --preset dante --seconds 300 --mb 200
nomad-packet-capture --start --filter "host 192.168.1.50 and tcp port 41794"
nomad-packet-capture --start --tap           # inline tap with the first USB adapter
nomad-packet-capture --viewer                # open the desktop viewer
nomad-packet-capture --status
nomad-packet-capture --stop
nomad-packet-capture --list
nomad-packet-capture --presets
```

## How it works

The app starts a small supervisor process that runs `tcpdump -w` straight to the file,
so the screen can never slow the capture down. The supervisor asks tcpdump for counts
once a second (SIGUSR1), enforces the limits, and writes a state file in
`$XDG_RUNTIME_DIR/nomad-packet-capture/`. The live protocol breakdown reads the growing
file and skips ahead (marked "sample") when traffic is too fast to read it all.

Inline tap: `/usr/lib/nomad-packet-capture/tap-helper` (root) makes the bridge `br-nomad`,
run by `nomad-packet-capture-tap@<adapter>.service`, which is bound to the adapter so
unplugging it takes the bridge down. A polkit rule lets the netdev group start/stop that
unit only. A udev rule starts `nomad-packet-capture-autotap@<iface>.service` (as user pi)
for USB network adapters; it does nothing unless Auto tap is on.

The package gives `/usr/bin/tcpdump` capture rights with `setcap` (the same as Nomad AV
Net Tools), so nothing runs as root. Note this lets any local user run tcpdump.

## Build

```
cd pcap-capture
python3 tests/test_basic.py        # capture tests need root (or setcap tcpdump)
python3 scripts/make_assets.py     # icon + store screenshots
bash scripts/build_deb.sh          # build/nomad-packet-capture_<ver>_all.deb
sudo apt install ./build/nomad-packet-capture_*_all.deb
```

Store listing data is in `app-builder.json` (share code NMPC).
