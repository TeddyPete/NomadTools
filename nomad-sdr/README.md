# Nomad SDR

A ham-friendly receiver for RTL-SDR dongles on the M5Stack CardputerZero.
Built for the **RTL-SDR Blog V3** (R820T), ready for HF through the V3's
direct-sampling input or an upconverter. GPL-3.0-only, part of the Nomad
tools by TheTechNomad.

It fills the gaps the store's ZeroRadio / ZeroSDR leave for hams:

| Feature | What it does |
| --- | --- |
| Listen | NFM, AM, USB, LSB, CW (700 Hz tone), broadcast FM. Filter width per mode, gain (auto or tuner steps), squelch, AGC, volume, PPM. Live 250 kHz spectrum and signal meter (dB over the noise). Tuning is instant: the dongle is retuned live. |
| Band plan | US amateur bands 160 m to 23 cm with ARRL sub-bands. Shows who may transmit (Tech / General / Extra) and, with your class set, "You can transmit here" or "Receive only". OK on a segment tunes it with the right mode. |
| Repeaters | Usual US offset for repeater outputs, **R** listens on the input (is the station in simplex range?). |
| HF | 0.5-28.8 MHz with the V3 direct sampling (Q branch), or an upconverter offset (Ham It Up style, 125 MHz default). The V4 is planned. |
| Recording | WAV (32 kHz mono), optionally only while the squelch is open. Power-loss safe. Play on the device, download on a phone from a web page shown as a QR code, or copy all to a USB stick (folder `Nomad-SDR`). |
| Bias-tee | Switch 4.5 V on the antenna jack for an LNA or active antenna (always switched off when the app quits). |
| APRS | Decodes 144.390 (also ISS 145.825, Europe 144.800) with multimon-ng. Stations listed with distance and direction (GPS or typed grid). Every packet goes into **Rig Companion**'s store, so its APRS list, inbox, weather page and map fill up from the SDR. |
| Fox hunt | Big "dB over noise" number, peak hold, rising/falling trend, history graph, fixed gain with quick Gain-/Gain+, and a tone whose pitch rises with the signal. |

## Keys

CardputerZero key spec: plain F/X/Z/C are Up/Down/Left/Right outside text
entry, Fn+H help, short Esc back one level, **hold Esc to exit to HOME**.

Radio screen: Up/Down tune by the step, Left/Right change the step, OK menu.
Keys 4-8: **Mode, Freq, Rec, Band, Menu**. R repeater input, M save memory,
S squelch, G gain, - and = volume, Space mute, B bias-tee.

## Files

* Settings: `~/.config/nomad-sdr/settings.json`
* Recordings: `~/.local/share/nomad-sdr/recordings/`
* APRS log: `~/.local/share/nomad-sdr/aprs.log`

Runs as the normal user (no root). The dongle needs the usual udev rule
from `librtlsdr0` / `rtl-sdr`. Only one program can use the dongle at a
time: close ZeroRadio / ZeroSDR first.

## How it works

`nomadsdr/rtl.py` talks to librtlsdr with ctypes (256 kS/s). `dsp.py` does
one 8192-point FFT per block (overlap-save): the spectrum, the channel
filter and the decimation to 32 kHz all come from it, with the channel 60 kHz
off the dongle's DC spike. About 30 % of one core on the CardputerZero,
~40 MB of RAM. Sound goes to PipeWire with `aplay`.

## Build and test

    ./scripts/build_deb.sh                 # build/nomad-sdr_<ver>-1_arm64.deb
    python3 tests/test_basic.py            # no dongle needed
    python3 tests/aprs_loop.py             # APRS through the receiver and multimon-ng
    python3 -m nomadsdr --screens shots/   # store screenshots
    nomad-sdr --probe                      # dongle, tuner, gains
    nomad-sdr --level 162.55 5             # signal level for 5 s

## Later

Weather-satellite (NOAA APT) capture, CW decoder, WSPR/FT8 spotting, RTL-SDR
Blog V4 (R828D) HF, memory scan, Ask Elmer lesson links.
