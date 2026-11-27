# TNT Display Control

Part of the TNT (Tech Nomad Ted) tools, [TheTechNomad.com](https://TheTechNomad.com).
A pocket network remote for projectors and TVs on the M5Stack CardputerZero.

Package `tnt-display-control`, share code `TNTD`, Python package `tntdisp`
(standard library + pygame/numpy for the LCD). Runs as the normal user.

## What it does

* **Find displays**: SSDP, PJLink class 2 search and a port sweep of the local
  /24 (4352, 3001, 8001/8002, 8060, 80), then identifies each hit.
* **Per display**: power on/off, input list and switch, volume, mute,
  picture/AV mute, picture mode, on-screen message, info, Wake-on-LAN.
* **Rooms**: displays with the same Room name form a group: All on, All off
  (asks first), Mute, Unmute, with a per-display result list.
* Saved list in `~/.config/tnt-display-control/displays.json` (mode 600).

| Type | Protocol | Power | Input | Volume | Mute | Extras |
|---|---|---|---|---|---|---|
| PJLink class 1/2 | TCP 4352, MD5 password | on/off/warming/cooling | list (class 2 names) | class 2 only | AVMT audio | AV mute, lamp hours, error status, model, filter |
| LG webOS | WSS 3001, pairing key | off; on by WoL | list with labels | level | set | screen off, toast message, model |
| Sony Bravia | REST, X-Auth-PSK | on/off (WoL fallback) | list | level | set | picture mode, picture off |
| Samsung Tizen | WSS 8002 token / WS 8001 | key; on by WoL | HDMI1-4 keys | keys | toggle | model, power state |
| Roku TV | ECP HTTP 8060 | on/off | TV inputs | keys | toggle | model, serial |

Not yet: Android/Google TV (needs the remote-v2 pairing protocol) and LG
picture mode (webOS only allows it through a pop-up hack, which we avoid).

## Keys (official CardputerZero key spec)

F/X move, OK or C select, Z or ESC back, ESC on the main page quits, hold ESC
for HOME, Fn+H help. Number keys 4-8 (labels at the bottom):

* Main list: Find, Rooms, On, Off (highlighted display), Refresh
* Display: On, Off, Vol-, Vol+, Mute
* Room: All on, All off, Mute, Unmute
* Found list: Add all, Rescan (key 8)

## Display setup notes

* LG: Settings > General > Devices > TV management / "Turn on via Wi-Fi"
  (or Mobile TV On) for Wake-on-LAN power on. First connect asks on the TV;
  a key from `~/.lgtv_key` (earlier pairing on this device) is reused.
* Samsung: first connect asks on the TV (Allow). Power on needs network
  standby and the MAC.
* Sony: Network > IP control > Authentication: Normal and Pre-Shared Key.
  Turn on Remote start for power on over IP.
* Roku: Settings > System > Advanced > Control by mobile apps: Enabled.
* PJLink: enable it in the projector's network menu; enter its password if set.

## Command line (over SSH)

```
tnt-display-control --scan [--save]
tnt-display-control --list
tnt-display-control --do "LG TV" status|on|off|inputs|input HDMI_2|vol +2|mute on|info|message Hi
tnt-display-control --room Ballroom on|off|mute|unmute      # "all" = every display
tnt-display-control --wol 30:34:db:6e:bc:84
```

## Build and test

```
python3 -m unittest discover tests      # fake PJLink, Sony, Roku and LG servers
python3 scripts/make_assets.py          # store screenshots
bash scripts/build_deb.sh               # build/tnt-display-control_<ver>-1_arm64.deb
```
