# TH-D75 CardputerZero beta validation

## Pairing correction, 0.1.0-2

The first hardware pairing attempt failed despite confirmation on both devices. BlueZ logged `Timed out waiting for reply from agent`. Instrumentation confirmed the app received the user's acceptance and invoked its reply callback, but the reply stalled behind the synchronous pairing request.

A fake peer on an isolated D-Bus session reproduced the timeout without touching Bluetooth or RF. Calling Pair and ConnectProfile asynchronously on the Bluetooth event loop fixes the callback round trip while the radio worker waits for completion. The regression fixture passed both acceptance and rejection. All four core suites passed again on the Zero.

Installed `rig-companion-zero_0.1.0-2_arm64.deb`, SHA-256 `78f651a779dc59260e19f1d57c554c546d51066b25faa4364aab58f76006915d`. Real-radio retest passed: BlueZ reports Paired, Bonded and Connected, and the user confirmed both VFOs appear. The LCD showed fresh CAT readback at 145.670000 MHz NFM on A and 9.490000 MHz AM on B. The saved radio is present and no restoration is pending. Pairing event logs omit pairing codes. Left the app connected. No RF transmission was performed; APRS/KISS/RadioMail and reconnection testing remain separate checks.

Device regression commands:

```sh
dbus-run-session -- python3 tests/dbus_roundtrip.py sync
dbus-run-session -- python3 tests/dbus_roundtrip.py
dbus-run-session -- python3 tests/dbus_roundtrip.py decline
```

The first command confirms the original synchronous callback failure; the other commands verify successful acceptance and explicit rejection.

## Initial build

Checked November 27, 2026. Package: `rig-companion-zero_0.1.0-1_arm64.deb`.

SHA-256: `1aacd5d77d99bc6daad609af6c4fa413101631416efd3ad1785e5320da802148`.

## Passed

- Four offline test suites passed on Windows and the physical CardputerZero. Cases cover split and escaped KISS streams, malformed-frame recovery, AX.25 and native TNC2 parsing, third-party APRS, weather, bounded persistent storage, frequency writes, simulated transmit, B.B. Link capabilities/QSY, exclusive session ownership, normal restoration and journal recovery.
- Additional device UI checks passed for all five page shortcuts, opening a position packet, saving it, replying to its sender including SSID, and entering F/Z/X/C and numeric keys as message text.
- The app found the CardputerZero keyboard without exclusive input capture.
- BlueZ registered the outgoing authenticated SPP profile without error.
- BlueZ accepted the GATT application and BLE advertisement, reporting `BLE ready as B.B. Link`.
- All rendered app screenshots are 320 × 170. Radio, traffic, inbox, weather, Link, packet detail, compose and disconnected screens were reviewed.
- The Debian package installed and upgraded successfully. It adds its own executable, library, icon and APPLaunch entry without replacing other apps.
- A bounded installed-app run displayed correctly on the actual RGB565 LCD and exited cleanly. The launcher was restored and active afterward. Direct framebuffer testing must pause the launcher to avoid its status overlay painting over the test app.
- The installed app reported approximately 58,324 KiB RSS (57 MiB). A two-second idle measurement used approximately 3.5% of one CPU core. These are brief idle measurements, not packet-load or long-session results.
- Package integrity matched after copying the Debian artifact back to the workspace.

## Still requires a connected TH-D75

No TH-D75 was discoverable or paired during this build. No radio setting was changed and no RF transmission occurred.

Validate pairing, both VFO readbacks, tuning and memory stepping, mode/power changes, native Menu 590 reception, KISS receive, APRS transmit, restoration after disconnect, and a RadioMail mail check. BLE registration alone does not prove phone interoperability or simultaneous Classic-radio/BLE-phone reliability.

Native APRS requires Menu 590 Raw Packets and Menu 982 Bluetooth. KISS requires Menu 983 Bluetooth. The app cannot retrieve the radio's historical stored inbox. Local APRS sends are unnumbered single packets without acknowledgment or retries.

Audio streaming, digital audio modems, a browser front panel and other radio models are outside this initial TH-D75 port. Store publication is pending author, share-code and license decisions plus physical-radio qualification. The manifest contains draft store metadata, not a completed submission.

## First device test

1. Open **Rig Companion** from the CardputerZero launcher.
2. End the TH-D75's other Bluetooth data session. On the radio, open Menu 934 Pairing Mode.
3. On the Zero, press **8** for Link, then Enter on **Find TH-D75 / pair**.
4. Select the discovered TH-D75. Compare the pairing numbers and accept on both devices.
5. Press **4** for Radio. Check both VFOs before attempting writes or enabling a bridge.

The app saves the selected radio and reconnects on later launches. BLE and TCP bridges default off and are enabled from Link. Use TCP KISS only on a trusted local network.


## Live APRS receive check

On November 27, 2026, the user confirmed APRS traffic and weather appeared on the Zero. Read-only inspection found 20 stored received packets at the first snapshot: seven Position, ten Packet/telemetry, one Message and two Weather records. The LCD explicitly showed KISS active, so this validates live KISS reception rather than native Menu 590 reception. Stations included N0KFB-11, N9UWY-1, W0ANA-15, KC9NVV-3 and N0HOY-10. Both weather records were from KF0ZH, reporting 43 F, 48% humidity, zero wind/gust and 1006.0 hPa. One received text message was saved in the inbox. The two weather records are two received packets from one station, not two weather stations. No radio settings or active session were changed during this check. APRS transmission, native APRS feed, RadioMail and session restoration still need separate qualification.
