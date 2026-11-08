"""Detect discs inserted/removed through the door (live-verified 2026-11-08, PROT §9.4).

Observed on the CD-425M: 0x15 [01] while the door is open (no disc loaded, status burst without 0x14),
0x15 [00] when it is closed; then the 360° disc detection runs with play state 0x60 ('searching');
after ~20 s the previously loaded disc is back.
The changer does not report *which* slots changed, so the slot list (no mechanics, ~1 s) is compared
with the library:

* trigger (0x15 door open/closed) -> once the door is closed and the detection has finished (or at most
  60 s of 'searching'; the end of the spin is not necessarily reported), poll the slot list every few
  seconds until two reads are identical, then compare;
* fallback: compare every `idle_interval` seconds while nothing else runs.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal


class SlotWatcher(QObject):
    changed = Signal()              # occupied slots differ from the library -> caller starts a quick scan

    def __init__(self, backend, db, scan, parent: QObject | None = None,
                 poll_ms: int = 5000, idle_interval: int = 60, settle_timeout: float = 180.0) -> None:
        super().__init__(parent)
        self.backend, self.db, self.scan = backend, db, scan
        self.settle_timeout = settle_timeout
        self._last: frozenset | None = None
        self._until = 0.0               # settle mode active until this time
        self._busy = False
        self._searching = False
        self.door_open = False
        self._t0 = 0.0
        self._poll = QTimer(self)
        self._poll.setInterval(poll_ms)
        self._poll.timeout.connect(self._tick)
        self._idle = QTimer(self)
        self._idle.setInterval(idle_interval * 1000)
        self._idle.timeout.connect(self._idle_check)

    # ------------------------------------------------------------------ inputs
    def start(self) -> None:
        self._idle.start()

    def stop(self) -> None:
        self._poll.stop()
        self._idle.stop()
        self._until = 0.0

    def on_status(self, st: dict, changed: list) -> None:
        self._searching = st.get("play_state") == "searching"
        self.door_open = st.get("changer_event") == 1
        if "*" in changed:
            if self.door_open:                       # connected while the door is open
                self.trigger()
            return
        if "event_count" in changed:
            self.trigger()

    def trigger(self) -> None:
        """Door activity: wait until the disc detection has finished, then compare."""
        self._t0 = time.monotonic()
        self._until = self._t0 + self.settle_timeout
        self._last = None
        if not self._poll.isActive():
            self._poll.start()

    # ------------------------------------------------------------------ work
    def _can_run(self) -> bool:
        return bool(self.backend.svc) and self.backend.connected and not self.scan.busy and not self._busy

    def _read(self, cb) -> None:
        svc = self.backend.svc
        self._busy = True

        def done(ok, res):
            self._busy = False
            cb(frozenset(s.disc for s in res) if ok and res else None)   # empty list = changer busy
        self.backend.run_async(lambda: svc.read_slot_list(), done, report_errors=False)

    def _tick(self) -> None:
        if time.monotonic() > self._until:
            self._poll.stop()
            return
        waiting_for_spin = self._searching and time.monotonic() - self._t0 < 60
        if self.door_open or waiting_for_spin or not self._can_run():
            return

        def got(slots):
            if slots is None:                        # changer busy (still detecting) -> next tick
                return
            if slots == self._last:                  # stable twice in a row -> done
                self._poll.stop()
                self._until = 0.0
                self._compare(slots)
            self._last = slots
        self._read(got)

    def _idle_check(self) -> None:
        if self._poll.isActive() or self.door_open or not self._can_run():
            return
        self._read(lambda slots: slots is not None and self._compare(slots))

    def _compare(self, slots: frozenset) -> None:
        if slots != frozenset(self.db.present_slots()):
            self.changed.emit()
