"""Byte transports: real serial port and an in-memory pipe (for the simulator/tests)."""
from __future__ import annotations

import queue
import time
from typing import Protocol

from .constants import BAUDRATE


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float) -> bytes: ...
    def close(self) -> None: ...


class SerialTransport:
    """9600 8N2, no flow control (PROT §2)."""

    def __init__(self, port: str, baudrate: int = BAUDRATE) -> None:
        import serial  # pyserial
        self.port = port
        self._s = serial.Serial(port, baudrate, bytesize=8, parity="N", stopbits=2,
                                timeout=0.02, write_timeout=2, xonxoff=False, rtscts=False)
        self._s.reset_input_buffer()

    def write(self, data: bytes) -> None:
        self._s.write(data)

    def read(self, timeout: float) -> bytes:
        end = time.monotonic() + max(timeout, 0)
        while True:
            n = self._s.in_waiting
            if n:
                return self._s.read(n)
            data = self._s.read(1)          # waits up to 20 ms
            if data:
                more = self._s.in_waiting
                return data + (self._s.read(more) if more else b"")
            if time.monotonic() >= end:
                return b""

    def close(self) -> None:
        try:
            self._s.close()
        except Exception:
            pass


class PipeEnd:
    """One end of an in-memory full-duplex byte pipe."""

    def __init__(self, rx: "queue.Queue[bytes]", tx: "queue.Queue[bytes]") -> None:
        self._rx, self._tx = rx, tx
        self.closed = False

    def write(self, data: bytes) -> None:
        if data:
            self._tx.put(bytes(data))

    def read(self, timeout: float) -> bytes:
        try:
            chunk = self._rx.get(timeout=max(timeout, 0.001))
        except queue.Empty:
            return b""
        parts = [chunk]
        while True:
            try:
                parts.append(self._rx.get_nowait())
            except queue.Empty:
                break
        return b"".join(parts)

    def close(self) -> None:
        self.closed = True


def pipe_pair() -> tuple[PipeEnd, PipeEnd]:
    a2b: "queue.Queue[bytes]" = queue.Queue()
    b2a: "queue.Queue[bytes]" = queue.Queue()
    return PipeEnd(b2a, a2b), PipeEnd(a2b, b2a)
