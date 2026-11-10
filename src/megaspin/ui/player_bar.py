"""Player bar at the bottom (Desktop_App_Design §8.6)."""
from __future__ import annotations
from ..i18n import tr

import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from .icons import icon
from .theme import COLORS

PLAY_STATE_TEXT = {
    "stopped": tr("Stopped"), "stopping": tr("Stopping…"), "searching": tr("Searching…"), "playing": tr("Playing"),
    "paused": tr("Pause"), "ff": tr("Fast forward"), "rew": tr("Rewind"), "unknown": "–",
}


def fmt_time(sec: float | None) -> str:
    if sec is None:
        return "–:––"
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class PositionEstimator:
    """The changer reports no playing time (not even while spooling); estimate it from state changes.

    FF/REW speed measured live on the CD-425M: about 16x (PROT §7.3)."""

    SPEED = {"playing": 1.0, "ff": 16.0, "rew": -16.0}

    def __init__(self) -> None:
        self.key = None
        self.base = 0.0
        self.since: float | None = None
        self.rate = 0.0
        self.length: float | None = None
        self.spooled = False            # FF/REW happened in this track -> estimate is unreliable

    def _clamp(self, v: float) -> float:
        v = max(0.0, v)
        return min(v, self.length) if self.length else v

    def update(self, disc: int, track: int, state: str) -> None:
        key = (disc, track)
        now = time.monotonic()
        rate = self.SPEED.get(state, 0.0)
        if key != self.key:
            self.key, self.base = key, 0.0
            self.spooled = state in ("ff", "rew")
            self.since, self.rate = (now, rate) if rate else (None, 0.0)
            return
        if self.since is not None:                       # close the running segment
            self.base = self._clamp(self.base + (now - self.since) * self.rate)
            self.since = None
        if state in ("stopped", "searching"):
            self.base, self.rate = 0.0, 0.0
            return
        if rate:
            self.since, self.rate = now, rate
        if state in ("ff", "rew"):
            self.spooled = True

    def value(self) -> float:
        if self.since is None:
            return self._clamp(self.base)
        return self._clamp(self.base + (time.monotonic() - self.since) * self.rate)


class PlayerBar(QWidget):
    keyRequested = Signal(str, str)      # key name, action (tap|press|release)
    playPauseRequested = Signal()

    def __init__(self, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlayerBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.accent = accent
        self.track_length: int | None = None
        self.est = PositionEstimator()
        self._state = "unknown"

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(6)

        def btn(name: str, tip: str, size: int = 22) -> QToolButton:
            b = QToolButton(self)
            b.setIcon(icon(name))
            b.setIconSize(QSize(size, size))
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            return b

        self.b_prev = btn("prev", tr("Previous track (Ctrl+←)"))
        self.b_play = btn("play", tr("Play/Pause (space)"), 24)
        self.b_play.setObjectName("PlayButton")
        self.b_next = btn("next", tr("Next track (Ctrl+→)"))
        self.b_stop = btn("stop", tr("Stop (Ctrl+.)"))
        self.b_rew = btn("rew", tr("Rewind – hold"))
        self.b_ff = btn("ff", tr("Fast forward – hold"))
        for b in (self.b_prev, self.b_play, self.b_next, self.b_stop):
            lay.addWidget(b)
        lay.addSpacing(10)
        lay.addWidget(self.b_rew)
        lay.addWidget(self.b_ff)
        lay.addSpacing(18)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.l_title = QLabel(tr("Not connected"))
        self.l_title.setObjectName("Title")
        self.l_sub = QLabel("")
        self.l_sub.setObjectName("Subtitle")
        self.l_playlist = QLabel("")
        self.l_playlist.setStyleSheet(f"color: {accent}; font-weight: 600;")
        self.l_playlist.hide()
        info.addWidget(self.l_playlist)
        info.addWidget(self.l_title)
        info.addWidget(self.l_sub)
        lay.addLayout(info, 2)

        posbox = QVBoxLayout()
        posbox.setSpacing(4)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setRange(0, 1000)
        self.progress.setToolTip(tr("Estimated position (the changer does not report playing time)"))
        self.l_time = QLabel("–:–– / –:––")
        self.l_time.setObjectName("Subtitle")
        self.l_time.setAlignment(Qt.AlignmentFlag.AlignRight)
        posbox.addStretch()
        posbox.addWidget(self.progress)
        posbox.addWidget(self.l_time)
        posbox.addStretch()
        w = QWidget()
        w.setLayout(posbox)
        w.setMinimumWidth(260)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(w, 3)
        lay.addSpacing(18)

        self.b_repeat = btn("repeat", tr("Repeat (Ctrl+R)"), 20)
        self.b_random = btn("shuffle", tr("Random: off → 1 disc → all (Ctrl+S)"), 20)
        self.l_random = QLabel("")
        self.l_random.setObjectName("Subtitle")
        lay.addWidget(self.b_repeat)
        lay.addWidget(self.b_random)
        lay.addWidget(self.l_random)

        self.b_prev.clicked.connect(lambda: self.keyRequested.emit("prev", "tap"))
        self.b_next.clicked.connect(lambda: self.keyRequested.emit("next", "tap"))
        self.b_stop.clicked.connect(lambda: self.keyRequested.emit("stop", "tap"))
        self.b_play.clicked.connect(self.playPauseRequested.emit)
        self.b_repeat.clicked.connect(lambda: self.keyRequested.emit("repeat", "tap"))
        self.b_random.clicked.connect(lambda: self.keyRequested.emit("random", "tap"))
        self.b_ff.pressed.connect(lambda: self.keyRequested.emit("ff", "press"))
        self.b_ff.released.connect(lambda: self.keyRequested.emit("ff", "release"))
        self.b_rew.pressed.connect(lambda: self.keyRequested.emit("rew", "press"))
        self.b_rew.released.connect(lambda: self.keyRequested.emit("rew", "release"))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        self.set_enabled(False)

    def set_enabled(self, on: bool) -> None:
        for b in (self.b_prev, self.b_play, self.b_next, self.b_stop, self.b_rew, self.b_ff,
                  self.b_repeat, self.b_random):
            b.setEnabled(on)

    def set_accent(self, accent: str, status: dict | None = None) -> None:
        self.accent = accent
        self.l_playlist.setStyleSheet(f"color: {accent}; font-weight: 600;")
        if status is not None:
            self.update_status(status)

    def set_playlist(self, text: str) -> None:
        self.l_playlist.setText(tr("Playlist: {0}").format(text) if text else "")
        self.l_playlist.setVisible(bool(text))

    def set_now_playing(self, title: str, subtitle: str, track_length: int | None) -> None:
        self.l_title.setText(title)
        self.l_sub.setText(subtitle)
        self.track_length = track_length
        self.est.length = float(track_length) if track_length else None

    def update_status(self, st: dict) -> None:
        self._state = st.get("play_state", "unknown")
        self.est.update(st.get("disc", 0), st.get("track", 0), self._state)
        playing = self._state in ("playing", "ff", "rew")
        self.b_play.setIcon(icon("pause" if playing else "play"))
        on = COLORS["text"]
        self.b_repeat.setIcon(icon("repeat", self.accent if st.get("repeat") else on))
        rnd = st.get("random", "off")
        self.b_random.setIcon(icon("shuffle", self.accent if rnd != "off" else on))
        self.l_random.setText({"one": tr("1 disc"), "all": tr("All")}.get(rnd, ""))
        self._tick()

    @property
    def play_state(self) -> str:
        return self._state

    def _tick(self) -> None:
        pos = self.est.value() if self._state not in ("stopped", "unknown", "searching") else None
        length = self.track_length
        rough = pos is not None and self.est.spooled
        self.l_time.setText(("≈ " if rough else "") + f"{fmt_time(pos)} / {fmt_time(length)}")
        self.l_time.setToolTip(
            tr("Imprecise after spooling: the changer does not report a playing position.\nThe display is correct again from the next track.") if rough else
            tr("Estimated from start and pauses (the changer does not report playing time)."))
        if pos is not None and length:
            self.progress.setValue(int(min(1.0, pos / length) * 1000))
        else:
            self.progress.setValue(0)
