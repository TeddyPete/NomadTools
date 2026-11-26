# TNT Packet Capture

Pocket packet capture for AV networks on the M5Stack CardputerZero.
Part of the TNT (Tech Nomad Ted) tools, [TheTechNomad.com](https://TheTechNomad.com).

Plug the CardputerZero's Ethernet port into a switch **mirror (SPAN) port**, pick a
filter, start, and get a `.pcap` you can open in Wireshark. On a normal switch port you
only see broadcast, multicast and the device's own traffic.

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
- **Share over network:** a read-only web page (port 8080) listing the captures for
  download from a laptop browser. On only while you have it switched on in the app.

Files are in `~/TNT-Captures/` named like `20261126-140312_Dante_eth0.pcap`, each with a
`.pcap.json` note (filter, port, length, packets, drops, why it stopped).

## Keys (TNT standard)

Up/Down (or plain F/X) move, OK or Right selects, Esc goes back and quits on the main
page. In settings OK/Right starts editing a field (red), OK saves, Esc cancels.
Hold Esc to go to the launcher.

## Command line (over SSH)

```
tnt-packet-capture --start --preset dante --seconds 300 --mb 200
tnt-packet-capture --start --filter "host 192.168.1.50 and tcp port 41794"
tnt-packet-capture --status
tnt-packet-capture --stop
tnt-packet-capture --list
tnt-packet-capture --presets
```

## How it works

The app starts a small supervisor process that runs `tcpdump -w` straight to the file,
so the screen can never slow the capture down. The supervisor asks tcpdump for counts
once a second (SIGUSR1), enforces the limits, and writes a state file in
`$XDG_RUNTIME_DIR/tnt-packet-capture/`. The live protocol breakdown reads the growing
file and skips ahead (marked "sample") when traffic is too fast to read it all.

The package gives `/usr/bin/tcpdump` capture rights with `setcap` (the same as TNT AV
Net Tools), so nothing runs as root. Note this lets any local user run tcpdump.

## Build

```
cd pcap-capture
python3 tests/test_basic.py        # capture tests need root (or setcap tcpdump)
python3 scripts/make_assets.py     # icon + store screenshots
bash scripts/build_deb.sh          # build/tnt-packet-capture_<ver>_all.deb
sudo apt install ./build/tnt-packet-capture_*_all.deb
```

Store listing data is in `app-builder.json` (share code TNTP).
