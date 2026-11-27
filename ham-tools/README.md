# Ask Elmer Ham Tools

From [Ask Elmer](https://askelmer.com). Ham radio tools on the M5Stack CardputerZero, with Antenna Lab up
front. Everything works offline except the live data (solar, spots, park lists and orbits), which is kept
for offline use once downloaded.

Package `askelmer-ham-tools`, share code `AEHT`, Python package `hamtools` (pygame and numpy for the LCD,
`nec2c` for antenna modelling, `python3-sgp4` for satellites). Runs as the normal user.

Version 0.3 merges the old **Ask Elmer Antenna Lab** and **Ask Elmer Shack Tools** into this one app. The
package replaces both (`Provides`/`Replaces`/`Conflicts`), so installing it removes them, and the first run
copies their settings into `~/.config/askelmer-ham-tools/` (the antenna designs become `antenna.json`).
The app's name is set in one place, `hamtools/__init__.py` (plus `app-builder.json` and `packaging/`).

## Sections

* **Antenna Lab** (loaded only when you open it): 18 antennas modelled with NEC2 on the device: dipole,
  inverted V, OCFD, end-fed half wave, fan and trap dipoles, G5RV / doublet, ground-mounted and elevated
  verticals, 5/8 wave, loaded short vertical, J-pole, Yagi (2-10 elements), Moxon, quad, delta loop, sky
  loop, small magnetic loop.
  * Design: frequency, sizes in feet or metres, height, wire or tubing, matching device.
  * Run (4): feed impedance, SWR through the match, resonance, 2:1 bandwidth, gain, takeoff angle, F/B,
    beamwidth, efficiency; with a feed line set, coax loss and the SWR at the radio.
  * Tune (5), SWR chart (6, with Wide and Measure: a NanoVNA `scan` or a `.s1p` file laid over the
    model), Pattern (7: azimuth and elevation, and a 3D shape you can turn and spin), Cut list (8).
  * Optimize the beam (Yagi): most gain, best F/B or balanced, without a longer boom.
* **Band check**: a frequency against your class, with a bar of the whole band (Technician, General and
  Extra segments, teal CW/data, amber phone, green all modes), may you transmit, the power limit, distance
  to the edge, the 60 m channel, what's usually nearby and the wavelength. Keys 5/6 step through the bands,
  7 is the band plan, **8 opens Antenna Lab at that frequency** (this replaces the old rule-of-thumb
  dipole and vertical lengths).
* **RF math**: power, dB and S-units, SWR and return loss, Ohm's law, LC, toroids, attenuator pads.
* **Where & when**: distance and beam headings to a grid or a call sign, zones, sunrise, sunset, greyline.
* **Propagation**: solar data from hamqsl.com plus Ask Elmer's offline MUF estimate and its daily curve.
* **Satellites**: next passes of ISS, SO-50, AO-91, PO-101, RS-44, AO-7 and FO-29 with a sky plot and live
  Doppler-corrected frequencies. Orbits from AMSAT (CelesTrak as a backup); a snapshot is bundled.
* **POTA / SOTA**: spots, parks and summits within 250 km (kept offline), an activation counter.
* **Station clock**: UTC and local time, and a 10-minute ID timer that beeps.
* **Reference**: search, Q signals, prosigns, CW abbreviations, RST, cut numbers, phonetics, 60 m channels.

No logbook: HamLog in the store does that. Band privileges follow FCC Part 97; check the current rules
before you transmit.

## GPS for every app

`hamtools/nomadgps.py` is a shared, root-free GPS reader that other Ask Elmer and Nomad apps can copy in.
The first app that wants a fix locks `/run/user/<uid>/nomad-gps/reader.lock`, reads NMEA and writes the fix
every second to `/run/user/<uid>/nomad-gps/fix.json`; other apps read that file. The last fix is kept in
`~/.config/nomad-gps/last.json`.

* USB GPS receivers that say they are one (u-blox, BU-353 and the like) are found by themselves. A radio's
  CAT port is never opened.
* **M5Stack Cap LoRa-1262**: its GNSS (ATGM336H) is on `/dev/ttyS0` at 115200, powered from the EXT 5 V
  output. Turn on "Cap LoRa GNSS" in Settings: it writes `{"cap": true}` to
  `~/.config/nomad-gps/config.json` and switches `/sys/class/leds/ext_5v_out` on (the gpio group may, so
  no root). If the 5 V output is already on, the Cap is tried without the setting.
* Another port: `{"port": "/dev/ttyUSB0", "baud": 4800}` in the same `config.json`.

## Command line (over SSH)

```
askelmer-ham-tools --mhz 7.074 --license General
askelmer-ham-tools --antennas
askelmer-ham-tools --run moxon --mhz 14.2 --tune
askelmer-ham-tools --deck dipole --mhz 7.15     # the NEC2 deck
askelmer-ham-tools --screens /tmp/shots         # render the LCD screens to PNG
```

## Build

```
python3 scripts/make_icon.py "HAM TOOLS" packaging/icon.png packaging/icon_100.png
bash scripts/build_deb.sh            # build/askelmer-ham-tools_<ver>-1_arm64.deb
python3 -m pytest tests              # the antenna tests need nec2c
```

## Look

Ask Elmer colours (navy, amber, mist), the speech-bubble mark, Barlow Condensed and Atkinson Hyperlegible
(SIL OFL, bundled in `hamtools/fonts/`).
