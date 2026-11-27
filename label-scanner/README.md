# Nomad Label Scanner

Part of the Nomad tools by Tech Nomad Ted, [TheTechNomad.com](https://TheTechNomad.com).
Scan AV gear labels with the M5Stack CardputerZero's camera and build an
inventory you can open in Excel.

Package `nomad-label-scanner`, share code `NMLS`, Python package `nomadscan`.
Runs as the normal user (no root). Uses Debian packages only: `rpicam-apps`
(camera), `python3-zbar` (barcodes/QR), `tesseract-ocr` (label text),
pygame/numpy/PIL (screen). `arp-scan` is used for network finds when Nomad
Net Tools has given it network rights; otherwise a UDP poke + ARP table.

## What it does

* **Scan a label**: live camera on the screen. Barcodes and QR codes are read
  as you aim (zbar on every frame). OK takes the shot, which also reads the
  printed text (tesseract OCR, about 5-10 s on the CardputerZero).
* **Picks out the fields**: MAC (any spelling: `00:10:7F..`, `00-10-7F..`,
  `0010.7f12.3456`, bare 12 hex, OCR look-alikes like O/0 and I/1 fixed),
  IP, serial (`S/N`, `Serial No.`, `SER`) and model (`Model`, `P/N`, `Part No.`).
  Barcodes win over OCR because they are exact; a plain barcode with no label
  word is taken as the serial. Every value found is listed under **Codes** so
  you can move it into another field.
* **MAC maker** from the IEEE list (arp-scan's copy) plus a built-in list of
  AV makers.
* **Find on network**: by MAC it sweeps the local subnet(s) and reads the ARP
  table to get the IP, then pings; by IP it pings and reads the MAC. The
  Inventory's **Check** does every item at once.
* **Jobs**: one inventory per site/room/rack, with Room (sticky for the next
  scans) and Notes. Label photos are kept (setting).
* **Export**: Excel (.xlsx, written with the standard library, one sheet per
  job, bold frozen header, filters) and CSV (UTF-8 with BOM so Excel opens it
  right). Nomad file transfer standard: a web page reached by a QR code on the
  screen (Excel, CSV, a .zip with photos, and All-Jobs.xlsx), or copy all to
  a USB stick (`Nomad-Label-Scans/`).

Files: `~/Nomad-Label-Scans/<Job>/items.json`, `photos/`, `<Job>.csv`,
`<Job>.xlsx`; settings in `~/.config/nomad-label-scanner/settings.json`.

## Camera notes

The camera streams 1536x816 YUV (same shape as the screen) from
`rpicam-vid`, so the preview shows exactly what is decoded and it fits the
stock 64 MB CMA. The camera is stopped while OCR runs to leave memory for
tesseract. The IMX219 lens is fixed focus: hold labels about 15-20 cm away.
For tiny stickers use **Zoom 2x** (a sensor crop, no blur from upscaling)
or a clip-on macro lens. If the picture is upside down, **Flip**.

## Keys (official CardputerZero key spec)

F/X move, OK or C select, Z or ESC back, ESC on the main page quits, hold ESC
for HOME, Fn+H help. Number keys 4-8 (labels at the bottom):

* Home: Scan, Items, Jobs, Share
* Camera: Shot, Zoom, Text on/off, Flip, Done (OK also takes the shot)
* Item: Save, Find, Codes, Photo, Discard/Delete
* Inventory: Scan, Check (all on the network), Share
* Jobs: New, Rename, Delete

## Command line (over SSH)

```
nomad-label-scanner --shot [--save frame.png]   take one shot and read it
nomad-label-scanner --read photo.jpg            read a photo file
nomad-label-scanner --jobs | --list [JOB]       jobs, items
nomad-label-scanner --export [JOB]              write CSV + XLSX
nomad-label-scanner --find 00:10:7F:12:34:56    find a device by MAC (or IP)
```

## Build

```
python3 -m unittest discover tests      # parsing, exports, synthetic label read
python3 scripts/make_assets.py          # store screenshots
bash scripts/build_deb.sh               # build/nomad-label-scanner_<ver>-1_arm64.deb
```
Icon: `branding/nomad_icons.py --style labeled --only label-scanner`.
