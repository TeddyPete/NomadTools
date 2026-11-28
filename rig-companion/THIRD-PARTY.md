# Third-party components

Retrieved November 27, 2026. External source files are reference material and were inspected before use.

## APRS packet parser

- Author: Tim Cocks for Adafruit Industries, copyright 2026.
- Source: https://github.com/adafruit/Adafruit_Learning_System_Guides/blob/main/Fruit_Jam/Fruit_Jam_SDR_Mapping/aprs_receiver/aprs_parse.py
- Git blob SHA: `1338ef829749e8bc85337f2e81eab2634735e511` (file identity, not a repository commit).
- License: MIT; full text in `licenses/MIT.txt`. File copyright and SPDX header are preserved.
- Copy: `rigzero/vendor/aprs_parse.py`, unchanged.
- Used for standard/compressed positions, Mic-E, objects/items, weather, station symbols and report classification. Rig Companion adds readable telemetry fields, persistent station definitions, validation, summaries and PHG interpretation.

## Map projection helpers

- Author: komoot GmbH, copyright 2015.
- Source: https://github.com/komoot/staticmap/blob/master/staticmap/staticmap.py
- Git blob SHA: `7378ec2ad67d203457530cd065388480eeba2547`.
- License: Apache-2.0; full text in `licenses/Apache-2.0.txt`.
- Copy: four coordinate functions extracted unchanged into `rigzero/vendor/projection.py`; unused rendering/network dependencies were omitted. The tile cache and small-screen interface are Rig Companion code.

## Basemap tiles

- © OpenStreetMap contributors, https://www.openstreetmap.org/copyright .
- Policy checked November 27, 2026: https://operations.osmfoundation.org/policies/tiles/ .
- The map requests only currently visible tiles over HTTPS, identifies the app, honors caching headers and displays attribution. It does not prefetch regions. Previously viewed cached areas work offline; an uncached offline view shows station markers without geographic map detail.

No aprs.fi code, branding, API or historical database is used. Full Linux APRS clients reviewed: https://github.com/Xastir/Xastir and https://www.ka2ddo.org/ka2ddo/YAAC.html . They remain separate apps, not bundled components.
