# Ask Elmer Shack Tools

From [Ask Elmer](https://askelmer.com). Ham radio tools on the M5Stack CardputerZero. Everything works offline
except the live data (solar, spots, park lists and orbits), which is kept for offline use once downloaded.

Package `askelmer-shack-tools`, share code `AEST`, Python p## Tools (0.2)

* **Band check**: a frequency (keys 5/6 step through the bands) against your class. A bar shows the
  whole band with Technician, General and Extra segments (teal CW/data, amber phone, green all modes)
  and a marker; then may you transmit, the power limit, distance to the segment edge, the 60 m channel,
  what's usually nearby (FT8, FT4, CW QRP, SSTV, calling frequencies) and dipole and vertical lengths.
  Key 7 is the band plan.
* **RF math**: power, dB and S-units (dBm or uV), SWR and return loss, Ohm's law, LC resonance and
  reactance, toroid winding (Amidon T and FT cores, turns and wire length), pi and T attenuator pads
  with the nearest 5% resistors.
* **Where & when**: your location from a USB GPS or your grid (key 4 takes the GPS fix, key 5 a
  city). To a grid or a call sign: country and CQ/ITU zones, distance and beam headings (short and
  long path), sunrise, sunset and greyline at both ends.
* **Propagation**: solar flux, sunspots, A and K, X-ray and N0NBH's band conditions (hamqsl.com, key 4),
  plus Ask Elmer's own offline MUF estimate for a 3000 km hop from your location, and its curve through the
  day (key 5). The estimate is a smooth empirical model, not a forecast.
* **Satellites**: the next passes of ISS, SO-50, AO-91, PO-101, RS-44, AO-7 and FO-29 (SGP4,
  `python3-sgp4`), with a sky plot and live Doppler-corrected uplink and downlink. Key 4 downloads
  fresh orbits from AMSAT (CelesTrak as a backup); a snapshot is bundled.
* **POTA / SOTA**: spots now (api.pota.app), parks and summits within 250 km (downloaded once from
  pota.app and sotadata, kept offline), and an activation counter (10 for POTA, 4 for SOTA, in one UTC day).
* **Station clock**: UTC (from the GPS when there is one) and local time, and a 10-minute ID timer
  that beeps.
* **Reference**: search, Q signals, prosigns, CW abbreviations, RST, cut numbers, phonetics, 60 m channels.

The coax loss tool moved to Ask Elmer Antenna Lab (Settings, Feed line).

## GPS for every app

`shacktools/nomadgps.py` is a shared, root-free GPS reader that other Ask Elmer and Nomad apps can
copy in. The first app that wants a fix locks `/run/user/<uid>/nomad-gps/reader.lock`, reads NMEA from
a port that says it is a GPS (u-blox, BU-353 and the like; a radio's CAT port is never opened), and
writes the fix every second to `/run/user/<uid>/nomad-gps/fix.json`. Other apps read that file; when
the reading app quits, the next takes over. The last fix is kept in `~/.config/nomad-gps/last.json`.
Another port can be named in `~/.config/nomad-gps/config.json`: `{"port": "/dev/ttyUSB0", "baud": 4800}`.

What you type in each tool, and the downloaded data, are kept in `~/.config/askelmer-shack-tools/`.
Band privileges: check the current FCC rules before you transmit.

 Band privileges: check the current FCC
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
