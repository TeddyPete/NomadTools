# AV tester

HDMI test patterns and audio test tones for the CardputerZero, run from the keyboard with
status on the built-in screen. Lip-sync measurement, EDID reader, SPL meter, saved reports
and a phone/web page for reports come next.

## Install (on the CardputerZero)

```bash
git clone https://github.com/TeddyPete/ZeroAVTools.git
cd ZeroAVTools/av-tester
./scripts/install.sh
```

## First: check the device

```bash
./scripts/device_check.sh > device_report.txt 2>&1
```

This lists HDMI modes, the connected display's EDID, audio devices and camera modes.
Nothing is changed.

## Run

Run from the console (not inside a desktop session), with an HDMI display connected:

```bash
python3 -m zeroav.app                                  # display's preferred mode
python3 -m zeroav.app --size 1280x720                  # pick a resolution
python3 -m zeroav.app --audio-device hdmi:CARD=vc4hdmi # tones to HDMI audio
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
