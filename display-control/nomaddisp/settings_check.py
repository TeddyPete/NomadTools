"""Small validation helpers."""
import ipaddress


def valid_ip(s: str) -> bool:
    try:
        ipaddress.IPv4Address((s or "").strip())
        return True
    except ValueError:
        return False
