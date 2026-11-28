"""Readable APRS reports, preserving raw packets and unknown sensor units."""
import math
import re

from .vendor import aprs_parse


def decode(source, destination, body):
    try:
        result = aprs_parse.aprs(source, destination, body.encode("latin-1", "replace"))
    except (ValueError, IndexError, KeyError, TypeError, OverflowError, ZeroDivisionError, RecursionError):
        result = {}
    if "lat" in result:
        lat, lon = result["lat"], result.get("lon", float("nan"))
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            result.pop("lat", None)
            result.pop("lon", None)
    # Validate decimal minutes before plotting positions accepted by the parser.
    uncompressed = re.search(r"(\d{2})(\d{2}\.\d{2})[NS].(\d{3})(\d{2}\.\d{2})[EW]", body)
    if uncompressed and (float(uncompressed[2]) >= 60 or float(uncompressed[4]) >= 60):
        result.pop("lat", None)
        result.pop("lon", None)
    telemetry = re.match(r"T#(\d{1,3}|MIC),((?:\d{1,3},){5})([01]{8})(.*)$", body)
    if telemetry:
        result.update(type="telemetry", telemetry={"sequence": telemetry[1],
                      "values": [int(v) for v in telemetry[2].strip(",").split(",")], "bits": telemetry[3]},
                      comment=telemetry[4].strip())
    if len(body) > 11 and body.startswith(":") and body[10] == ":" and body[1:10].strip() == source:
        match = re.match(r"(PARM|UNIT|EQNS|BITS)\.(.*)", body[11:])
        if match:
            fields = match[2].split(",")[:15]
            update = {}
            if match[1] in ("PARM", "UNIT"):
                update["names" if match[1] == "PARM" else "units"] = [v[:24] for v in fields[:13]]
            elif match[1] == "EQNS":
                try:
                    values = [float(v) for v in fields]
                    if len(values) % 3 == 0 and all(math.isfinite(v) and abs(v) <= 1e12 for v in values):
                        update["equations"] = [values[i:i + 3] for i in range(0, len(values), 3)]
                except ValueError:
                    pass
            elif re.fullmatch(r"[01]{8}", fields[0]):
                update.update(bits=fields[0], project=",".join(fields[1:])[:60])
            result.update(type="telemetry setup", definition=update, comment=match[2])
    phg = re.search(r"PHG([0-9])([0-9])([0-9])([0-9])", result.get("comment", ""))
    if phg:
        p, h, g, bearing = map(int, phg.groups())
        result["phg"] = {"power": p * p, "height_ft": 10 * 2 ** h, "gain_dbi": g,
                         "bearing": bearing * 45 if 1 <= bearing <= 8 else None}
    result["symbol_name"] = aprs_parse.symbol_name(result.get("sym"))
    return result


def coordinates(lat, lon):
    return f"{abs(lat):.5f} {'N' if lat >= 0 else 'S'}  {abs(lon):.5f} {'E' if lon >= 0 else 'W'}"


def describe(packet, definitions=None):
    """Return a new display record; raw info, message body and timestamp survive."""
    result = dict(packet)
    data = packet.get("decoded", {})
    lines = []
    summary = packet["text"]
    if "lat" in data:
        summary = coordinates(data["lat"], data["lon"])
        lines.append(summary)
        if data.get("name"):
            lines.append(("Removed: " if data.get("killed") else "Name: ") + data["name"])
        if data.get("symbol_name"):
            lines.append("Station: " + data["symbol_name"])
        if "course" in data:
            lines.append(f"Course {data['course']:g} deg")
        if "speed" in data:
            lines.append(f"Speed {data['speed']:g} km/h")
        if "alt" in data:
            lines.append(f"Altitude {data['alt']:g} m")
        if data.get("mice"):
            lines.append("Mic-E: " + data["mice"])
    telemetry = data.get("telemetry")
    if telemetry:
        meta = definitions or {}
        readings = []
        for i, raw in enumerate(telemetry["values"]):
            name = meta.get("names", [])[i] if i < len(meta.get("names", [])) else f"Channel {i + 1}"
            equations = meta.get("equations", [])
            unit = "raw"
            value = raw
            if i < len(equations):
                a, b, c = equations[i]
                value = a * raw * raw + b * raw + c
                unit = meta.get("units", [])[i] if i < len(meta.get("units", [])) else ""
            readings.append(f"{name}: {value:g}" + (" " + unit if unit else ""))
        summary = f"Telemetry #{telemetry['sequence']} · " + readings[0]
        lines = [f"Report #{telemetry['sequence']}"] + readings
        bits = telemetry["bits"]
        lines.append("Digital bits: " + bits)
        for i, value in enumerate(bits):
            if 5 + i < len(meta.get("names", [])):
                sense = meta.get("bits", "11111111")[i]
                lines.append(meta["names"][5 + i] + (": ON" if value == sense else ": OFF"))
        if not meta.get("equations"):
            lines.append("Raw values; calibration not received")
    if data.get("type") == "telemetry setup":
        summary = "Telemetry labels / calibration"
        lines = [summary, packet["info"].split(":", 2)[-1]]
    if data.get("phg"):
        phg = data["phg"]
        lines.extend([f"Power {phg['power']} W · Gain {phg['gain_dbi']} dBi",
                      f"Antenna height {phg['height_ft']} ft HAAT",
                      f"Direction {phg['bearing']} deg" if phg["bearing"] else "Antenna omnidirectional"])
    if packet.get("weather"):
        wx = packet["weather"]
        labels = (("temp", "Temperature", "F"), ("humidity", "Humidity", "%"), ("wind", "Wind", "mph"),
                  ("gust", "Gust", "mph"), ("pressure", "Pressure", "hPa"), ("rain", "Rain / hour", "in"))
        values = [f"{label}: {wx[key]:g} {unit}" for key, label, unit in labels if key in wx]
        lines.extend(values)
        if "lat" not in data:
            summary = " · ".join(values[:2])
    comment = data.get("comment", "").strip()
    if comment and comment != packet["text"] and not telemetry and data.get("type") != "telemetry setup":
        lines.append(comment)
    if not lines:
        lines.append(packet["text"])
    result.update(summary=summary, details="\n".join(lines))
    return result
