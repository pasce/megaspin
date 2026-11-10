"""Protokoll-Konsole (Desktop_App_Design §9.8): live list of all bytes between PC and changer."""
from __future__ import annotations
from ...i18n import tr

import time
from collections import deque
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ...protocol.codec import Ctrl, FrameParser
from ...protocol.describe import describe
from ..theme import COLORS

MAX_ENTRIES = 20_000
MAX_SHOWN = 3_000


class ProtocolConsole(QDialog):
    """Collects all traffic from the moment the program starts (also while hidden)."""

    def __init__(self, backend, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Protocol console"))
        self.resize(980, 560)
        self.setModal(False)
        self.entries: deque[tuple[float, str, bytes, str, bool]] = deque(maxlen=MAX_ENTRIES)
        self._parsers = {"RX": FrameParser(), "TX": FrameParser()}
        self._pending: list = []
        self.paused = False

        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.b_pause = QPushButton(tr("Pause"))
        self.b_pause.setCheckable(True)
        self.b_pause.toggled.connect(self._toggle_pause)
        self.b_clear = QPushButton(tr("Clear"))
        self.b_clear.clicked.connect(self.clear)
        self.cb_ctrl = QCheckBox(tr("Hide ENQ/ACK/EOT"))
        self.cb_ctrl.setChecked(True)
        self.cb_ctrl.toggled.connect(self._rebuild)
        self.cb_status = QCheckBox(tr("status messages only"))
        self.cb_status.setToolTip(tr("Only the unsolicited messages from the changer (0x12–0x15)"))
        self.cb_status.toggled.connect(self._rebuild)
        self.e_filter = QLineEdit()
        self.e_filter.setPlaceholderText(tr("Filter (text or hex) …"))
        self.e_filter.setClearButtonEnabled(True)
        self.e_filter.textChanged.connect(self._rebuild)
        self.b_save = QPushButton(tr("Save to file …"))
        self.b_save.clicked.connect(self.save)
        for w in (self.b_pause, self.b_clear, self.cb_ctrl, self.cb_status):
            bar.addWidget(w)
        bar.addWidget(self.e_filter, 1)
        bar.addWidget(self.b_save)
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("Time"), "", tr("Meaning"), tr("Bytes")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(2, 430)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._mono = QFont(mono)
        lay.addWidget(self.tree, 1)
        self.l_info = QLabel()
        self.l_info.setObjectName("Subtitle")
        lay.addWidget(self.l_info)

        self._flush_timer = QTimer(self)          # batch UI updates (traffic can be bursty)
        self._flush_timer.setInterval(150)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()
        backend.rawData.connect(self.on_raw)

    # ------------------------------------------------------------------ data
    def on_raw(self, direction: str, data: bytes, t: float) -> None:
        parser = self._parsers.get(direction)
        if parser is None:
            return
        for m in parser.feed(data, time.monotonic()):
            raw = bytes([m.byte]) if isinstance(m, Ctrl) else (m.to_bytes() if hasattr(m, "to_bytes")
                                                               else getattr(m, "raw", b""))
            entry = (t, direction, raw, describe(m), isinstance(m, Ctrl))
            self.entries.append(entry)
            self._pending.append(entry)

    def _visible(self, e) -> bool:
        _t, _d, raw, text, is_ctrl = e
        if is_ctrl and self.cb_ctrl.isChecked():
            return False
        if self.cb_status.isChecked() and not (len(raw) > 1 and 0x12 <= raw[1] <= 0x15):
            return False
        q = self.e_filter.text().strip().lower()
        if q and q not in text.lower() and q.replace(" ", "") not in raw.hex():
            return False
        return True

    def _item(self, e) -> QTreeWidgetItem:
        t, d, raw, text, is_ctrl = e
        ts = datetime.fromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]
        it = QTreeWidgetItem([ts, tr("PC → changer") if d == "TX" else tr("changer → PC"), text, raw.hex(" ").upper()])
        it.setFont(3, self._mono)
        it.setFont(0, self._mono)
        color = QColor("#7FB7FF") if d == "TX" else QColor("#8CD98C")
        it.setForeground(1, color)
        if is_ctrl:
            for c in range(4):
                it.setForeground(c, QColor(COLORS["text2"]))
        return it

    def _flush(self) -> None:
        if not self.isVisible():
            self._pending = []                    # rebuilt from self.entries when shown
            return
        if self.paused or not self._pending:
            return
        items = [self._item(e) for e in self._pending if self._visible(e)]
        self._pending = []
        if not items:
            return
        at_bottom = self.tree.verticalScrollBar().value() >= self.tree.verticalScrollBar().maximum() - 4
        self.tree.addTopLevelItems(items)
        over = self.tree.topLevelItemCount() - MAX_SHOWN
        for _ in range(max(0, over)):
            self.tree.takeTopLevelItem(0)
        if at_bottom:
            self.tree.scrollToBottom()
        self._update_info()

    def _rebuild(self) -> None:
        self.tree.clear()
        items = [self._item(e) for e in self.entries if self._visible(e)][-MAX_SHOWN:]
        self.tree.addTopLevelItems(items)
        self.tree.scrollToBottom()
        self._pending = []
        self._update_info()

    def _update_info(self) -> None:
        self.l_info.setText(tr("{0} entries saved (max. {1}), {2} shown").format(
            len(self.entries), MAX_ENTRIES, self.tree.topLevelItemCount())
                            + (tr(" · stopped") if self.paused else ""))

    # ------------------------------------------------------------------ actions
    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._rebuild()

    def _toggle_pause(self, on: bool) -> None:
        self.paused = on
        self.b_pause.setText(tr("Resume") if on else tr("Pause"))
        if not on:
            self._rebuild()
        self._update_info()

    def clear(self) -> None:
        self.entries.clear()
        self._pending = []
        self.tree.clear()
        self._update_info()

    def text_dump(self) -> str:
        lines = []
        for t, d, raw, text, _c in self.entries:
            ts = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            lines.append(f"{ts}  {d}  {raw.hex(' ').upper():<48}  {text}")
        return "\n".join(lines) + "\n"

    def save(self) -> None:
        name = datetime.now().strftime("megaspin-protokoll-%Y%m%d-%H%M%S.txt")
        path, _ = QFileDialog.getSaveFileName(self, tr("Save protocol"), name, tr("Text files (*.txt)"))
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text_dump())
