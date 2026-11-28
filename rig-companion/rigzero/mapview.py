"""Small station map with a single background tile fetcher and a disk cache."""
from collections import OrderedDict
from email.utils import parsedate_to_datetime
from io import BytesIO
import json
import math
import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .display import ACCENT, ALERT, BG, DIM, INK, PANEL
from .vendor.projection import _lat_to_y, _lon_to_x, _x_to_lon, _y_to_lat

MAX_LAT = 85.05112878
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def point(lat, lon, zoom):
    return _lon_to_x(lon, zoom) * 256, _lat_to_y(max(-MAX_LAT, min(MAX_LAT, lat)), zoom) * 256


class TileCache:
    def __init__(self, folder, enabled=True):
        self.folder, self.enabled = folder, enabled
        folder.mkdir(parents=True, exist_ok=True)
        self.pending = ()
        self.visible = False
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.generation = 0
        self.status = "Cached map"
        self.retry_at = 0
        self.thread = threading.Thread(target=self._run, daemon=True, name="rig-map-tiles")
        if enabled:
            self.thread.start()

    def path(self, key):
        return self.folder / ("%d-%d-%d.png" % key)

    def request(self, keys):
        self.visible = True
        keys = tuple(dict.fromkeys(keys))
        if keys != self.pending:
            self.pending = keys
            self.wake.set()

    def pause(self):
        self.visible = False

    def _fetch(self, key):
        from PIL import Image
        path = self.path(key)
        meta_path = path.with_suffix(".json")
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            meta = {}
        now = time.time()
        if path.exists() and meta.get("expires", 0) > now:
            return
        if not path.exists() and len(list(self.folder.glob("*.png"))) >= 256:
            # Retain cached tiles for at least seven days; never bulk-prefetch.
            oldest = min(self.folder.glob("*.png"), key=lambda p: p.stat().st_mtime)
            if now - oldest.stat().st_mtime < 7 * 86400:
                self.status = "Map cache full"
                return
            oldest.unlink()
            oldest.with_suffix(".json").unlink(missing_ok=True)
        headers = {"User-Agent": "RigCompanionZero/0.2.0 (APRS station map)"}
        if meta.get("etag") and path.exists():
            headers["If-None-Match"] = meta["etag"]
        request = Request(TILE_URL.format(z=key[0], x=key[1], y=key[2]), headers=headers)
        self.status = "Loading map"
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            if error.code != 304 or not path.exists():
                raise
            response = error
        with response:
            cache_control = response.headers.get("Cache-Control", "")
            lifetime = re.search(r"max-age=(\d+)", cache_control)
            ttl = int(lifetime[1]) if lifetime else 7 * 86400
            if not lifetime and response.headers.get("Expires"):
                try:
                    ttl = max(0, parsedate_to_datetime(response.headers["Expires"]).timestamp() - now)
                except (ValueError, TypeError, OverflowError):
                    pass
            if response.code != 304:
                data = response.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise ValueError("Oversized map tile")
                with Image.open(BytesIO(data)) as tile:
                    if tile.format != "PNG" or tile.size != (256, 256):
                        raise ValueError("Invalid map tile")
                    tile.verify()
                part = path.with_suffix(".part")
                part.write_bytes(data)
                part.replace(path)
                self.generation += 1
            meta.update(expires=now + ttl, etag=response.headers.get("ETag", meta.get("etag", "")))
            meta_path.write_text(json.dumps(meta))
        self.status = "Cached map"

    def _run(self):
        while not self.stop.is_set():
            self.wake.wait(.5)
            self.wake.clear()
            if not self.visible or time.monotonic() < self.retry_at:
                continue
            for key in self.pending:
                if not self.visible or self.stop.is_set():
                    break
                if key not in self.pending:
                    continue
                try:
                    self._fetch(key)
                except Exception:
                    self.status = "Offline / cached tiles"
                    self.retry_at = time.monotonic() + 30
                    break
                if self.stop.wait(.15):
                    break

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread.is_alive():
            self.thread.join(3.5)


class StationMap:
    width, height, top = 320, 102, 26

    def __init__(self, folder, network=True):
        self.cache = TileCache(folder, enabled=network)
        self.center = None
        self.zoom = 8
        self.selected = None
        self.images = OrderedDict()
        self.generation = -1

    def fit(self, stations):
        if not stations:
            return
        reference = stations[0]["decoded"]["lon"]
        xs, ys = [], []
        for packet in stations:
            data = packet["decoded"]
            lon = reference + (data["lon"] - reference + 180) % 360 - 180
            x, y = point(data["lat"], lon, 0)
            # The projection wraps longitude, so unwrap around the first station.
            rx, _ = point(0, reference, 0)
            x = rx + (x - rx + 128) % 256 - 128
            xs.append(x)
            ys.append(y)
        cx, cy = (min(xs) + max(xs)) / 512, (min(ys) + max(ys)) / 512
        self.center = (_y_to_lat(cy, 0), (_x_to_lon(cx, 0) + 180) % 360 - 180)
        for zoom in range(14, 1, -1):
            if (max(xs) - min(xs)) * 2 ** zoom <= self.width - 50 and (max(ys) - min(ys)) * 2 ** zoom <= self.height - 35:
                self.zoom = zoom
                break
        else:
            self.zoom = 2
        self.selected = stations[0]["station_key"]

    def choose(self, stations, packet=None):
        if self.center is None and stations:
            data = stations[0]["decoded"]
            self.center = (data["lat"], data["lon"])
            self.zoom = 9
            self.selected = stations[0]["station_key"]
        if packet and "lat" in packet.get("decoded", {}):
            data = packet["decoded"]
            self.center = (data["lat"], data["lon"])
            self.selected = packet.get("station_key", packet["sender"] + "/" + data.get("name", ""))
        if stations and self.selected not in {p["station_key"] for p in stations}:
            self.selected = stations[0]["station_key"]

    def selected_packet(self, stations):
        return next((p for p in stations if p["station_key"] == self.selected), None)

    def next(self, stations):
        if stations:
            current = next((i for i, p in enumerate(stations) if p["station_key"] == self.selected), -1)
            packet = stations[(current + 1) % len(stations)]
            self.choose(stations, packet)

    def pan(self, dx, dy):
        if self.center is None:
            return
        x, y = point(*self.center, self.zoom)
        x += dx * 55
        y = max(0, min(256 * 2 ** self.zoom, y + dy * 35))
        self.center = (_y_to_lat(y / 256, self.zoom), (_x_to_lon(x / 256, self.zoom) + 180) % 360 - 180)

    def render(self, display, stations):
        import pygame
        self.choose(stations)
        if self.center is None:
            self.cache.pause()
            display.text("Waiting for station positions", 10, 47, INK, 17, 300)
            display.wrap("Received positions will appear here. Previously viewed map tiles also work offline.", y=78, height=56, color=DIM)
            return
        cx, cy = point(*self.center, self.zoom)
        origin = (cx - self.width / 2, cy - self.height / 2)
        view = pygame.Surface((self.width, self.height))
        view.fill(PANEL)
        keys = []
        loaded = 0
        if self.generation != self.cache.generation:
            self.images.clear()
            self.generation = self.cache.generation
        for x in range(math.floor(origin[0] / 256), math.ceil((origin[0] + self.width) / 256)):
            for y in range(math.floor(origin[1] / 256), math.ceil((origin[1] + self.height) / 256)):
                px, py = round(x * 256 - origin[0]), round(y * 256 - origin[1])
                if not 0 <= y < 2 ** self.zoom:
                    continue
                key = (self.zoom, x % 2 ** self.zoom, y)
                keys.append(key)
                if key not in self.images:
                    try:
                        self.images[key] = pygame.image.load(str(self.cache.path(key)))
                    except (OSError, pygame.error):
                        self.images[key] = None
                tile = self.images[key]
                if tile:
                    loaded += 1
                    view.blit(tile, (px, py))
                else:
                    pygame.draw.rect(view, "#3a5058", (px, py, 256, 256), 1)
        while len(self.images) > 24:
            self.images.popitem(last=False)
        self.cache.request(keys)
        selected_packet = self.selected_packet(stations)
        if selected_packet:
            previous = None
            world = 256 * 2 ** self.zoom
            for lat, lon in selected_packet.get("trail", []):
                x, y = point(lat, lon, self.zoom)
                x = cx + (x - cx + world / 2) % world - world / 2
                current = (round(x - origin[0]), round(y - origin[1]))
                if previous and abs(current[0] - previous[0]) < world / 2:
                    pygame.draw.line(view, "#168e83", previous, current, 2)
                previous = current
        occupied = [pygame.Rect(281, 2, 37, 17)]
        ordered = sorted(stations, key=lambda p: p["station_key"] != self.selected)
        for packet in ordered:
            data = packet["decoded"]
            x, y = point(data["lat"], data["lon"], self.zoom)
            world = 256 * 2 ** self.zoom
            x = cx + (x - cx + world / 2) % world - world / 2
            px, py = round(x - origin[0]), round(y - origin[1])
            if not (0 <= px < self.width and 0 <= py < self.height):
                continue
            selected = packet["station_key"] == self.selected
            color = ALERT if selected else ACCENT
            pygame.draw.circle(view, BG, (px, py), 6)
            pygame.draw.circle(view, color, (px, py), 4)
            label = data.get("name") or packet["sender"]
            image = display.fonts[12].render(label, True, color)
            box = pygame.Rect(min(max(2, px + 7), self.width - image.get_width() - 7),
                              min(max(2, py - 16), self.height - 18), image.get_width() + 6, 16)
            if selected or not any(box.colliderect(other) for other in occupied):
                pygame.draw.rect(view, BG, box, border_radius=2)
                view.blit(image, (box.x + 3, box.y))
                occupied.append(box)
        display.surface.blit(view, (0, self.top))
        if loaded < len(keys):
            label = self.cache.status if self.cache.enabled else "Offline / no cached map"
            if label == "Cached map":
                label = "Loading map"
            image = display.fonts[12].render(label, True, INK)
            display.rect(5, 28, image.get_width() + 8, 17, BG)
            display.surface.blit(image, (9, 29))
        display.rect(281, 28, 37, 17, BG)
        display.text(f"z{self.zoom}", 287, 29, INK, 12)
        display.text("Arrows pan · Tab next · A all · R center", 9, 130, DIM, 12, 302)

    def close(self):
        self.cache.close()

