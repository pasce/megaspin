"""Choose a MusicBrainz match (Desktop_App_Design §9.4)."""
from __future__ import annotations
from ...i18n import tr

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..player_bar import fmt_time


class MatchSelectDialog(QDialog):
    _results = Signal(list)

    def __init__(self, slot: int, album, candidates: list, meta, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Choose metadata – disc #{0}").format(slot))
        self.resize(900, 560)
        self.slot, self.meta, self.album = slot, meta, album
        self.cands = list(candidates)
        self.choice = None          # Candidate | None
        self.none_fits = False

        lay = QVBoxLayout(self)
        t = QLabel(tr("Which album is in slot {0}?").format(slot))
        t.setObjectName("Title")
        lay.addWidget(t)
        known = " – ".join(x for x in (album.artist, album.album) if x) or tr("unknown")
        info = QLabel(tr("Known: {0} · {1} tracks").format(known, album.track_count or '?')
                      + (f" · {fmt_time(album.duration_s)}" if album.duration_s else ""))
        info.setObjectName("Subtitle")
        lay.addWidget(info)

        srow = QHBoxLayout()
        self.q = QLineEdit(" ".join(x for x in (album.artist, album.album) if x))
        self.q.setPlaceholderText(tr("Search manually: artist and album"))
        b_search = QPushButton(tr("Search"))
        b_search.clicked.connect(self._search)
        self.q.returnPressed.connect(self._search)
        srow.addWidget(self.q, 1)
        srow.addWidget(b_search)
        lay.addLayout(srow)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Score", tr("Artist"), tr("Album"), tr("Year"), tr("Country"), "Label", "CD", tr("Ø dev.")])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.currentItemChanged.connect(self._preview)
        self.tree.itemDoubleClicked.connect(lambda *_: self._take())
        self.tracks = QListWidget()
        split.addWidget(self.tree)
        split.addWidget(self.tracks)
        split.setSizes([600, 300])
        lay.addWidget(split, 1)
        self.status = QLabel("")
        self.status.setObjectName("Subtitle")
        lay.addWidget(self.status)

        row = QHBoxLayout()
        b_none = QPushButton(tr("None fits"))
        b_none.setToolTip(tr("Do not use MusicBrainz data (CD-TEXT/memory titles stay)"))
        b_none.clicked.connect(self._none)
        b_cancel = QPushButton(tr("Cancel"))
        b_cancel.clicked.connect(self.reject)
        self.b_ok = QPushButton(tr("Apply"))
        self.b_ok.setObjectName("Primary")
        self.b_ok.clicked.connect(self._take)
        row.addWidget(b_none)
        row.addStretch()
        row.addWidget(b_cancel)
        row.addWidget(self.b_ok)
        lay.addLayout(row)

        self._results.connect(self._on_results)
        self._fill()

    def _fill(self) -> None:
        self.tree.clear()
        for i, c in enumerate(self.cands):
            disc = f"{c.medium}/{c.medium_count}" if c.medium_count > 1 else ""
            diff = c.details.get("avg_diff_s") if c.details else None
            it = QTreeWidgetItem([f"{c.score:.2f}", c.artist, c.title, str(c.year or ""), c.country, c.label,
                                  disc, f"{diff} s" if diff is not None else ""])
            it.setData(0, Qt.ItemDataRole.UserRole, i)
            self.tree.addTopLevelItem(it)
        for col in (0, 1, 3, 4, 5, 6, 7):
            self.tree.resizeColumnToContents(col)
        if self.cands:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.status.setText(tr("{0} matches").format(len(self.cands)) if self.cands
                            else tr("No matches – search manually?"))
        self.b_ok.setEnabled(bool(self.cands))

    def _preview(self, it, _prev=None) -> None:
        self.tracks.clear()
        if not it:
            return
        c = self.cands[it.data(0, Qt.ItemDataRole.UserRole)]
        for n, (title, length) in enumerate(c.tracks, 1):
            self.tracks.addItem(f"{n:>2}  {title}  {fmt_time(length) if length else ''}")

    def _search(self) -> None:
        text = self.q.text().strip()
        if not text:
            return
        self.status.setText(tr("Searching MusicBrainz …"))
        self.meta.search(self.slot, text, lambda res: self._results.emit(res))

    def _on_results(self, res: list) -> None:
        self.cands = res
        self._fill()

    def _take(self) -> None:
        it = self.tree.currentItem()
        if it:
            self.choice = self.cands[it.data(0, Qt.ItemDataRole.UserRole)]
            self.accept()

    def _none(self) -> None:
        self.none_fits = True
        self.accept()
