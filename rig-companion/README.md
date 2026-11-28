# Rig Companion for CardputerZero

Version 0.2.1 adds arrow-key navigation in the APRS lists and packet detail (0.2.0 added readable APRS reports and a station map). It uses the CYD project's
verified CAT conventions and KISS framing with Linux BlueZ, a keyboard UI and
SQLite storage. Pairing, both VFO readbacks and live KISS reception have been
checked on the user's TH-D75. RadioMail, APRS transmit and native APRS receive
still need qualification on this port.

## Connections

Open Link with **8**, choose **Find TH-D75 / pair**, then open Menu **934** on
the handheld. Select the discovered radio and compare the pairing numbers.
Confirm on both devices. The app remembers the chosen radio and reconnects.
Frequency and controls become available after an exact `ID TH-D75` response.

For native receive, enable APRS on the handheld, set Menu **590** to **Raw
Packets**, and Menu **982** to **Bluetooth**. For KISS set Menu **983** to
**Bluetooth**. The radio's existing USB/Bluetooth menu destinations are set
on the handheld. The app does not claim a CAT command for those menu entries.

## Keys

The keys below the screen switch pages, **4 Radio**, **5 APRS**, **6 Inbox**,
**7 Weather**, **8 Link**. Arrow keys and F/Z/X/C navigate outside editors.
Inside an editor all printable keys enter text. Esc backs out. Esc from Radio
opens exit confirmation, and the app restores an active KISS session on exit.

On Radio, up/down tunes or steps populated memory channels. Enter opens MHz
entry, Tab selects A/B, M cycles mode, P cycles power, V toggles VFO/memory,
D toggles dual receive, S cycles squelch, and J/K changes volume. **?** shows
the control guide. Readback is required after changes.

On APRS/Inbox/Weather, Up/Down move, Right or Enter opens the selected packet,
Left backs out, N opens compose, K starts or ends KISS, and S switches
live/saved packets on the APRS page. In packet detail Up/Down scroll and Left
backs out; the bottom keys are **4 Back**, **5 Map**, **6 Save**, **7 Reply**,
**8 Raw** (switches between readable and raw content). Every received
sender can be used as an APRS recipient. Messages and packets carry the Zero's
UTC receive timestamp. Clock accuracy follows the device's system clock.

Set your licensed callsign and SSID under **Link > Callsign**. Compose pre-fills
From, and Reply pre-fills To. Tab switches between recipient and body. Enter
starts KISS if needed, then opens a send confirmation. Enter in that confirmation
sends one packet. Local messages have no automatic retry or delivery receipt.
Use the displayed frequency to confirm the intended APRS channel before sending.

Native and KISS receive share the same stored inbox. Up to 500 distinct text
messages, 500 saved packets, and 2000 recent unsaved packets are retained in
`~/.config/rig-companion-zero/station.sqlite3`. Native messages are captured
as received. Older records held only by the handheld cannot be downloaded.

## Packets from Nomad SDR

Nomad SDR's APRS receiver (an RTL-SDR on 144.390) writes every packet it decodes
into the same store, so they show up in the APRS list, inbox, weather page and
map next to the TH-D75's packets. Since 0.2.4 the map also refreshes while both
apps are running.

## Readable reports and map

Positions, compressed positions, Mic-E, objects/items and PHG site information
get readable details. Telemetry displays each channel and digital bits. When a
station sends its own PARM/UNIT/EQNS/BITS definitions, the app remembers labels
and calibration for up to 128 stations. Until calibration arrives, values are
explicitly marked raw. Telemetry setup packets are classified separately from
personal messages. Previously stored packets are decoded again on upgrade,
retaining their IDs, raw content, receive timestamps and saved flags.

Press **T** in a packet detail to switch between readable and raw content.
Press **M** from APRS, Inbox, Weather or packet detail to open the map. The map
starts near the most recent station or the opened position report. It shows
up to 128 known stations and the selected station's last 16 distinct positions.
On the map, the bottom keys are **4 Back**, **5 Zoom -**, **6 Zoom +**,
**7 Next station**, **8 Open details**. Arrow keys pan; Tab cycles stations;
**A** fits all stations and **R** centers the selected station. Existing
Save and Reply actions work from the station's packet details.

Map tiles are © OpenStreetMap contributors. Compact attribution stays in the
map's top bar. Press I on the map, or Link > Map data licences, for the data
source, ODbL licence and copyright URL. Only visible tiles are requested,
with a dedicated background worker and HTTP caching. The disk cache holds up
to 256 tiles, with at least seven-day retention unless HTTP headers specify
otherwise. Closing the map pauses further requests. Previously viewed areas
work offline; unvisited offline areas show markers without geographic detail.
Map requests disclose the viewed map area and public IP to the tile provider.
The owner authorized OpenStreetMap requests for this device on 2026-11-27.
No aprs.fi API, code or historical database is used. Sources and third-party
licenses are recorded in `THIRD-PARTY.md` and bundled with the package.

## Optional phone and PC bridges

**Link > BLE phone bridge** advertises **B.B. Link** using the BLE KISS UUIDs.
The TX characteristic accepts writes with and without response. Notifications
use 20-byte chunks compatible with the default ATT MTU. The bridge implements
the B.B. Link frequency/rate and restore extension for RadioMail. Phone
subscription starts KISS. This first version needs a live iPhone qualification.

**Link > TCP KISS / 8001** enables a single TCP client on port **8001**. Use a
trusted local network. A client connection starts KISS. Local compose, BLE and
TCP share one radio session owner. On disconnect the app restores the saved
radio state. Stop a local KISS session before connecting a phone or PC.

Before KISS, the app persists the TNC mode, VFO record, channel mode and rate.
It verifies restoration after exit. Unplugging or power loss leaves a recovery
record which is retried after the same saved radio reconnects. Errors remain
visible and radio changes are blocked until restoration succeeds.

## Build and run

Runtime dependencies are Debian's `python3-pygame`, `python3-numpy`,
`python3-dbus`, `python3-gi`, `python3-pil`, `bluez`, and `fonts-dejavu-core`. The app runs as
the logged-in user, who needs normal input, video and Bluetooth permissions.

```sh
python3 -m unittest discover -s tests -v
python3 -m rigzero --preview previews
python3 package.py
sudo dpkg -i dist/rig-companion-zero_0.2.4-1_arm64.deb
rig-companion-zero
```

The Debian package adds a **Rig Companion** launcher entry. `--status` reports
stored setup and recovery state without opening the radio. `--seconds N`
limits a launch for display testing. `--preview FOLDER` renders clearly
illustrative screens without using Bluetooth. Only one live instance can run.

This release does not include audio streaming, digital audio modems, a web
front panel, or profiles for other radio models. Package publication, account,
share code and store submission are separate release decisions. No store
submission is performed by the build script.

Sources checked 2026-11-27 include the
[BlueZ profile](https://bluez.readthedocs.io/en/latest/profile-api/),
[GATT](https://bluez.readthedocs.io/en/latest/gatt-api/) and
[advertising](https://bluez.readthedocs.io/en/latest/advertising-api/) APIs,
the [BLE KISS API](https://github.com/hessu/aprs-specs/blob/master/BLE-KISS-API.md),
and our CYD/TH-D75 hardware findings in the sibling project.


## About and licence

Link > **About Rig Companion** (or **A** inside the **?** guide) shows the
standard Nomad About screen: name, version, licence, Developed by TheTechNomad,
www.TheTechNomad.com with a QR code, and github.com/TeddyPete.

Rig Companion is part of NomadTools by TheTechNomad and is licensed under the
GNU General Public License v3.0 only (GPL-3.0-only), see `../LICENSE`.
Bundled third-party files keep their own MIT and Apache-2.0 licences, listed in
`THIRD-PARTY.md` with full texts in `licenses/`.
