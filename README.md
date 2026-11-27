# ZeroAVTools: the Nomad apps

Field tools for AV work on the [M5Stack CardputerZero](https://docs.m5stack.com/en/CardputerZero),
a pocket Raspberry Pi CM0 Linux handheld with HDMI out, a camera, a mic and a keyboard.
The **Nomad** apps are by Tech Nomad Ted, [TheTechNomad.com](https://TheTechNomad.com).

| App | Folder | Package | Share code |
| --- | --- | --- | --- |
| Nomad AV Tester: HDMI test patterns, tones, EDID, lip-sync, audio meter | [`av-tester/`](av-tester/) | `nomad-av-tester` | NMAV |
| Nomad Net Tools: find AV gear, Dante/NDI, PTP, terminal, NVX setup, reports | [`net-tools/`](net-tools/) | `nomad-net-tools` | NMNT |
| Nomad WiFi Share: Wi-Fi to Ethernet, hotspot, guest Wi-Fi login | [`wifi-share/`](wifi-share/) | `nomad-wifi-share` | NMWF |
| Nomad Packet Capture: mirror-port or inline-tap pcap | [`pcap-capture/`](pcap-capture/) | `nomad-packet-capture` | NMPC |
| Nomad Display Control: power, input and volume for TVs and projectors | [`display-control/`](display-control/) | `nomad-display-control` | NMDC |

Each app lives in its own folder with its own README and install steps.

These apps used to be called "TNT ..." (packages `tnt-*`). Each Nomad package replaces
its old `tnt-*` package when installed, and the app moves its old settings
(`~/.config/tnt-*`, `~/TNT-Captures`, `~/TNT-Net-Reports`) to the new names the first time it starts.

Icons come from [`branding/nomad_icons.py`](branding/nomad_icons.py)
(`python3 branding/nomad_icons.py --style labeled --out DIR`).
