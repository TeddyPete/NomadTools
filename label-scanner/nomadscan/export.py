"""Inventory exports: CSV and a real Excel workbook (.xlsx).

The .xlsx is written with the standard library (zipfile + XML), so the app
needs no spreadsheet package. One sheet per job, bold header row, frozen
header, filters on and sensible column widths.
"""
from __future__ import annotations

import csv
import io
import os
import re
import time
import zipfile
from xml.sax.saxutils import escape

from . import store

COLUMNS = [("#", 5), ("Device", 22), ("Model", 20), ("Serial", 20), ("MAC", 19), ("Vendor", 24),
           ("IP", 16), ("Room", 16), ("Notes", 30), ("Network check", 18), ("Checked", 18),
           ("Scanned", 19), ("Photo", 22), ("Barcodes", 40)]


def rows(items: list) -> list[list[str]]:
    out = []
    for n, it in enumerate(items, 1):
        out.append([str(n), it.name, it.model, it.serial, it.mac, it.vendor, it.ip, it.room, it.notes,
                    it.online, it.checked, it.time, it.photo, " | ".join(c for c in it.codes)])
    return out


def csv_bytes(items: list) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c for c, _ in COLUMNS])
    for r in rows(items):
        # keep Excel from turning serials like 00012 or 1E5 into numbers
        w.writerow([v for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")   # BOM: Excel opens UTF-8 right


# ---------------------------------------------------------------- xlsx

_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, value: str, style: int = 0) -> str:
    v = escape(_BAD.sub("", str(value)))
    st = f' s="{style}"' if style else ""
    if style == 0 and re.fullmatch(r"[1-9]\d{0,6}", str(value)):
        return f'<c r="{ref}"><v>{value}</v></c>'          # "#" column as a number
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{v}</t></is></c>'


def _sheet_xml(header: list, data: list, widths: list) -> str:
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
           '</sheetView></sheetViews>'
           f'<cols>{cols}</cols><sheetData>']
    out.append('<row r="1">' + "".join(_cell(f"{_col(i)}1", h, 1) for i, h in enumerate(header)) + "</row>")
    for r, row in enumerate(data, 2):
        out.append(f'<row r="{r}">' + "".join(_cell(f"{_col(i)}{r}", v) for i, v in enumerate(row) if v != "") + "</row>")
    last = f"{_col(len(header) - 1)}{max(1, len(data) + 1)}"
    out.append(f'</sheetData><autoFilter ref="A1:{last}"/></worksheet>')
    return "".join(out)


def sheet_title(name: str, used: set) -> str:
    t = re.sub(r"[\[\]:*?/\\]", "", name).strip("'")[:31] or "Sheet"
    base, n = t, 2
    while t.lower() in used:
        suffix = f" ({n})"
        t = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(t.lower())
    return t


def xlsx_bytes(sheets: list) -> bytes:
    """sheets: [(title, header, rows, widths)]"""
    used: set = set()
    titles = [sheet_title(s[0], used) for s in sheets]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                   '</Relationships>')
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                   'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                   '<dc:title>Nomad Label Scanner inventory</dc:title><dc:creator>Nomad Label Scanner</dc:creator>'
                   f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(t, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, t in enumerate(titles, 1))
                   + '</sheets>'
                   + "<definedNames>" + "".join(
                       f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
                       f"'{escape(t)}'!$A$1:${_col(len(s[1]) - 1)}${max(1, len(s[2]) + 1)}</definedName>"
                       for i, (t, s) in enumerate(zip(titles, sheets))) + "</definedNames>"
                   + '</workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                             f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
                   '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FF127834"/><bgColor indexed="64"/></patternFill></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   '</styleSheet>')
        for i, (title, header, data, widths) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(header, data, widths))
    return buf.getvalue()


def job_sheet(job: str, items: list | None = None):
    items = store.load(job) if items is None else items
    return (job, [c for c, _ in COLUMNS], rows(items), [w for _, w in COLUMNS])


def export_job(job: str) -> list[str]:
    """Write <job>.csv and <job>.xlsx into the job folder. Returns their paths."""
    items = store.load(job)
    d = store.job_dir(job)
    os.makedirs(d, exist_ok=True)
    base = os.path.join(d, store.safe_name(job))
    out = []
    for ext, data in ((".csv", csv_bytes(items)), (".xlsx", xlsx_bytes([job_sheet(job, items)]))):
        _atomic(base + ext, data)
        out.append(base + ext)
    return out


def export_all() -> str:
    """All-Jobs.xlsx in the scans folder: one sheet per job."""
    js = store.jobs()
    path = os.path.join(store.data_root(), "All-Jobs.xlsx")
    os.makedirs(store.data_root(), exist_ok=True)
    _atomic(path, xlsx_bytes([job_sheet(j) for j in js] or [("Inventory", [c for c, _ in COLUMNS], [], [w for _, w in COLUMNS])]))
    return path


def _atomic(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
