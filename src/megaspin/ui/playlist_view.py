"""Playlist view (Desktop_App_Design §9.7): entries of one playlist, reorder by drag & drop."""
from __future__ import annotations
from ..i18n import tr

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .icons import icon
from .player_bar import fmt_time
from .theme import COLORS

EntryRole = Qt.ItemDataRole.UserRole + 5


class _Tree(QTreeWidget):
    reordered = Signal()

    def dropEvent(self, ev) -> None:
        super().dropEvent(ev)
        self.reordered.emit()


class PlaylistView(QWidget):
    playRequested = Signal(int, int, bool)       # playlist id, start index, shuffle
    changed = Signal()                           # items/name changed (sidebar counts)
    renameRequested = Signal(int)
    deleteRequested = Signal(int)

    def __init__(self, db, cover_fn, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.db, self.cover_fn, self.accent = db, cover_fn, accent
        self.pid: int | None = None
        self.playing_index = -1

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        txt = QVBoxLayout()
        self.l_name = QLabel()
        self.l_name.setObjectName("Big")
        self.l_info = QLabel()
        self.l_info.setObjectName("Subtitle")
        txt.addWidget(self.l_name)
        txt.addWidget(self.l_info)
        head.addLayout(txt, 1)
        self.b_play = QToolButton()
        self.b_play.setObjectName("PlayButton")
        self.b_play.setIcon(icon("play", "#FFFFFF", 22))
        self.b_play.setToolTip(tr("Play playlist"))
        self.b_play.clicked.connect(lambda: self.pid and self.playRequested.emit(self.pid, 0, False))
        self.b_shuffle = QPushButton(tr("Shuffle"))
        self.b_shuffle.setIcon(icon("shuffle"))
        self.b_shuffle.clicked.connect(lambda: self.pid and self.playRequested.emit(self.pid, 0, True))
        self.b_rename = QPushButton(tr("Rename …"))
        self.b_rename.clicked.connect(lambda: self.pid and self.renameRequested.emit(self.pid))
        self.b_delete = QPushButton(tr("Delete"))
        self.b_delete.clicked.connect(lambda: self.pid and self.deleteRequested.emit(self.pid))
        for w in (self.b_play, self.b_shuffle, self.b_rename, self.b_delete):
            head.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(head)

        self.tree = _Tree()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["", tr("Title"), tr("Album"), tr("Duration")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(36, 36))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(
            lambda it, _c: self.pid and self.playRequested.emit(self.pid, self.tree.indexOfTopLevelItem(it), False))
        self.tree.reordered.connect(self._save_order)
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)
        self.empty = QLabel(tr("This playlist is empty. Add albums or tracks with right-click → „Add to playlist“."))
        self.empty.setObjectName("Subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)
        sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(self.remove_selected)

    # ------------------------------------------------------------------ content
    def show_playlist(self, pid: int) -> None:
        self.pid = pid
        self.refresh()

    def refresh(self) -> None:
        if self.pid is None:
            return
        name = self.db.playlist_name(self.pid)
        if name is None:
            self.pid = None
            return
        items = self.db.playlist_items(self.pid)
        self.l_name.setText(name)
        self.tree.clear()
        total, unknown = 0, False
        for i, (slot, track) in enumerate(items):
            a = self.db.album(slot)
            album_txt = (f"{a.display_album} – {a.display_artist}" if a and a.display_artist
                         else (a.display_album if a else tr("Disc {0}").format(slot))) + f"  · #{slot}"
            if track:
                t = next((x for x in a.tracks if x.no == track), None) if a else None
                title = f"{track}. {t.title}" if t else tr("Track {0}").format(track)
                length = t.length_s if t else None
            else:
                title = tr("Whole disc")
                length = a.duration_s if a else None
            if length:
                total += length
            else:
                unknown = True
            it = QTreeWidgetItem(["", title, album_txt, fmt_time(length) if length else ""])
            it.setData(0, EntryRole, (slot, track))
            it.setIcon(0, QIcon(self.cover_fn(a, 36)) if a else icon("disc"))
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            it.setForeground(2, QColor(COLORS["text2"]))
            it.setForeground(3, QColor(COLORS["text2"]))
            it.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if a and not a.present:
                it.setToolTip(1, tr("Disc is not in the changer – will be skipped when playing"))
                for c in range(4):
                    it.setForeground(c, QColor(COLORS["text2"]))
            self.tree.addTopLevelItem(it)
        self.l_info.setText(tr("{0} entries").format(len(items))
                             + (tr(" · {0}{1}").format(tr("min. ") if unknown else "", fmt_time(total))
                                if total else ""))
        self.empty.setVisible(not items)
        self.tree.setVisible(bool(items))
        self.b_play.setEnabled(bool(items))
        self.b_shuffle.setEnabled(bool(items))
        self.mark_playing(self.playing_index)

    def mark_playing(self, index: int) -> None:
        self.playing_index = index
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setForeground(1, QColor(self.accent if i == index else COLORS["text"]))

    def entries(self) -> list[tuple[int, int]]:
        return [tuple(self.tree.topLevelItem(i).data(0, EntryRole)) for i in range(self.tree.topLevelItemCount())]

    # ------------------------------------------------------------------ editing
    def _save_order(self) -> None:
        if self.pid is not None:
            self.db.set_playlist_items(self.pid, self.entries())
            self.refresh()
            self.changed.emit()

    def remove_selected(self) -> None:
        rows = sorted((self.tree.indexOfTopLevelItem(it) for it in self.tree.selectedItems()), reverse=True)
        if not rows or self.pid is None:
            return
        items = self.entries()
        for r in rows:
            items.pop(r)
        self.db.set_playlist_items(self.pid, items)
        self.refresh()
        self.changed.emit()

    def _move(self, delta: int) -> None:
        it = self.tree.currentItem()
        if not it or self.pid is None:
            return
        i = self.tree.indexOfTopLevelItem(it)
        j = i + delta
        items = self.entries()
        if not 0 <= j < len(items):
            return
        items[i], items[j] = items[j], items[i]
        self.db.set_playlist_items(self.pid, items)
        self.refresh()
        self.tree.setCurrentItem(self.tree.topLevelItem(j))

    def _menu(self, pos) -> None:
        it = self.tree.itemAt(pos)
        if not it:
            return
        i = self.tree.indexOfTopLevelItem(it)
        m = QMenu(self)
        m.addAction(icon("play"), tr("Play from here"), lambda: self.playRequested.emit(self.pid, i, False))
        m.addSeparator()
        m.addAction(tr("Move up"), lambda: self._move(-1)).setEnabled(i > 0)
        m.addAction(tr("Move down"), lambda: self._move(+1)).setEnabled(i < self.tree.topLevelItemCount() - 1)
        m.addAction(tr("Remove (Del)"), self.remove_selected)
        m.exec(self.tree.viewport().mapToGlobal(pos))
