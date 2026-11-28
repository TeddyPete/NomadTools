"""Model identification uses CAT replies, independent of the Bluetooth alias."""

import re

MODEL_NAMES = ("TH-D75", "TH-D74", "TM-D750")


def model_from_id(line):
    match = re.fullmatch(r"ID (TH-D75|TH-D74|TM-D750)([AE])?", line)
    return match[1] if match else None


def discovery_candidate(name, uuids):
    return (any(name.upper().startswith(model) for model in MODEL_NAMES)
            or "00001101-0000-1000-8000-00805f9b34fb" in {str(uuid).lower() for uuid in uuids})
