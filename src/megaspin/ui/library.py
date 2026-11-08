"""Album grid: model, delegate, view and A–Z bar (Desktop_App_Design §8.3)."""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QListView, QStyle, QStyledItemDelegate,
                               QToolButton, QWidget)

from ..data.db import Album
from ..data.names import artist_key, best_variant
from ..protocol.constants import music_type_name
from .fonts import scaled, sized_px
from .icons import icon
from .theme import COLORS

AlbumRole = Qt.ItemDataRole.UserRole + 1
GroupRole = Qt.ItemDataRole.UserRole + 3

SORTS = {
    "artist": ("Interpret", lambda a: (artist_key(a.artist) or "~", _norm(a.album or ""), a.slot)),
    "album": ("Album", lambda a: (_norm(a.album or "~"), a.slot)),
    "year": ("Jahr", lambda a: (a.year is None, a.year or 0, artist_key(a.artist) or "~", a.slot)),
    "slot": ("Slot-Nummer", lambda a: a.slot),
    "played": ("Zuletzt gespielt", lambda a: -(a.last_played_at or 0)),
}


GROUPINGS = {"none": "Nicht gruppieren", "artist": "Nach Interpret", "year": "Nach Jahr"}
UNKNOWN_YEAR = "Unbekannt"


@dataclass
class Group:
    kind: str                       # "artist" | "year"
    key: object                     # artist_key / year / UNKNOWN_YEAR
    title: str
    albums: list[Album] = field(default_factory=list)

    @property
    def subtitle(self) -> str:
        n = len(self.albums)
        s = f"{n} Album" if n == 1 else f"{n} Alben"
        if self.kind == "year":
            artists = {artist_key(a.artist) for a in self.albums if a.artist}
            if len(artists) > 1:
                s += f" · {len(artists)} Interpreten"
            elif artists:
                s += " · " + best_variant([a.artist for a in self.albums if a.artist])
        return s


def build_groups(albums: list[Album], kind: str) -> list[Group]:
    groups: dict[object, Group] = {}
    for a in albums:
        if kind == "artist":
            key = artist_key(a.artist) or "~"
        else:
            key = a.year or UNKNOWN_YEAR
        groups.setdefault(key, Group(kind, key, "")).albums.append(a)
    for g in groups.values():
        if kind == "artist":
            names = [a.artist for a in g.albums if a.artist]
            g.title = best_variant(names) if names else "Unbekannter Interpret"
        else:
            g.title = str(g.key)
    if kind == "artist":
        return sorted(groups.values(), key=lambda g: (g.key == "~", g.key))
    return sorted(groups.values(), key=lambda g: (g.key == UNKNOWN_YEAR, -(g.key if isinstance(g.key, int) else 0)))


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return s[4:] if s.startswith("the ") else s


def sort_letter(a: Album, sort: str) -> str:
    if sort == "artist":
        s = _norm(a.artist or "")
    elif sort == "album":
        s = _norm(a.album or "")
    else:
        return "#"
    return s[:1].upper() if s[:1].isalpha() else "#"


class LibraryModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.all: list[Album] = []
        self.items: list[Album] = []
        self.filter: tuple[str, object] = ("all", None)
        self.search = ""
        self.sort = "artist"
        self.group_by = "none"
        self.open_group = None             # key of the group currently shown (drill-down)
        self.groups: list[Group] = []
        self.playing_slot = 0

    # Qt API
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None                     # stale index (model was reset by the same click)
        a = self.items[index.row()]
        if isinstance(a, Group):
            if role == GroupRole:
                return a
            if role == Qt.ItemDataRole.DisplayRole:
                return a.title
            if role == Qt.ItemDataRole.ToolTipRole:
                return f"<b>{a.title}</b><br>{a.subtitle}<br>Klicken zum Öffnen"
            return None
        if role == AlbumRole:
            return a
        if role == Qt.ItemDataRole.DisplayRole:
            return a.display_album
        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [f"<b>{a.display_album}</b>", a.display_artist, f"Disc #{a.slot}"]
            if a.music_type:
                parts.append(music_type_name(a.music_type))
            if a.track_count:
                parts.append(f"{a.track_count} Tracks")
            src = {"cdtext": "CD-TEXT", "memory": "Wechsler-Speicher", "user": "eigene Angaben",
                   "musicbrainz": "MusicBrainz", "none": "keine Titel"}[a.title_source]
            parts.append(f"Quelle: {src}")
            return "<br>".join(p for p in parts if p)
        return None

    # filtering
    def set_albums(self, albums: list[Album]) -> None:
        self.all = albums
        self._apply()

    def set_filter(self, kind: str, value=None) -> None:
        self.filter = (kind, value)
        self._apply()

    def set_search(self, text: str) -> None:
        self.search = text.strip()
        self._apply()

    def set_sort(self, key: str) -> None:
        self.sort = key
        self._apply()

    def set_group_by(self, kind: str) -> None:
        self.group_by = kind
        self.open_group = None
        self._apply()

    def enter_group(self, key) -> None:
        self.open_group = key
        self._apply()

    def leave_group(self) -> None:
        self.open_group = None
        self._apply()

    @property
    def showing_groups(self) -> bool:
        return self.group_by != "none" and self.open_group is None

    def current_group(self) -> Group | None:
        return next((g for g in self.groups if g.key == self.open_group), None)

    def visible_albums(self) -> list[Album]:
        """Albums currently represented in the view (all albums of all groups when groups are shown)."""
        if self.showing_groups:
            return [a for g in self.groups for a in g.albums]
        return [a for a in self.items if isinstance(a, Album)]

    def set_playing(self, slot: int) -> None:
        if slot == self.playing_slot:
            return
        self.playing_slot = slot
        if self.items:
            self.dataChanged.emit(self.index(0), self.index(len(self.items) - 1))

    def _match(self, a: Album) -> bool:
        kind, val = self.filter
        if kind == "incomplete" and a.complete:
            return False
        if kind == "artist" and artist_key(a.artist) != val:
            return False
        if kind == "genre" and a.music_type != val:
            return False
        if kind == "userfile" and not (a.user_files & (1 << (val - 1))):
            return False
        if self.search:
            q = _norm(self.search)
            if q.startswith("#") and q[1:].isdigit():
                return a.slot == int(q[1:])
            hay = _norm(" ".join(x for x in (a.artist, a.album, str(a.slot)) if x))
            if q not in hay:
                return False
        return True

    def _apply(self) -> None:
        self.beginResetModel()
        albums = [a for a in self.all if self._match(a)]
        albums.sort(key=SORTS[self.sort][1])
        if self.group_by == "none":
            self.groups = []
            self.items = albums
        else:
            self.groups = build_groups(albums, self.group_by)
            g = self.current_group()
            if self.open_group is not None and g is None:
                self.open_group = None              # group vanished (filter/search)
            self.items = list(g.albums) if g else list(self.groups)
        self.endResetModel()

    def row_of_slot(self, slot: int) -> int:
        for i, a in enumerate(self.items):
            if isinstance(a, Group):
                if any(x.slot == slot for x in a.albums):
                    return i
            elif a.slot == slot:
                return i
        return -1

    def _letter(self, item) -> str:
        if isinstance(item, Group):
            if item.kind != "artist":
                return "#"
            s = str(item.key)
            return s[:1].upper() if s[:1].isalpha() else "#"
        return sort_letter(item, self.sort)

    def first_row_for_letter(self, letter: str) -> int:
        for i, a in enumerate(self.items):
            lt = self._letter(a)
            if lt >= letter or (letter == "#" and lt == "#"):
                return i
        return -1


def placeholder_colors(a: Album) -> tuple[QColor, QColor]:
    h = int(hashlib.md5((a.artist or a.album or str(a.slot)).encode()).hexdigest()[:6], 16)
    hue = h % 360
    c1 = QColor.fromHsl(hue, 70, 70)
    c2 = QColor.fromHsl((hue + 40) % 360, 90, 35)
    return c1, c2


class AlbumDelegate(QStyledItemDelegate):
    def __init__(self, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.accent = QColor(accent)
        self.cover = 160
        self._pix_cache: dict[tuple[str, int], QPixmap] = {}

    def set_cover_size(self, size: int) -> None:
        self.cover = size
        self._pix_cache.clear()

    def sizeHint(self, option, index) -> QSize:
        return QSize(self.cover + 20, self.cover + 66)

    def _pixmap(self, path: str) -> QPixmap | None:
        key = (path, self.cover)
        if key not in self._pix_cache:
            pm = QPixmap(path)
            if pm.isNull():
                return None
            self._pix_cache[key] = pm.scaled(self.cover * 2, self.cover * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                             Qt.TransformationMode.SmoothTransformation)
        return self._pix_cache[key]

    def _draw_cover(self, p: QPainter, rect: QRect, a: Album, radius: int = 6, small: bool = False) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        pm = self._pixmap(a.cover_path) if a.cover_path else None
        if pm:
            p.save()
            p.setClipPath(path)
            # crop the source to the aspect ratio of the target rect
            tr = rect.width() / max(1, rect.height())
            sw, sh = pm.width(), pm.height()
            if sw / sh > tr:
                w = int(sh * tr)
                src = QRect((sw - w) // 2, 0, w, sh)
            else:
                h = int(sw / tr)
                src = QRect(0, (sh - h) // 2, sw, h)
            p.drawPixmap(rect, pm, src)
            p.restore()
            return
        c1, c2 = placeholder_colors(a)
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.fillPath(path, QBrush(g))
        ic = max(16, min(rect.width(), rect.height()) // 3)
        if small:
            p.drawPixmap(rect.center().x() - ic // 2, rect.center().y() - ic // 2,
                         icon("disc", "#FFFFFF", ic).pixmap(ic, ic))
            return
        p.drawPixmap(rect.center().x() - ic // 2, rect.center().y() - ic // 2 - 10,
                     icon("disc", "#FFFFFF", ic).pixmap(ic, ic))
        p.setFont(sized_px(p.font(), max(14, self.cover // 8), bold=True))
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(QRect(rect.x(), rect.center().y() + ic // 2 - 4, rect.width(), 30),
                   Qt.AlignmentFlag.AlignCenter, f"#{a.slot}")

    def _paint_group(self, p: QPainter, option, g: Group, model) -> None:
        r = option.rect
        cov = QRect(r.x() + 10, r.y() + 10, self.cover, self.cover)
        covers = sorted(g.albums, key=lambda a: (a.cover_path is None, a.slot))[:4]
        n = len(covers)
        gap = 2
        half = (self.cover - gap) // 2
        cells: list[QRect]
        if n == 1:
            cells = [cov]
        elif n == 2:
            cells = [QRect(cov.x(), cov.y(), half, self.cover),
                     QRect(cov.x() + half + gap, cov.y(), self.cover - half - gap, self.cover)]
        elif n == 3:
            cells = [QRect(cov.x(), cov.y(), half, self.cover),
                     QRect(cov.x() + half + gap, cov.y(), self.cover - half - gap, half),
                     QRect(cov.x() + half + gap, cov.y() + half + gap, self.cover - half - gap, self.cover - half - gap)]
        else:
            o = half + gap
            rest = self.cover - o
            cells = [QRect(cov.x(), cov.y(), half, half), QRect(cov.x() + o, cov.y(), rest, half),
                     QRect(cov.x(), cov.y() + o, half, rest), QRect(cov.x() + o, cov.y() + o, rest, rest)]
        clip = QPainterPath()
        clip.addRoundedRect(cov, 6, 6)
        p.save()
        p.setClipPath(clip)
        for cell, a in zip(cells, covers):
            self._draw_cover(p, cell, a, radius=0, small=n > 1)
        p.restore()
        # album count badge (bottom right)
        cnt = str(len(g.albums))
        f = sized_px(option.font, 13, bold=True)
        p.setFont(f)
        w = max(26, p.fontMetrics().horizontalAdvance(cnt) + 16)
        badge = QRect(cov.right() - w - 6, cov.bottom() - 30, w, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(badge, 12, 12)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, cnt)
        if any(a.slot == model.playing_slot for a in g.albums):
            p.setPen(QPen(self.accent, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(cov.adjusted(1, 1, -1, -1), 6, 6)
        tx = QRect(cov.x(), cov.bottom() + 6, self.cover, 18)
        ft = QFont(option.font)
        ft.setBold(True)
        p.setFont(ft)
        p.setPen(QColor(COLORS["text"]))
        p.drawText(tx, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(g.title, Qt.TextElideMode.ElideRight, tx.width()))
        p.setFont(scaled(ft, 0.92, bold=False))
        p.setPen(QColor(COLORS["text2"]))
        tx2 = tx.translated(0, 18)
        p.drawText(tx2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(g.subtitle, Qt.TextElideMode.ElideRight, tx2.width()))

    def paint(self, p: QPainter, option, index) -> None:
        model: LibraryModel = index.model()
        g = index.data(GroupRole)
        a: Album = index.data(AlbumRole)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        hovered = option.state & QStyle.StateFlag.State_MouseOver
        selected = option.state & QStyle.StateFlag.State_Selected
        if selected or hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(COLORS["hover"] if hovered and not selected else "#2F2F2F"))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 8, 8)

        if g is not None:
            self._paint_group(p, option, g, model)
            p.restore()
            return
        cov = QRect(r.x() + 10, r.y() + 10, self.cover, self.cover)
        self._draw_cover(p, cov, a)

        if a.mb_status == "ambiguous":      # needs a decision
            b = QRect(cov.right() - 30, cov.top() + 6, 24, 24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(COLORS["warn"]))
            p.drawEllipse(b)
            p.setPen(QColor("#000000"))
            p.setFont(sized_px(option.font, 15, bold=True))
            p.drawText(b, Qt.AlignmentFlag.AlignCenter, "?")
        elif not a.complete:      # small dot: incomplete data (no TOC)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(COLORS["warn"]))
            p.drawEllipse(cov.right() - 14, cov.top() + 6, 8, 8)
        if a.slot == model.playing_slot:
            p.setPen(QPen(self.accent, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(cov.adjusted(1, 1, -1, -1), 6, 6)
            b = QRect(cov.left() + 8, cov.bottom() - 36, 28, 28)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.accent)
            p.drawEllipse(b)
            p.drawPixmap(b.adjusted(6, 6, -6, -6), icon("play", "#FFFFFF", 16).pixmap(16, 16))

        tx = QRect(cov.x(), cov.bottom() + 6, self.cover, 18)
        f = QFont(option.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(COLORS["text"]))
        p.drawText(tx, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(a.display_album, Qt.TextElideMode.ElideRight, tx.width()))
        p.setFont(scaled(f, 0.92, bold=False))
        p.setPen(QColor(COLORS["text2"]))
        tx2 = tx.translated(0, 18)
        p.drawText(tx2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(a.display_artist, Qt.TextElideMode.ElideRight, tx2.width()))
        tx3 = tx2.translated(0, 17)
        extra = f"#{a.slot}" + (f" · {a.track_count} Tracks" if a.track_count else "")
        p.drawText(tx3, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, extra)
        p.restore()


class AlbumGrid(QListView):
    playRequested = Signal(int)                 # slot
    contextRequested = Signal(int, object)      # slot, global pos
    groupOpened = Signal(object)                # group key
    groupContextRequested = Signal(object, object)   # Group, global pos

    def __init__(self, model: LibraryModel, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.delegate = AlbumDelegate(accent, self)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setStyleSheet(f"QListView {{ background: {COLORS['bg']}; border: none; }}")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doubleClicked.connect(self._double)
        self.clicked.connect(self._clicked)
        self.customContextMenuRequested.connect(self._ctx)

    def _clicked(self, idx) -> None:
        g = idx.data(GroupRole)
        if g is not None:
            self.groupOpened.emit(g.key)

    def _double(self, idx) -> None:
        a = idx.data(AlbumRole)
        if a is not None:
            self.playRequested.emit(a.slot)

    def _ctx(self, pos) -> None:
        idx = self.indexAt(pos)
        if not idx.isValid():
            return
        self.setCurrentIndex(idx)
        g = idx.data(GroupRole)
        if g is not None:
            self.groupContextRequested.emit(g, self.viewport().mapToGlobal(pos))
        else:
            self.contextRequested.emit(idx.data(AlbumRole).slot, self.viewport().mapToGlobal(pos))

    def keyPressEvent(self, ev) -> None:
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            g = self.currentIndex().data(GroupRole)
            if g is not None:
                self.groupOpened.emit(g.key)
            else:
                self.playRequested.emit(self.currentIndex().data(AlbumRole).slot)
            return
        super().keyPressEvent(ev)

    def wheelEvent(self, ev) -> None:
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            size = self.delegate.cover + (12 if ev.angleDelta().y() > 0 else -12)
            self.delegate.set_cover_size(max(120, min(240, size)))
            self.doItemsLayout()
            return
        super().wheelEvent(ev)

    def scroll_to_slot(self, slot: int) -> None:
        row = self.model().row_of_slot(slot)
        if row >= 0:
            idx = self.model().index(row)
            self.setCurrentIndex(idx)
            self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    def current_slot(self) -> int | None:
        idx = self.currentIndex()
        a = idx.data(AlbumRole) if idx.isValid() else None
        return a.slot if a is not None else None


class AlphabetBar(QWidget):
    letterClicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for ch in "#ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            b = QToolButton()
            b.setText(ch)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QToolButton {{ color: {COLORS['text2']}; padding: 2px 5px; border-radius: 4px; }}"
                            f"QToolButton:hover {{ color: {COLORS['text']}; background: {COLORS['hover']}; }}")
            b.clicked.connect(lambda _=False, c=ch: self.letterClicked.emit(c))
            lay.addWidget(b)
        lay.addStretch()
