# TNT AV Tester

HDMI test patterns and audio test tones for the CardputerZero, run from the keyboard with
status on the built-in screen. Lip-sync measurement, EDID reader, SPL meter, saved reports
and a phone/web page for reports come next.

## Install as a launcher app (on the CardputerZero)

The app installs like a Store app: it appears on the HOME screen as **TNT AV Tester**.

```bash
git clone https://github.com/TeddyPete/ZeroAVTools.git
cd ZeroAVTools/av-tester
sudo apt install python3-pygame python3-numpy dpkg-dev
./scripts/build_deb.sh                        # -> build/tnt-av-tester_<ver>_all.deb
sudo apt install ./build/tnt-av-tester_*_all.deb
```

Open **TNT AV Tester** from HOME. Hold Esc for 2 s (or press Q) to return to the launcher.

If the Pi desktop is running on HDMI, TNT AV Tester pauses it while it runs so it can set HDMI
resolution and refresh itself, then starts the desktop again when you quit. A reboot always
brings the desktop back. To keep the desktop up and show patterns in a window on it instead,
set `ZEROAV_KEEP_DESKTOP=1`. The package installs a small polkit rule
(`/usr/share/polkit-1/rules.d/60-tnt-av-tester.rules`) that lets local users in the `video`
group stop and start `lightdm.service` only, with no password.
Uninstall with `sudo apt remove tnt-av-tester`.

## Publishing to the CardputerZero Store

`app-builder.json` holds the Store listing (summary, category, screenshots, icon, license,
share code `TNTA`, permissions). To publish, use M5Stack's
[AppBuilder](https://github.com/CardputerZero/AppBuilder) `czdev` tool from this folder:

```bash
./czdev login                                          # GitHub device login, once
./czdev publish --deb build/tnt-av-tester_<ver>_all.deb  # opens a review PR
```

An M5Stack admin reviews and merges; then it shows in the Store.
Regenerate the icon and screenshots with `python3 scripts/make_assets.py`.

## Install for development

## First: check the device

```bash
./scripts/device_check.sh > device_report.txt 2>&1
```

This lists HDMI modes, the connected display's EDID, audio devices and camera modes.
Nothing is changed.

## Run from a shell (development)

Stop the launcher first (`systemctl --user stop APPLaunch.service`), connect an HDMI display, then:

```bash
python3 -m zeroav.app                                  # display's preferred mode
python3 -m zeroav.app --size 1280x720                  # pick a resolution
python3 -m zeroav.app --audio-device default          # pick a tone output (default: HDMI audio)
```

## Keys

| Key | Action |
| --- | --- |
| Right / Down / Space / `.` / `n` | Next pattern |
| Left / Up / `,` / `p` | Previous pattern |
| `1`-`7` | Jump to category: bars, geometry, gradients, solids, sharpness, motion |
| `t` | Audio out (HDMI): off, 1 kHz both, L/R alternating, left only, right only, pink noise, 20 Hz-20 kHz log sweep (10 s), polarity pulse |
| `+` / `-` | Tone level, 2 dB steps (starts at -20 dBFS) |
| `i` | Info overlay: resolution, refresh, measured fps, frame counter |
| `m` | Next HDMI mode: every mode the display offers, with exact refresh (1080p60, 1080p59.94, 1080p50, 1080p23.98, ...) |
| `e` | Display EDID: maker, model, serial, build date, size, native mode, all modes, audio, HDR, color depth. Shown on HDMI and, scrollable, on the small screen |
| `e` view: Up / Down | Scroll the small screen |
| `e` view: Left / Right | Turn the HDMI page when it doesn't all fit |
| `e` view: `s` | Save the EDID report (text plus raw `.bin`) to `~/.local/share/tnt-av-tester/reports/` |
| `l` | Lip-sync test (see below) |
| `a` | Audio input meter and 1/3-octave RTA from the mic, on HDMI and the small screen (see below) |
| `q` / Esc | Quit |

## Audio meter and RTA

Press `a`. The mic's level (RMS, peak, Leq, max) and 31-band 1/3-octave RTA show on HDMI and the
small screen. Play pink noise with `t` to check a room or EQ; the RTA reads flat for flat pink noise.

- `w` switches A and Z (flat) weighting. `r` resets max and Leq. `s` saves a report.
- SPL needs a one-time calibration: with a calibrator or a reference meter next to the
  CardputerZero, press `+` / `-` until the SPL matches. It is saved in
  `~/.config/tnt-av-tester/spl.json`. Until then SPL reads "uncal" and levels are dBFS.
- Polarity pulse: a sharp positive-going pulse twice a second, for a polarity checker.

## Lip-sync test

Press `l`, aim the CardputerZero's camera at the screen and put it near the speakers, then press
Enter. The screen flashes white with a 1 kHz beep about ten times. The camera (200 fps) and mic time
each one and the small screen shows the offset (+ = audio late), ATSC and EBU R37 pass/fail, and the
fix. The fix leaves audio about 12 ms late, since late audio is far less noticeable than early audio.

- `c` after a run on a system you trust to be in sync stores that run as the zero point
  (`~/.config/tnt-av-tester/lipsync.json`). Do this once; it removes the camera and audio delays
  inside the CardputerZero itself. Until then results show "not calibrated".
- `s` saves a report with every flash to `~/.local/share/tnt-av-tester/reports/`.
- `python3 -m zeroav.lipsync` checks the camera frame rate and mic level without HDMI.

## Patterns

Color bars 75% and 100% (with PLUGE), crosshatch 16 and 32, safe-area frame, gray and RGB ramps,
16-step gray, solids (white, black, 50% gray, R, G, B), 1 px and 64 px checkerboard, moving box with
frame-counter strip for judder.

Preview all patterns as PNG files without a display:

```bash
python3 -m zeroav.app --render-dir out --size 1920x1080
```

## Known limits

- No 4K. The CardputerZero's HDMI (Pi VC4) tops out at a 162 MHz pixel clock, which is 1080p60.
  Ultrawide 2560x1080 works at 24, 25 and 30 Hz when the display lists those modes; 50 and 60 Hz
  need more than 162 MHz. The EDID view marks modes that are too fast in red.
- Only modes the display's EDID lists can be selected (no custom timings yet).
- The Pi's HDMI output has no HDCP.
