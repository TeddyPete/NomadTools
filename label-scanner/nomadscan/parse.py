"""Pull MAC addresses, IP addresses, serial and model numbers out of what
the camera read: barcode/QR contents and OCR text from a gear label.

    found = parse.extract(codes=["SN:1234ABC"], text="MAC 00:10:7F:12:34:56 ...")
    found.mac, found.serial, found.model, found.ip, found.others
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEX = "0-9A-Fa-f"
_MAC_SEP = re.compile(rf"(?<![{HEX}.:\-])((?:[{HEX}]{{2}}([:\-. ]))(?:[{HEX}]{{2}}\2){{4}}[{HEX}]{{2}})(?![{HEX}]|[.:\-][{HEX}])")
_MAC_DOT = re.compile(rf"(?<![{HEX}.])([{HEX}]{{4}}\.[{HEX}]{{4}}\.[{HEX}]{{4}})(?![{HEX}])")
_MAC_BARE = re.compile(rf"(?<![0-9A-Za-z])([{HEX}]{{12}})(?![0-9A-Za-z])")
_IP = re.compile(r"(?<![\w.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\w]|\.\d)")

# Label words before a value. Order matters: longer first.
SERIAL_WORDS = r"(?:serial\s*(?:no\.?|number|num|#)?|s\s*/\s*n|s\.n\.?|ser\.?\s*no\.?|sn|ser)"
MODEL_WORDS = r"(?:model\s*(?:no\.?|number|#)?|mod\.?|mdl|type|p\s*/\s*n|part\s*(?:no\.?|number|#)?|pn|cat\.?\s*no\.?)"
MAC_WORDS = r"(?:mac\s*(?:address|addr\.?|id)?|ethernet(?:\s*address)?|lan\s*mac|hw\s*addr|e?id)"
IP_WORDS = r"(?:ip\s*(?:address|addr\.?)?|default\s*ip)"
_VAL = r"\s*[:#=\-.]?\s*([A-Za-z0-9][A-Za-z0-9\-/._]{2,40})"
_SERIAL = re.compile(rf"(?<![A-Za-z]){SERIAL_WORDS}{_VAL}", re.I)
_MODEL = re.compile(rf"(?<![A-Za-z]){MODEL_WORDS}{_VAL}", re.I)
_MACLAB = re.compile(rf"(?<![A-Za-z]){MAC_WORDS}\s*[:#=\-]?\s*([0-9A-Za-z:\-. ]{{12,20}})", re.I)
_IPLAB = re.compile(rf"(?<![A-Za-z]){IP_WORDS}\s*[:#=\-]?\s*([0-9OoIl|. ]{{7,21}})", re.I)
# Prefixes some makers put inside the barcode itself
_PREFIX = re.compile(r"^\s*(S/?N|SER(?:IAL)?|MAC|P/?N|MODEL|IP)\s*[:=#\-]?\s*(.+)$", re.I)

# Characters OCR mixes up with hex digits / numbers
_TO_HEX = str.maketrans({"O": "0", "o": "0", "Q": "0", "I": "1", "l": "1", "i": "1", "|": "1",
                         "S": "5", "s": "5", "Z": "2", "z": "2", "G": "6", "g": "9", "B": "8"})
_TO_NUM = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", " ": ""})


@dataclass
class Found:
    mac: str = ""
    ip: str = ""
    serial: str = ""
    model: str = ""
    others: list = field(default_factory=list)   # [(kind, value)] extra candidates
    codes: list = field(default_factory=list)    # [(symbology, data)] raw barcodes

    def candidates(self) -> list:
        """Every value found, for the "Use another code" picker: (kind, value)."""
        out = []
        for kind in ("mac", "ip", "serial", "model"):
            v = getattr(self, kind)
            if v:
                out.append((kind, v))
        seen = {v for _, v in out}
        for kind, v in self.others:
            if v not in seen:
                out.append((kind, v))
                seen.add(v)
        return out


def norm_mac(s: str) -> str:
    """Any MAC spelling -> 00:10:7F:12:34:56, or "" if it isn't one."""
    h = re.sub(r"[^0-9A-Fa-f]", "", s or "")
    if len(h) != 12:
        return ""
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)).upper()


def is_ip(s: str) -> bool:
    m = _IP.fullmatch((s or "").strip())
    return bool(m) and not s.startswith("0.")


def _fix_hex(s: str) -> str:
    return s.translate(_TO_HEX)


def _macs(text: str, fuzzy: bool) -> list[str]:
    out = []
    out += [norm_mac(m.group(1)) for m in _MAC_SEP.finditer(text)]
    out += [norm_mac(m) for m in _MAC_DOT.findall(text)]
    if fuzzy:
        # OCR: "00:1O:7F:I2:34:56" -> fix look-alike letters, then try again
        for m in re.findall(r"(?:[0-9A-Za-z|]{2}[:\-.]){5}[0-9A-Za-z|]{2}", text):
            v = norm_mac(_fix_hex(m))
            if v:
                out.append(v)
        for m in _MACLAB.findall(text):
            v = norm_mac(_fix_hex(re.sub(r"[\s:.\-]", "", m))[:12])
            if v:
                out.append(v)
    return [m for m in out if m and m != "00:00:00:00:00:00" and m != "FF:FF:FF:FF:FF:FF"]


def _clean(v: str) -> str:
    return v.strip().strip(".:-/_").strip()


def _plausible_id(v: str) -> bool:
    """Serial/model: some digits, not a plain word, not a date-ish tiny thing."""
    v = _clean(v)
    return 3 <= len(v) <= 40 and any(c.isdigit() for c in v) and not is_ip(v)


def _add(f: Found, kind: str, v: str) -> None:
    v = _clean(v) if kind in ("serial", "model") else v
    if not v:
        return
    if not getattr(f, kind):
        setattr(f, kind, v)
    elif getattr(f, kind) != v and (kind, v) not in f.others:
        f.others.append((kind, v))


def _from_text(f: Found, text: str, fuzzy: bool) -> None:
    for m in _macs(text, fuzzy):
        _add(f, "mac", m)
    for m in _IPLAB.findall(text) if fuzzy else []:
        v = re.sub(r"\s", "", m.translate(_TO_NUM)).strip(".")
        if is_ip(v):
            _add(f, "ip", v)
    for m in _IP.findall(text):
        if is_ip(m):
            _add(f, "ip", m)
    for m in _SERIAL.findall(text):
        if _plausible_id(m) and not norm_mac(m):
            _add(f, "serial", m)
    for m in _MODEL.findall(text):
        if len(_clean(m)) >= 2 and not norm_mac(m):
            _add(f, "model", m)


def classify_code(data: str) -> tuple[str, str]:
    """One barcode's contents -> (kind, value). kind: mac ip serial model url text."""
    d = (data or "").strip()
    m = _PREFIX.match(d)
    if m:
        word, val = m.group(1).upper().replace("/", ""), m.group(2).strip()
        kind = {"SN": "serial", "SER": "serial", "SERIAL": "serial", "MAC": "mac", "PN": "model",
                "MODEL": "model", "IP": "ip"}.get(word, "text")
        if kind == "mac":
            val = norm_mac(val) or val
        return kind, val
    if norm_mac(d) and (re.fullmatch(rf"[{HEX}]{{12}}", d) or _MAC_SEP.fullmatch(d) or _MAC_DOT.fullmatch(d)):
        return "mac", norm_mac(d)
    if is_ip(d):
        return "ip", d
    if re.match(r"^(https?://|www\.)", d, re.I):
        return "url", d
    if re.fullmatch(r"[A-Za-z0-9\-/._]{4,40}", d) and any(c.isdigit() for c in d):
        return "serial", d
    return "text", d


def extract(codes: list | None = None, text: str = "") -> Found:
    """codes: barcode contents (str or (symbology, data)). text: OCR text.
    Barcodes win over OCR because they are read exactly."""
    f = Found()
    plain_ids = []
    for c in codes or []:
        sym, data = (c if isinstance(c, (tuple, list)) else ("", c))
        f.codes.append((sym, data))
        if "\n" in data or ";" in data or len(data) > 48:
            # QR with several fields ("MAC:..;SN:..") - each part, then as label text
            for part in re.split(r"[;\n|,]", data):
                if _PREFIX.match(part):
                    kind, val = classify_code(part)
                    if kind in ("mac", "ip", "model", "serial"):
                        _add(f, kind, val)
            _from_text(f, data.replace(";", "\n"), fuzzy=False)
            continue
        kind, val = classify_code(data)
        if kind in ("mac", "ip", "model"):
            _add(f, kind, val)
        elif kind == "serial":
            if _PREFIX.match(data):
                _add(f, "serial", val)
            else:
                plain_ids.append(val)
        elif kind in ("url", "text"):
            f.others.append((kind, val))
    if text:
        _from_text(f, text, fuzzy=True)
    # A bare barcode: if the label text names it, keep that, else it's the
    # serial (what gear barcodes nearly always carry), extra ones go to others.
    for v in plain_ids:
        if v in (f.serial, f.model):
            continue
        if not f.serial:
            f.serial = v
        else:
            f.others.append(("code", v))
    return f
