"""Program-controlled playback of playlists, genres and user files (Desktop_App_Design §10.6).

The changer only plays "disc d from track t onwards", so the program watches the status (0x12 / 0x13) and
starts the next entry when the current one has ended. Entry = (slot, track); track 0 = whole disc.

End of an entry (live-verified: after the last track the CD-425M goes on to the next occupied disc,
track 1 - also while FF is held - and reports 0x12 immediately, before the search/load):
* single track t: the changer moves on to t+1 on the same disc, or changes disc after the last track;
* whole disc: the changer changes disc after the last track (or stops); a jump from the last track back
  to track 1 (repeat) also counts as the end.
Track changes are tracked in every play state (also FF/REW), and the next entry is started at once,
so the changer's own move to the next disc is interrupted early.
Anything else (another disc chosen, stop in the middle, track jump) is a user action -> the playlist stops.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)
STABLE = ("playing", "paused", "stopped")


@dataclass
class Entry:
    slot: int
    track: int = 0          # 0 = whole disc

    @property
    def start_track(self) -> int:
        return self.track or 1


def prepare_changer(svc) -> None:
    """Plain track mode without random/repeat, otherwise the end of an entry cannot be detected."""
    st = svc.status
    if st.mode != "track":
        svc.reset_mode()
    for _ in range(3):
        if svc.status.random == "off":
            break
        before = svc.status.random
        svc.key("random")
        svc.wait_for(lambda s: s.random != before, 3.0)
    if svc.status.repeat:
        svc.key("repeat")
        svc.wait_for(lambda s: not s.repeat, 3.0)


class PlaylistPlayer(QObject):
    changed = Signal()                  # name / position changed (player bar label)
    finished = Signal(str)              # reason: "end" | "user" | "stopped" | "error"

    ARM_TIMEOUT_MS = 60_000             # disc load incl. search; entry is skipped afterwards

    def __init__(self, backend, last_track_fn, present_fn=lambda slot: True,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.last_track_fn = last_track_fn          # slot -> last track number or None (unknown)
        self.present_fn = present_fn
        self.name = ""
        self.entries: list[Entry] = []
        self.index = -1
        self.state = "idle"                         # idle | preparing | arming | playing
        self._seen_track = 0
        self._st: dict = {}
        self._arm_timer = QTimer(self)
        self._arm_timer.setSingleShot(True)
        self._arm_timer.timeout.connect(self._arm_timeout)

    # ------------------------------------------------------------------ public
    @property
    def active(self) -> bool:
        return self.state != "idle"

    @property
    def current(self) -> Entry | None:
        return self.entries[self.index] if 0 <= self.index < len(self.entries) else None

    def label(self) -> str:
        if not self.active:
            return ""
        return f"{self.name} ({max(self.index + 1, 1)}/{len(self.entries)})"

    def start(self, name: str, entries: list[tuple[int, int]] | list[Entry], shuffle: bool = False,
              start_index: int = 0) -> bool:
        items = [e if isinstance(e, Entry) else Entry(*e) for e in entries]
        items = [e for e in items if self.present_fn(e.slot)]
        if not items:
            return False
        if shuffle:
            random.shuffle(items)
            start_index = 0
        self.name, self.entries = name, items
        self.index = max(0, min(start_index, len(items) - 1)) - 1
        self.state = "preparing"                    # switching random/repeat off first
        self.changed.emit()
        self.backend.call(prepare_changer, lambda ok, _res: self._advance(+1))
        return True

    def stop(self, reason: str = "stopped") -> None:
        if not self.active:
            return
        log.info("playlist %r stopped (%s) at entry %d, last status %s", self.name, reason, self.index,
                 {k: self._st.get(k) for k in ("disc", "track", "play_state")})
        self.state = "idle"
        self._arm_timer.stop()
        self.changed.emit()
        self.finished.emit(reason)

    def next(self) -> None:
        if self.active:
            self._advance(+1)

    def prev(self) -> None:
        if self.active:
            self._advance(-1 if self.index > 0 else 0)

    def jump(self, index: int) -> None:
        if self.active and 0 <= index < len(self.entries):
            self.index = index - 1
            self._advance(+1)

    # ------------------------------------------------------------------ internals
    def _advance(self, step: int) -> None:
        if not self.active:
            return
        self.index += step
        if self.index >= len(self.entries):
            self.stop("end")
            return
        e = self.entries[self.index]
        log.info("playlist %r -> entry %d/%d %s", self.name, self.index + 1, len(self.entries), e)
        self._seen_track = 0
        st = self._st
        if step == 1 and st.get("disc") == e.slot and st.get("track") == e.start_track                 and st.get("play_state") == "playing":
            self.state = "playing"                   # the changer already went on to this track
            self._seen_track = e.start_track
            self.changed.emit()
            return
        self.state = "arming"
        self._arm_timer.start(self.ARM_TIMEOUT_MS)
        self.changed.emit()
        self.backend.play(e.slot, e.start_track)

    def _arm_timeout(self) -> None:
        if self.state == "arming":
            self._advance(+1)                        # disc missing / not playable -> skip

    def on_status(self, st: dict) -> None:
        self._st = st
        if not self.active:
            return
        log.info("playlist status disc=%s track=%s %s (state=%s seen=%s)", st.get("disc"), st.get("track"),
                 st.get("play_state"), self.state, self._seen_track)
        e = self.current
        if self.state == "preparing" or e is None:
            return
        disc, track, ps = st.get("disc", 0), st.get("track", 0), st.get("play_state", "")
        if self.state == "arming":
            if disc == e.slot and track == e.start_track and ps == "playing":
                self.state = "playing"
                self._seen_track = track
                self._arm_timer.stop()
            return
        last = self.last_track_fn(e.slot)
        transitional = ps in ("searching", "stopping")
        if e.track:                                  # ---- single track
            at_last = last is None or e.track >= last
            if disc == e.slot and track == e.track:
                if ps == "stopped":
                    self._advance(+1) if at_last else self.stop("user")
                return
            if disc == e.slot and track == e.track + 1:
                self._advance(+1)                    # track ended (or spooled past its end)
            elif disc != e.slot and at_last:
                self._advance(+1)                    # last track of the disc ended -> changer moved on
            elif not transitional:
                self.stop("user")
            return
        # ---- whole disc
        if disc == e.slot:
            at_last = last is None or self._seen_track >= last
            if ps == "stopped":
                self._advance(+1) if at_last and self._seen_track else self.stop("user")
                return
            if track == 1 and self._seen_track > 1 and at_last:
                self._advance(+1)                    # repeat jumped from the last track back to 1
            elif track:
                self._seen_track = track             # also while FF/REW
            return
        if last is None or self._seen_track >= last:
            self._advance(+1)                        # disc ended -> changer moved on to the next disc
        else:
            self.stop("user")
