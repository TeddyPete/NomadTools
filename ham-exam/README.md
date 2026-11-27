# Ask Elmer Ham Exam

From [Ask Elmer](https://askelmer.com). Study for the US amateur radio license exams on the
M5Stack CardputerZero, offline, with the official NCVEC question pools word for word.

Package `askelmer-ham-exam`, share code `AEHX`, Python package `hamexam` (pygame for the LCD).
Runs as the normal user.

## What it does

* **Pools**: Technician 2026-2030 (409), General 2023-2027 (423 active), Amateur Extra 2024-2028
  (599 active). Questions deleted by NCVEC errata are never drawn.
* **Practice exam**: one question from each group, like the real draw (35, pass 26; Extra 50, pass
  37). Move back and forth, change answers, Finish scores it; then review the missed questions.
* **Study a topic**: a subelement or one group. After each answer: the correct answer and its rule
  reference. After a miss, a fresh question from the same group, and the missed one comes back.
* **Quick 10** (weakest questions first) and **Missed questions**.
* **Progress**: seen and mastered (two right in a row) per subelement, practice exam results and an
  estimated chance to pass today.
* **Figures** fill the screen, with 4 to zoom and arrows to pan.
* Progress is saved in `~/.config/askelmer-ham-exam/state.json`; every record keeps its `pool_id`.

Wrong answers show only the correct answer and its rule, never anything about the choice picked.
Ask Elmer's explanations (the method for each question) are not bundled; the app points to
askelmer.com.

## Command line (over SSH)

```
askelmer-ham-exam --exams
askelmer-ham-exam --draw technician
askelmer-ham-exam --screens /tmp/shots     # render the LCD screens to PNG
```

## Build

```
python3 scripts/import_pools.py ../../askelmer     # copy the pools from the Ask Elmer repo
python3 scripts/make_icon.py "HAM EXAM" packaging/icon.png packaging/icon_100.png
bash scripts/build_deb.sh                          # build/askelmer-ham-exam_<ver>-1_arm64.deb
python3 -m pytest tests
```

The pool files in `hamexam/data/` are copied unchanged from Ask Elmer's `packs/ham-radio/pools/`,
which are generated from the NCVEC releases by Ask Elmer's `tools/parse_ncvec_pool.py`. Don't edit
them by hand; re-run the import when a pool or errata changes. The NCVEC pools are public domain.

## Look

Ask Elmer colours (navy, amber, mist), the speech-bubble mark and Ask Elmer's fonts: Barlow Condensed
for titles and Atkinson Hyperlegible for text, both SIL Open Font License, bundled in `fonts/` with
their licences. Arrows and symbols fall back to DejaVu Sans.
