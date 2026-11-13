"""Detect discs added or removed through the door.

The changer reports the door state with 0x15 (01 = open, 00 = closed). It does not say which slots changed,
so after the door has closed the slot list is read once and compared with the library.

Reads of the stored data are kept to a minimum on purpose (the changer's memory is EEPROM):
* no periodic slot reads while nothing happens,
* after "door closed" exactly one slot read, once the 360° disc detection has finished (play state
  'searching' is over and stayed over for `settle_s`),
* a read that comes back empty (changer still busy) is retried a few times, then given up.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal


class SlotWatcher(QObject):
    changed = Signal()              # occupied slots differ from the library -> caller starts a quick scan

    def __init__(self, backend, db, scan, parent: QObject | None = None,
                 poll_ms: int = 2000, settle_s: float = 2.0, max_wait_s: float = 120.0,
                 max_tries: int = 10) -> None:
        super().__init__(parent)
        self.backend, self.db, self.scan = backend, db, scan
        self.settle_s = settle_s
        self.max_wait_s = max_wait_s
        self.max_tries = max_tries
        self.door_open = False
        self._searching = False
        self._last_searching = 0.0
        self._deadline = 0.0          # 0 = nothing pending
        self._tries = 0
        self._busy = False
        self._poll = QTimer(self)     # retry/settle timer, only active while a check is pending
        self._poll.setInterval(poll_ms)
        self._poll.timeout.connect(self._tick)

    # ------------------------------------------------------------------ inputs
    def start(self) -> None:          # kept for the API; nothing runs until the door changes
        pass

    def stop(self) -> None:
        self._poll.stop()
        self._deadline = 0.0

    def on_status(self, st: dict, changed: list) -> None:
        self._searching = st.get("play_state") == "searching"
        if self._searching:
            self._last_searching = time.monotonic()
        was_open = self.door_open
        self.door_open = st.get("changer_event") == 1
        if "*" in changed:                              # status burst after connecting
            if self.door_open:                          # connected while the door is open: wait for close
                self._arm()
            return
        if was_open and not self.door_open:
            self._arm()                                 # door has just been closed (open -> closed only)

    # ------------------------------------------------------------------ work
    def _arm(self) -> None:
        self._deadline = time.monotonic() + self.max_wait_s
        self._tries = 0
        self._poll.start()

    def _can_run(self) -> bool:
        return bool(self.backend.svc) and self.backend.connected and not self.scan.busy and not self._busy

    def _tick(self) -> None:
        if not self._deadline:
            self._poll.stop()
            return
        now = time.monotonic()
        if now > self._deadline or self._tries >= self.max_tries:
            self._poll.stop()
            self._deadline = 0.0
            return
        if self.door_open or self._searching or now - self._last_searching < self.settle_s:
            return                                      # disc detection still running
        if not self._can_run():
            return
        self._poll.stop()
        self._read()

    def _read(self) -> None:
        svc = self.backend.svc
        self._busy = True

        def done(ok, res):
            self._busy = False
            slots = frozenset(s.disc for s in res) if ok and res else None   # empty list = changer busy
            self._got(slots)
        self.backend.run_async(lambda: svc.read_slot_list(), done, report_errors=False)

    def _got(self, slots) -> None:
        if slots is None:                               # busy or failed: try again shortly
            self._tries += 1
            if self._deadline and self._tries < self.max_tries:
                self._poll.start()
            return
        self._deadline = 0.0
        self._compare(slots)

    def _compare(self, slots: frozenset) -> None:
        if slots != frozenset(self.db.present_slots()):
            self.changed.emit()
