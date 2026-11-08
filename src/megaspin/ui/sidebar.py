"""Left sidebar: library filters, artists, genres, user files (Desktop_App_Design §8.2)."""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from ..data.db import Album
from ..data.names import artist_key, best_variant
from ..protocol.constants import music_type_name
from .fonts import sized_px
from .theme import COLORS

FilterRole = Qt.ItemDataRole.UserRole + 2


class Sidebar(QTreeWidget):
    filterChanged = Signal(str, object)
    contextRequested = Signal(str, object, object)     # kind, value, global pos

    def __init__(self, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(10)
        self.setRootIsDecorated(False)
        # neutral style: the Windows 11 style paints an extra selection marker left of the item
        from PySide6.QtWidgets import QStyleFactory
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            self._style = fusion                      # keep a reference (Qt does not take ownership)
            self.setStyle(fusion)
        self.setMinimumWidth(190)
        self.set_accent(accent)
        self.itemClicked.connect(self._clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context)
        self._current = ("all", None)

    def set_accent(self, accent: str) -> None:
        self.setStyleSheet(
            f"QTreeWidget {{ background: {COLORS['panel']}; border: none; border-right: 1px solid {COLORS['border']};"
            f" padding: 8px 4px; outline: 0; show-decoration-selected: 0; }}"
            f"QTreeWidget::branch, QTreeWidget::branch:selected, QTreeWidget::branch:hover"
            f" {{ background: transparent; border: none; }}"
            f"QTreeWidget::item {{ padding: 5px 6px; border-radius: 6px; }}"
            f"QTreeWidget::item:hover {{ background: {COLORS['hover']}; }}"
            f"QTreeWidget::item:selected {{ background: {accent}; color: white; }}")
        # the Windows 11 style draws its own selection marker in the palette colour -> use the accent there too
        pal = self.palette()
        for role in ("Highlight", "Accent"):
            if hasattr(QPalette.ColorRole, role):
                pal.setColor(getattr(QPalette.ColorRole, role), QColor(accent))
        self.setPalette(pal)

    def _group(self, title: str) -> QTreeWidgetItem:
        it = QTreeWidgetItem(self, [title.upper()])
        it.setFont(0, sized_px(self.font(), 11, bold=True))
        it.setForeground(0, QColor(COLORS["text2"]))
        it.setFlags(Qt.ItemFlag.ItemIsEnabled)
        it.setExpanded(True)
        return it

    def _entry(self, parent: QTreeWidgetItem, text: str, count: int, kind: str, value=None) -> QTreeWidgetItem:
        it = QTreeWidgetItem(parent, [f"{text}   {count}" if count is not None else text])
        it.setData(0, FilterRole, (kind, value))
        it.setToolTip(0, text)
        if (kind, value) == self._current:
            self.setCurrentItem(it)
        return it

    def populate(self, albums: list[Album], uf_names: dict[int, str],
                 playlists: list[tuple[int, str, int]] = ()) -> None:
        self.clear()
        g = self._group("Bibliothek")
        self._entry(g, "Alle Alben", len(albums), "all")
        inc = sum(1 for a in albums if not a.complete)
        if inc:
            self._entry(g, "Unvollständig", inc, "incomplete")
        groups: dict[str, list[str]] = {}
        for a in albums:
            if a.artist:
                groups.setdefault(artist_key(a.artist), []).append(a.artist)
        if groups:
            g = self._group("Interpreten")
            named = sorted(((best_variant(v), k, len(v)) for k, v in groups.items()), key=lambda x: x[1])
            for name, key, n in named:
                self._entry(g, name, n, "artist", key)
        genres = Counter(a.music_type for a in albums if a.music_type)
        if genres:
            g = self._group("Genres")
            for code in sorted(genres, key=music_type_name):
                self._entry(g, music_type_name(code), genres[code], "genre", code)
        g = self._group("User Files")
        for n in range(1, 9):
            cnt = sum(1 for a in albums if a.user_files & (1 << (n - 1)))
            self._entry(g, uf_names.get(n, f"User File {n}"), cnt, "userfile", n)
        g = self._group("Playlists")
        for pid, name, cnt in playlists:
            self._entry(g, name, cnt, "playlist", pid)
        new = self._entry(g, "+ Neue Playlist", None, "newplaylist")
        new.setForeground(0, QColor(COLORS["text2"]))
        self.expandAll()

    def _clicked(self, it: QTreeWidgetItem) -> None:
        data = it.data(0, FilterRole)
        if data:
            if data[0] != "newplaylist":
                self._current = data
            self.filterChanged.emit(*data)

    def select(self, kind: str, value=None) -> None:
        self._current = (kind, value)
        it = self._find(kind, value)
        if it:
            self.setCurrentItem(it)

    def _find(self, kind: str, value):
        for i in range(self.topLevelItemCount()):
            g = self.topLevelItem(i)
            for j in range(g.childCount()):
                if g.child(j).data(0, FilterRole) == (kind, value):
                    return g.child(j)
        return None

    def _context(self, pos) -> None:
        it = self.itemAt(pos)
        data = it.data(0, FilterRole) if it else None
        if data:
            self.contextRequested.emit(data[0], data[1], self.viewport().mapToGlobal(pos))
