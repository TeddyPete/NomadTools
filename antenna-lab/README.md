# Ask Elmer Antenna Lab

From [Ask Elmer](https://askelmer.com). A pocket antenna modeling lab for the M5Stack CardputerZero,
running the NEC2 engine (`nec2c`) on the device. Port of the Antenna Lab in the Ask Elmer web app.

Package `askelmer-antenna-lab`, share code `AEAL`, Python package `elmerlab`
(pygame and numpy for the LCD, `nec2c` for the electromagnetics). Runs as the normal user.

## What it does

* **18 antennas**: half-wave dipole, inverted V, OCFD, end-fed half wave, fan dipole, trap dipole,
  G5RV / ladder-line doublet, ground-mounted vertical (MININEC-style ground with radial loss),
  elevated ground plane, 5/8-wave vertical, coil-loaded short vertical, J-pole, Yagi (2-10
  elements), Moxon, cubical quad, delta loop, horizontal sky loop, small magnetic loop.
* **Design**: frequency, sizes in feet or metres, height, wire or tubing, matching device
  (1:1 choke, 4:1 balun, 49:1 / 64:1 EFHW transformer, 9:1 unun, 75 ohm Q-section, tuner).
* **Run (4)**: feed impedance, SWR into 50 ohm through the matching device, resonance, lowest SWR,
  2:1 bandwidth, gain in dBi and takeoff angle, front-to-back, beamwidth, polarization, efficiency.
* **Tune (5)**: adjusts the main size (length, coil, capacitor and coupling loop, size trim) until
  the antenna is resonant or has the lowest SWR.
* **SWR (6)**: SWR across the band with the band edges; Wide (5 on that screen) sweeps far
  enough to see a multiband wire's other bands.
* **Pattern (7)**: azimuth and elevation cuts through the main lobe.
* **Cut (8)**: what to cut and build, with coil recipes for traps and loading coils.
* Ground and conductor material in Settings; every antenna remembers its last design in
  `~/.config/askelmer-antenna-lab/state.json`.

## Command line (over SSH)

```
askelmer-antenna-lab --list
askelmer-antenna-lab --run moxon --mhz 14.2 --tune
askelmer-antenna-lab --deck dipole --mhz 7.15     # the NEC2 deck
askelmer-antenna-lab --screens /tmp/shots         # render the LCD screens to PNG
```

## Build

```
python3 scripts/make_icon.py "ANTENNA LAB" packaging/icon.png packaging/icon_100.png
bash scripts/build_deb.sh            # build/askelmer-antenna-lab_<ver>-1_arm64.deb
python3 -m pytest tests              # needs nec2c installed
```

## Not yet

* NanoVNA sweep overlaid on the model's SWR curve (USB serial).
* The 3D wire view and full-size charts on an HDMI monitor.
* Optimizer for beams (gain / front-to-back) and coax loss to the shack.

## Look

Ask Elmer colours (navy, amber, mist), the speech-bubble mark and Ask Elmer's fonts: Barlow Condensed
for titles and Atkinson Hyperlegible for text, both SIL Open Font License, bundled in `fonts/` with
their licences. Arrows and symbols fall back to DejaVu Sans.
