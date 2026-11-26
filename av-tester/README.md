# AV tester

HDMI test patterns and audio test tones for the CardputerZero, run from the keyboard with
status on the built-in screen. Lip-sync measurement, EDID reader, SPL meter, saved reports
and a phone/web page for reports come next.

## Install as a launcher app (on the CardputerZero)

The app installs like a Store app: it appears on the HOME screen as **AV Tester**.

```bash
git clone https://github.com/TeddyPete/ZeroAVTools.git
cd ZeroAVTools/av-tester
sudo apt install python3-pygame python3-numpy dpkg-dev
./scripts/build_deb.sh                        # -> build/zeroav-tester_<ver>_all.deb
sudo apt install ./build/zeroav-tester_*_all.deb
```

Open **AV Tester** from HOME. Hold Esc for 2 s (or press Q) to return to the launcher.
Uninstall with `sudo apt remove zeroav-tester`.

## Publishing to the CardputerZero Store

`app-builder.json` holds the Store listing (summary, category, screenshots, icon, license,
share code `ZAVT`, permissions). To publish, use M5Stack's
[AppBuilder](https://github.com/CardputerZero/AppBuilder) `czdev` tool from this folder:

```bash
./czdev login                                          # GitHub device login, once
./czdev publish --deb build/zeroav-tester_0.1.0_all.deb  # opens a review PR
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
python3 -m zeroav.app --audio-device pipewire         # tones through PipeWire (default when present)
```

## Keys

| Key | Action |
| --- | --- |
| Right / Down / Space / `.` / `n` | Next pattern |
| Left / Up / `,` / `p` | Previous pattern |
| `1`-`7` | Jump to category: bars, geometry, gradients, solids, sharpness, motion |
| `t` | Tone: off, 1 kHz both, L/R alternating, left only, right only |
| `+` / `-` | Tone level, 2 dB steps (starts at -20 dBFS) |
| `i` | Info overlay: resolution, refresh, measured fps, frame counter |
| `m` | Next HDMI resolution |
| `q` / Esc | Quit |

## Patterns

Color bars 75% and 100% (with PLUGE), crosshatch 16 and 32, safe-area frame, gray and RGB ramps,
16-step gray, solids (white, black, 50% gray, R, G, B), 1 px and 64 px checkerboard, moving box with
frame-counter strip for judder.

Preview all patterns as PNG files without a display:

```bash
python3 -m zeroav.app --render-dir out --size 1920x1080
```

## Known limits

- HDMI refresh rate follows the mode the system boots with; the overlay shows the measured fps.
  Per-mode refresh switching comes after the device check confirms what the HDMI output supports.
- The Pi's HDMI output has no HDCP.
