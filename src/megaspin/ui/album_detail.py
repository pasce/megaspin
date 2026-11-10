"""Album detail panel (Desktop_App_Design §8.4), shown below the grid."""
from __future__ import annotations
from ..i18n import tr

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..data.db import Album
from ..protocol.constants import music_type_name
from .flow_layout import FlowLayout
from .icons import icon
from .player_bar import fmt_time
from .theme import COLORS

SOURCE_TEXT = {"cdtext": "CD-TEXT", "memory": tr("Changer memory (25 characters)"), "user": tr("own entries"),
               "musicbrainz": "MusicBrainz", "none": tr("no titles")}


class AlbumDetail(QFrame):
    playRequested = Signal(int, int)        # slot, track
    readFullRequested = Signal(int)
    rereadRequested = Signal(int)
    closeRequested = Signal()
    metadataRequested = Signal(int)
    chooseMatchRequested = Signal(int)
    coverRequested = Signal(int)
    editRequested = Signal(int)
    trackMenuRequested = Signal(int, int, object)   # slot, track, global pos

    def __init__(self, accent: str, cover_fn, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.accent = accent
        self.cover_fn = cover_fn
        self.album: Album | None = None
        self.playing: tuple[int, int] = (0, 0)

        lay = QGridLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setHorizontalSpacing(20)
        self.cover = QLabel()
        self.cover.setFixedSize(200, 200)
        lay.addWidget(self.cover, 0, 0, 3, 1, Qt.AlignmentFlag.AlignTop)

        head = QHBoxLayout()
        txt = QVBoxLayout()
        txt.setSpacing(2)
        self.l_album = QLabel()
        self.l_album.setObjectName("Big")
        self.l_album.setWordWrap(True)
        self.l_artist = QLabel()
        self.l_artist.setObjectName("Title")
        self.l_info = QLabel()
        self.l_info.setObjectName("Subtitle")
        self.l_info.setWordWrap(True)
        for w in (self.l_album, self.l_artist, self.l_info):
            txt.addWidget(w)
        head.addLayout(txt, 1)
        self.b_play = QToolButton()
        self.b_play.setObjectName("PlayButton")
        self.b_play.setIcon(icon("play", "#FFFFFF", 22))
        self.b_play.setToolTip(tr("Play album"))
        self.b_play.clicked.connect(lambda: self.album and self.playRequested.emit(self.album.slot, 1))
        b_close = QToolButton()
        b_close.setText("✕")
        b_close.setToolTip(tr("Close (Esc)"))
        b_close.clicked.connect(self.closeRequested.emit)
        head.addWidget(self.b_play, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(b_close, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head, 0, 1)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {COLORS['warn']};")
        lay.addWidget(self.hint, 1, 1)

        self.tracks = QTreeWidget()
        self.tracks.setColumnCount(3)
        self.tracks.setHeaderHidden(True)
        self.tracks.setRootIsDecorated(False)
        self.tracks.setIndentation(0)
        self.tracks.setUniformRowHeights(True)
        self.tracks.setStyleSheet(f"QTreeWidget {{ background: transparent; border: none; outline: 0; }}"
                                  f"QTreeWidget::item {{ padding: 3px 2px; }}"
                                  f"QTreeWidget::item:hover {{ background: {COLORS['hover']}; }}")
        h = self.tracks.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tracks.itemDoubleClicked.connect(
            lambda it, _c: self.album and self.playRequested.emit(self.album.slot, it.data(0, Qt.ItemDataRole.UserRole)))
        self.tracks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tracks.customContextMenuRequested.connect(self._track_menu)
        lay.addWidget(self.tracks, 2, 1)

        btn_box = QWidget()
        btns = FlowLayout(btn_box, spacing=10)      # wraps to a second row when the panel is narrow
        self.btn_layout = btns
        self.b_full = QPushButton(tr("Full read"))
        self.b_full.setToolTip(tr("Load the disc (without playback) and read table of contents and CD-TEXT"))
        self.b_full.clicked.connect(lambda: self.album and self.readFullRequested.emit(self.album.slot))
        self.b_reread = QPushButton(tr("Re-read titles"))
        self.b_reread.setToolTip(tr("Re-read memory titles, genre and user files (no disc loading)"))
        self.b_reread.clicked.connect(lambda: self.album and self.rereadRequested.emit(self.album.slot))
        self.b_meta = QPushButton(tr("Look up metadata"))
        self.b_meta.setToolTip(tr("Look up titles and cover at MusicBrainz"))
        self.b_meta.clicked.connect(lambda: self.album and self.metadataRequested.emit(self.album.slot))
        self.b_match = QPushButton(tr("Choose match …"))
        self.b_match.clicked.connect(lambda: self.album and self.chooseMatchRequested.emit(self.album.slot))
        self.b_cover = QPushButton(tr("Change cover …"))
        self.b_cover.clicked.connect(lambda: self.album and self.coverRequested.emit(self.album.slot))
        self.b_edit = QPushButton(tr("Edit …"))
        self.b_edit.setIcon(icon("edit"))
        self.b_edit.setToolTip(tr("Edit artist, album, titles, genre and user files (F2)"))
        self.b_edit.clicked.connect(lambda: self.album and self.editRequested.emit(self.album.slot))
        btns.addWidget(self.b_edit)
        btns.addWidget(self.b_full)
        btns.addWidget(self.b_reread)
        btns.addWidget(self.b_meta)
        btns.addWidget(self.b_match)
        btns.addWidget(self.b_cover)
        lay.addWidget(btn_box, 3, 1)
        lay.setRowStretch(2, 1)
        lay.setColumnStretch(1, 1)

    def show_album(self, album: Album | None, uf_names: dict[int, str]) -> None:
        self.album = album
        if not album:
            return
        self.cover.setPixmap(self.cover_fn(album, 200))
        self.l_album.setText(album.display_album)
        self.l_artist.setText(album.display_artist or tr("Unknown artist"))
        parts = [tr("Disc #{0}").format(album.slot)]
        if album.year:
            parts.append(str(album.year))
        if album.music_type:
            parts.append(music_type_name(album.music_type))
        if album.track_count:
            parts.append(tr("{0} tracks").format(album.track_count))
        if album.duration_s:
            parts.append(fmt_time(album.duration_s))
        ufs = [uf_names.get(n, f"User File {n}") for n in range(1, 9) if album.user_files & (1 << (n - 1))]
        if ufs:
            parts.append(tr("User files: ") + ", ".join(ufs))
        parts.append(tr("Titles: ") + SOURCE_TEXT.get(album.title_source, ""))
        self.l_info.setText(" · ".join(parts))
        if album.mb_status == "ambiguous":
            self.hint.setText(tr("MusicBrainz found several possible albums – please use „Choose match …“."))
        elif not album.present:
            self.hint.setText(tr("This disc is currently not in the changer."))
        elif not album.has_toc:
            self.hint.setText(tr("For track lengths and full titles, please use „Full read“ (the disc will be loaded briefly)."))
        else:
            self.hint.setText("")
        self.hint.setVisible(bool(self.hint.text()))
        self.b_full.setEnabled(album.present)
        self.b_reread.setEnabled(album.present)
        self.b_meta.setEnabled(album.has_toc)
        self.b_meta.setToolTip(tr("Look up titles and cover at MusicBrainz") if album.has_toc
                               else tr("First use „Full read“ (table of contents needed)"))
        self.b_match.setVisible(album.has_toc and album.mb_status not in (None, "ok", "none"))
        self.btn_layout.invalidate()                 # re-place the buttons when one is shown/hidden
        self.btn_layout.activate()
        self.tracks.clear()
        for t in album.tracks:
            it = QTreeWidgetItem([str(t.no), t.title, fmt_time(t.length_s) if t.length_s else ""])
            it.setData(0, Qt.ItemDataRole.UserRole, t.no)
            it.setToolTip(1, tr("{0}\nSource: {1}").format(t.title, SOURCE_TEXT.get(t.source, t.source)))
            it.setTextAlignment(0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setForeground(0, QColor(COLORS["text2"]))
            it.setForeground(2, QColor(COLORS["text2"]))
            self.tracks.addTopLevelItem(it)
        self.mark_playing(*self.playing)

    def _track_menu(self, pos) -> None:
        it = self.tracks.itemAt(pos)
        if it and self.album:
            self.trackMenuRequested.emit(self.album.slot, it.data(0, Qt.ItemDataRole.UserRole),
                                         self.tracks.viewport().mapToGlobal(pos))

    def mark_playing(self, disc: int, track: int) -> None:
        self.playing = (disc, track)
        if not self.album:
            return
        for i in range(self.tracks.topLevelItemCount()):
            it = self.tracks.topLevelItem(i)
            on = disc == self.album.slot and it.data(0, Qt.ItemDataRole.UserRole) == track
            it.setForeground(1, QColor(self.accent if on else COLORS["text"]))
            it.setText(0, "▶" if on else str(it.data(0, Qt.ItemDataRole.UserRole)))
