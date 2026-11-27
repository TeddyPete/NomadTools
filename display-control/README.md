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
* **Remote**: the TV's menu buttons: arrows (F/X/Z/C or the arrow keys), OK,
  DEL = Back, and keys 4-8 Home, Back, Menu, Input, Exit. LG (pointer socket),
  Samsung (remote keys), Sony (IRCC codes) and Roku (ECP keys). PJLink has no
  menu navigation.
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

## Will it control my display? (Check a display)

Main list > **Check a display (IP)** (or `tnt-display-control --check IP`)
probes one address and lists each control method: **OK** (answers, ready),
**!** (answers but needs a password, key or setting) or **x** (off/missing).
It only reads greetings and status, so nothing shows on the display.

| Method | How it is checked |
|---|---|
| PJLink | TCP 4352 greeting: `PJLINK 0` = no password, `PJLINK 1` = password; class from `CLSS ?` |
| LG webOS | port 3001/3000 open (pairing can't be checked without the TV asking) |
| Samsung | `http://ip:8001/api/v2/` model and token support |
| Sony | `getInterfaceInfo` (no key needed), then `getPowerStatus` to see if a PSK is required |
| Roku | `/query/device-info` on 8060; TV or player; 403 = control disabled |

It also lists other control ports it sees (Telnet, NEC 7142, Epson 3629,
Panasonic 1024, Christie, Barco, Android TV, Cast) and the MAC for
Wake-on-LAN. Key 4 adds the display with what was found.

## Keys (official CardputerZero key spec)

F/X move, OK or C select, Z or ESC back, ESC on the main page quits, hold ESC
for HOME, Fn+H help. Number keys 4-8 (labels at the bottom):

* Main list: Find, Rooms, On, Off (highlighted display), Refresh
* Display: On, Off, Vol-, Vol+, Mute
* Remote: Home, Back, Menu, Input, Exit
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
