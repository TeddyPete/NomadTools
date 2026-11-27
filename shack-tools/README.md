# Ask Elmer Shack Tools

From [Ask Elmer](https://askelmer.com). The everyday ham radio calculators from the Ask Elmer web app's
Shack, on the M5Stack CardputerZero, offline.

Package `askelmer-shack-tools`, share code `AEST`, Python package `shacktools` (pygame for the LCD).
Runs as the normal user.

## Tools

* **Frequency and band**: frequency or wavelength, your license class (Technician, General, Extra):
  band, whether you may transmit there and with which modes, wavelength, half- and quarter-wave lengths.
* **Band plan**: every US band from 160 m to 23 cm with your class's segments (FCC Part 97.301/97.305).
  Key 4 changes the class.
* **Ohm's law**: any two of E, I, R, P with prefixes (4.7k, 250m).
* **Decibels**: W to dBm/dBW, a gain or loss applied, ratio to dB.
* **SWR**: from a reading or forward/reflected watts: reflected power, return loss, mismatch loss.
* **Coax loss**: RG-58, RG-8X, RG-213, LMR-400, any length (ft or m) and frequency.
* **Grid square**: locator from latitude/longitude (or type yours), distance and beam heading to another.
* **UTC clock**, **Phonetics**, **Q signals**.

What you type in each tool is kept in `~/.config/askelmer-shack-tools/state.json`.

The math is a port of Ask Elmer's `app/src/workshop/shack/lib`. Band privileges: check the current FCC
rules before you transmit.

## Command line

```
askelmer-shack-tools --mhz 7.074 --license General
askelmer-shack-tools --screens /tmp/shots
```

## Build

```
python3 scripts/make_icon.py "SHACK TOOLS" packaging/icon.png packaging/icon_100.png
bash scripts/build_deb.sh
python3 -m pytest tests
```

## Look

Ask Elmer colours, the speech-bubble mark, Barlow Condensed and Atkinson Hyperlegible (SIL OFL, bundled in
`shacktools/fonts/`).
