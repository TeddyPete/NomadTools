"""Tiny WebSocket client (text frames only), enough for LG webOS and Samsung
Tizen remotes. Standard library only."""
from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct

from .base import DisplayError


class WebSocket:
    def __init__(self, host: str, port: int, path: str = "/", tls: bool = False, timeout: float = 5.0):
        self.host, self.port = host, port
        try:
            raw = socket.create_connection((host, port), timeout)
        except OSError as e:
            raise DisplayError(f"No answer from {host}:{port} ({e.__class__.__name__})")
        raw.settimeout(timeout)
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE      # TVs use self-signed certificates
            try:
                raw = ctx.wrap_socket(raw, server_hostname=host)
            except (ssl.SSLError, OSError) as e:
                raw.close()
                raise DisplayError(f"TLS failed ({e.__class__.__name__})")
        self.s = raw
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        try:
            self.s.sendall(req.encode())
            buf = b""
            while b"\r\n\r\n" not in buf:
                c = self.s.recv(1024)
                if not c:
                    raise DisplayError("Connection closed during handshake")
                buf += c
                if len(buf) > 16384:
                    raise DisplayError("Bad handshake")
        except socket.timeout:
            self.close()
            raise DisplayError("No WebSocket answer")
        head, self._rest = buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101" not in status:
            self.close()
            raise DisplayError(f"Refused: {status[9:40]}")

    def settimeout(self, t: float) -> None:
        self.s.settimeout(t)

    def _recvall(self, n: int) -> bytes:
        b = self._rest[:n]
        self._rest = self._rest[n:]
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c:
                raise DisplayError("Connection closed")
            b += c
        return b

    def send(self, obj) -> None:
        data = (obj if isinstance(obj, str) else json.dumps(obj)).encode()
        self._frame(0x1, data)

    def _frame(self, op: int, data: bytes) -> None:
        mask = os.urandom(4)
        n = len(data)
        h = bytes([0x80 | op])
        if n < 126:
            h += bytes([0x80 | n])
        elif n < 65536:
            h += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            h += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.s.sendall(h + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv_text(self) -> str:
        parts = b""
        while True:
            h = self._recvall(2)
            fin, op = h[0] & 0x80, h[0] & 0x0F
            n = h[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recvall(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recvall(8))[0]
            mask = self._recvall(4) if h[1] & 0x80 else None
            data = self._recvall(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 0x8:
                raise DisplayError("TV closed the connection")
            if op == 0x9:
                self._frame(0xA, data)       # pong
                continue
            if op == 0xA:
                continue
            parts += data
            if fin:
                return parts.decode("utf-8", "replace")

    def recv(self):
        try:
            return json.loads(self.recv_text())
        except socket.timeout:
            raise DisplayError("TV stopped answering")
        except ValueError:
            return {}

    def close(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass
