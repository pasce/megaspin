"""Frame encoding/decoding (PROT §3).

Frame: STX | TYPE | LEN_lo | LEN_hi | PAYLOAD[LEN] | CHK
CHK  = (-(TYPE + LEN_lo + LEN_hi + sum(PAYLOAD))) & 0xFF
LEN is a 16-bit little-endian value (the original VB program got this wrong).
"""
from __future__ import annotations

from dataclasses import dataclass

from .constants import CONTROL_BYTES, STX

MAX_PAYLOAD = 1024
INTER_BYTE_TIMEOUT = 0.2  # seconds of silence inside a frame -> discard


def checksum(body: bytes) -> int:
    """Checksum over TYPE, LEN_lo, LEN_hi and payload."""
    return (-sum(body)) & 0xFF


def build_frame(ftype: int, payload: bytes | bytearray | list[int] = b"") -> bytes:
    payload = bytes(payload)
    n = len(payload)
    if n > 0xFFFF:
        raise ValueError("payload too long")
    body = bytes([ftype & 0xFF, n & 0xFF, n >> 8]) + payload
    return bytes([STX]) + body + bytes([checksum(body)])


@dataclass(frozen=True)
class Ctrl:
    byte: int

    @property
    def name(self) -> str:
        return CONTROL_BYTES.get(self.byte, f"{self.byte:02X}")


@dataclass(frozen=True)
class Frame:
    ftype: int
    payload: bytes

    def to_bytes(self) -> bytes:
        return build_frame(self.ftype, self.payload)


@dataclass(frozen=True)
class BadFrame:
    raw: bytes


Message = Ctrl | Frame | BadFrame


class FrameParser:
    """Incremental parser: feed raw bytes, get control bytes and frames."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._last = 0.0
        self.garbage = 0

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes, now: float = 0.0) -> list[Message]:
        out: list[Message] = []
        if self._buf and now and self._last and now - self._last > INTER_BYTE_TIMEOUT:
            self.garbage += len(self._buf)  # incomplete frame timed out
            self._buf.clear()
        if data:
            self._last = now
        self._buf.extend(data)
        buf = self._buf
        while buf:
            b = buf[0]
            if b in CONTROL_BYTES:
                out.append(Ctrl(b))
                del buf[0]
                continue
            if b != STX:
                self.garbage += 1
                del buf[0]
                continue
            if len(buf) < 4:
                break
            n = buf[2] | (buf[3] << 8)
            if n > MAX_PAYLOAD:
                self.garbage += 1
                del buf[0]
                continue
            if len(buf) < n + 5:
                break
            raw = bytes(buf[: n + 5])
            del buf[: n + 5]
            if sum(raw[1:]) & 0xFF == 0:
                out.append(Frame(raw[1], raw[4:-1]))
            else:
                out.append(BadFrame(raw))
        return out


def hexs(data: bytes) -> str:
    return " ".join(f"{x:02X}" for x in data)
