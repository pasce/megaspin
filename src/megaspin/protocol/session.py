"""Session engine: the only code that talks to the transport (PROT §4).

Session types
  A  command:     ENQ->ACK, n x (frame->ACK), EOT->ACK
  B  request:     ENQ->ACK, frame->ACK, changer sends m frames (each ACKed), changer EOT -> ACK
  C  unsolicited: changer ENQ -> ACK, frame -> ACK, EOT -> ACK

All timing-critical replies (ACK/NAK) are produced in the engine thread.
"""
from __future__ import annotations

import heapq
import itertools
import logging
import random
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable

from .codec import BadFrame, Ctrl, Frame, FrameParser, Message
from .constants import ACK, ENQ, EOT, NAK
from .transport import Transport

log = logging.getLogger(__name__)


class ChangerError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


@dataclass
class Timeouts:
    enq: float = 0.3            # ENQ -> ACK
    enq_tries: int = 5
    busy_tries: int = 10        # EOT received instead of ACK
    frame: float = 1.0          # frame -> ACK
    frame_tries: int = 4
    eot: float = 0.5
    eot_tries: int = 4
    first_reply: float = 5.0    # request: first answer frame
    inter_reply: float = 3.0    # between answer frames (CD-TEXT pauses up to ~0.4 s)
    unsolicited: float = 3.0    # idle time inside a changer-initiated session
    dedupe: float = 2.5


@dataclass(order=True)
class _QItem:
    priority: int
    seq: int
    job: "Job" = field(compare=False)


@dataclass
class Job:
    kind: str                                   # "command" | "request"
    sessions: list[list[bytes]] = field(default_factory=list)   # command: frames per session
    frame: bytes = b""                          # request frame
    first_timeout: float | None = None
    inter_timeout: float | None = None
    future: Future = field(default_factory=Future)
    label: str = ""


RawCallback = Callable[[str, bytes, float], None]       # direction "RX"/"TX", data, time
FrameCallback = Callable[[Frame], None]
OnlineCallback = Callable[[bool], None]


class SessionEngine:
    def __init__(self, transport: Transport, *, timeouts: Timeouts | None = None,
                 on_unsolicited: FrameCallback | None = None, on_raw: RawCallback | None = None,
                 on_online: OnlineCallback | None = None, on_idle: Callable[[float], None] | None = None,
                 idle_interval: float = 10.0) -> None:
        self.t = timeouts or Timeouts()
        self._tr = transport
        self._parser = FrameParser()
        self._pending: deque[Message] = deque()
        self._queue: list[_QItem] = []
        self._qlock = threading.Lock()
        self._seq = itertools.count()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_unsolicited = on_unsolicited
        self.on_raw = on_raw
        self.on_online = on_online
        self.on_idle = on_idle
        self.idle_interval = idle_interval
        self._online: bool | None = None
        self._last_traffic = time.monotonic()
        self._last_idle_cb = time.monotonic()
        self._last_unsolicited: tuple[int, bytes, float] | None = None
        self.stats = {"rx_frames": 0, "tx_frames": 0, "nak_sent": 0, "bad_frames": 0, "dupes": 0}

    # ------------------------------------------------------------------ public API
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="megaspin-session", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        with self._qlock:
            items, self._queue = self._queue, []
        for it in items:
            if not it.job.future.done():
                it.job.future.set_exception(ChangerError("STOPPED"))

    @property
    def online(self) -> bool:
        return bool(self._online)

    def submit(self, job: Job, priority: int = 2) -> Future:
        with self._qlock:
            heapq.heappush(self._queue, _QItem(priority, next(self._seq), job))
        return job.future

    def command(self, *sessions: list[bytes] | bytes, priority: int = 1, label: str = "") -> Future:
        """Each positional argument is one session (a frame or a list of frames)."""
        sess = [[s] if isinstance(s, (bytes, bytearray)) else list(s) for s in sessions]
        return self.submit(Job("command", sessions=sess, label=label), priority)

    def request(self, frame: bytes, *, priority: int = 2, first_timeout: float | None = None,
                inter_timeout: float | None = None, label: str = "") -> Future:
        return self.submit(Job("request", frame=frame, first_timeout=first_timeout,
                               inter_timeout=inter_timeout, label=label), priority)

    @property
    def queue_length(self) -> int:
        with self._qlock:
            return len(self._queue)

    # ------------------------------------------------------------------ I/O helpers
    def _write(self, data: bytes) -> None:
        self._tr.write(data)
        if len(data) > 1:
            self.stats["tx_frames"] += 1
        if self.on_raw:
            self.on_raw("TX", data, time.time())

    def _ack(self) -> None:
        self._write(bytes([ACK]))

    def _next(self, timeout: float) -> Message | None:
        end = time.monotonic() + timeout
        while not self._pending:
            if self._stop.is_set():
                return None
            remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            data = self._tr.read(min(remaining, 0.05))
            now = time.monotonic()
            if data:
                self._last_traffic = now
                if self.on_raw:
                    self.on_raw("RX", data, time.time())
            for m in self._parser.feed(data, now):
                self._pending.append(m)
        return self._pending.popleft()

    def _set_online(self, value: bool) -> None:
        if self._online != value:
            self._online = value
            if self.on_online:
                try:
                    self.on_online(value)
                except Exception:
                    log.exception("on_online callback failed")

    def _dispatch_unsolicited(self, fr: Frame) -> None:
        self.stats["rx_frames"] += 1
        now = time.monotonic()
        last = self._last_unsolicited
        if last and last[0] == fr.ftype and last[1] == fr.payload and now - last[2] < self.t.dedupe:
            self.stats["dupes"] += 1
            return
        self._last_unsolicited = (fr.ftype, fr.payload, now)
        if self.on_unsolicited:
            try:
                self.on_unsolicited(fr)
            except Exception:
                log.exception("on_unsolicited callback failed")

    # ------------------------------------------------------------------ main loop
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                m = self._next(0.03) if not self._pending else self._pending.popleft()
                if m is not None:
                    self._handle_idle(m)
                    continue
                item = None
                with self._qlock:
                    if self._queue:
                        item = heapq.heappop(self._queue)
                if item:
                    self._execute(item.job)
                    continue
                now = time.monotonic()
                if self.on_idle and now - self._last_idle_cb >= self.idle_interval:
                    self._last_idle_cb = now
                    self.on_idle(now - self._last_traffic)
            except Exception:
                log.exception("session loop error")
                time.sleep(0.1)

    def _handle_idle(self, m: Message) -> None:
        if isinstance(m, Ctrl):
            if m.byte == ENQ:
                self._serve_changer_session()
            elif m.byte == EOT:
                self._ack()
        elif isinstance(m, Frame):          # frame outside a session: ack and use it
            self._ack()
            self._dispatch_unsolicited(m)
        elif isinstance(m, BadFrame):
            self.stats["bad_frames"] += 1
            self._write(bytes([NAK]))

    def _serve_changer_session(self) -> None:
        """Type C: changer ENQ already received."""
        self._ack()
        self._set_online(True)
        while True:
            m = self._next(self.t.unsolicited)
            if m is None:
                return
            if isinstance(m, Frame):
                self._ack()
                self._dispatch_unsolicited(m)
            elif isinstance(m, BadFrame):
                self.stats["bad_frames"] += 1
                self.stats["nak_sent"] += 1
                self._write(bytes([NAK]))
            elif m.byte == EOT:
                self._ack()
                return
            elif m.byte == ENQ:             # changer repeated ENQ (our ACK was late)
                self._ack()

    # ------------------------------------------------------------------ job execution
    def _execute(self, job: Job) -> None:
        fut = job.future
        if not fut.set_running_or_notify_cancel():
            return
        try:
            if job.kind == "command":
                for frames in job.sessions:
                    self._open_session()
                    for f in frames:
                        self._send_frame(f)
                    self._close_session()
                result = None
            else:
                self._open_session()
                self._send_frame(job.frame)
                result = self._collect(job.first_timeout or self.t.first_reply,
                                       job.inter_timeout or self.t.inter_reply)
            self._set_online(True)
            fut.set_result(result)
        except ChangerError as e:
            if e.code == "NOT_RESPONDING":
                self._set_online(False)
            fut.set_exception(e)
        except Exception as e:  # pragma: no cover - safety net
            fut.set_exception(e)

    def _open_session(self) -> None:
        enq_fail = busy = 0
        while True:
            self._write(bytes([ENQ]))
            end = time.monotonic() + self.t.enq
            got = None
            while True:
                m = self._next(max(0.0, end - time.monotonic()))
                if m is None:
                    break
                if isinstance(m, Ctrl):
                    got = m.byte
                    break
                if isinstance(m, Frame):       # stray frame: acknowledge, keep waiting
                    self._ack()
                    self._dispatch_unsolicited(m)
                elif isinstance(m, BadFrame):
                    self._write(bytes([NAK]))
            if got == ACK:
                return
            if got == EOT:                      # changer busy
                self._ack()
                busy += 1
                if busy >= self.t.busy_tries:
                    raise ChangerError("BUSY", "changer keeps answering EOT")
                time.sleep(random.uniform(0.15, 0.4))
                continue
            if got == ENQ:                      # collision: changer wants to talk first
                self._serve_changer_session()
                continue
            enq_fail += 1
            if enq_fail >= self.t.enq_tries:
                raise ChangerError("NOT_RESPONDING", "no ACK on ENQ")

    def _send_frame(self, frame: bytes) -> None:
        for _ in range(self.t.frame_tries):
            self._write(frame)
            end = time.monotonic() + self.t.frame
            while True:
                m = self._next(max(0.0, end - time.monotonic()))
                if m is None:
                    break
                if isinstance(m, Ctrl):
                    if m.byte == ACK:
                        return
                    if m.byte == EOT:
                        self._ack()
                        raise ChangerError("BUSY", "EOT instead of ACK")
                    if m.byte == NAK:
                        break
        raise ChangerError("NOT_ACKED", "frame not acknowledged")

    def _close_session(self) -> None:
        for _ in range(self.t.eot_tries):
            self._write(bytes([EOT]))
            end = time.monotonic() + self.t.eot
            while True:
                m = self._next(max(0.0, end - time.monotonic()))
                if m is None:
                    break
                if isinstance(m, Ctrl) and m.byte == ACK:
                    return
                if isinstance(m, Ctrl) and m.byte == ENQ:     # changer already starts a new session
                    self._pending.appendleft(m)
                    return
        log.warning("EOT not acknowledged")

    def _collect(self, first: float, inter: float) -> list[Frame]:
        frames: list[Frame] = []
        timeout = first
        while True:
            m = self._next(timeout)
            if m is None:
                raise ChangerError("TIMEOUT", f"no reply after {len(frames)} frame(s)")
            if isinstance(m, Frame):
                self._ack()
                self.stats["rx_frames"] += 1
                frames.append(m)
                timeout = inter
            elif isinstance(m, BadFrame):
                self.stats["bad_frames"] += 1
                self.stats["nak_sent"] += 1
                self._write(bytes([NAK]))
            elif m.byte == EOT:
                self._ack()
                return frames
            elif m.byte == ENQ:
                self._ack()
