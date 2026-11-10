"""Album bearbeiten (Desktop_App_Design §9.3)."""
from __future__ import annotations
from ...i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...data.db import Album
from ...data.names import nice_case
from ...protocol.commands import to_changer_text
from ...protocol.constants import MUSIC_TYPE_NAMES, music_type_code, music_type_index
from ...protocol.parsers import split_artist_album
from ..theme import COLORS

MAX_CHANGER_TRACKS = 20
SRC = {"user": "eigene", "musicbrainz": "MusicBrainz", "cdtext": "CD-TEXT", "memory": tr("Changer"), "none": "–"}


def _first(*vals):
    for v in vals:
        if v not in (None, ""):
            return v
    return None


def changer_disc_title(artist: str, album: str) -> str:
    """The changer stores 'Artist   Album' (three spaces) in one 25-character title."""
    if artist and album:
        return f"{artist}   {album}"
    return artist or album or ""


class EditAlbumDialog(QDialog):
    COL_NO, COL_TITLE, COL_CHANGER, COL_SRC = range(4)

    def __init__(self, album: Album, sources: dict, uf_names: dict[int, str], can_write: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Edit album – disc #{0}").format(album.slot))
        self.resize(820, 640)
        self.album = album
        d = sources.get("disc", {})
        self._trk = sources.get("tracks", {})
        cd_a, cd_b = (nice_case(x) for x in split_artist_album(d.get("cdtext_album")))
        mem_a, mem_b = (nice_case(x) for x in split_artist_album(d.get("changer_title")))
        self._auto_artist = _first(d.get("mb_artist"), cd_a, mem_a) or ""
        self._auto_album = _first(d.get("mb_album"), cd_b, mem_b) or ""
        self._auto_year = d.get("mb_year")
        self._mb = (d.get("mb_artist"), d.get("mb_album"))
        self._cd = (cd_a, cd_b)
        self._changer_mt = d.get("changer_mt") or 0
        self._changer_uf = d.get("changer_uf") or 0

        root = QVBoxLayout(self)
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        self.e_artist = QLineEdit(album.artist or "")
        self.e_album = QLineEdit(album.album or "")
        self.e_year = QLineEdit(str(album.year) if album.year else "")
        self.e_year.setValidator(QIntValidator(0, 2999))
        self.e_year.setFixedWidth(70)
        self.c_genre = QComboBox()
        self.c_genre.addItems(MUSIC_TYPE_NAMES)
        self.c_genre.setCurrentIndex(music_type_index(album.music_type))
        form.addWidget(QLabel(tr("Artist")), 0, 0)
        form.addWidget(self.e_artist, 0, 1)
        form.addWidget(QLabel(tr("Year")), 0, 2)
        form.addWidget(self.e_year, 0, 3)
        form.addWidget(QLabel(tr("Album")), 1, 0)
        form.addWidget(self.e_album, 1, 1, 1, 3)
        form.addWidget(QLabel(tr("Genre")), 2, 0)
        form.addWidget(self.c_genre, 2, 1)
        form.addWidget(QLabel(tr("User files")), 3, 0, Qt.AlignmentFlag.AlignTop)
        ufw = QGridLayout()
        self.uf_boxes: list[QCheckBox] = []
        for n in range(1, 9):
            cb = QCheckBox(uf_names.get(n, f"User File {n}"))
            cb.setChecked(bool(album.user_files & (1 << (n - 1))))
            self.uf_boxes.append(cb)
            ufw.addWidget(cb, (n - 1) // 4, (n - 1) % 4)
        form.addLayout(ufw, 3, 1, 1, 3)
        form.setColumnStretch(1, 1)
        root.addLayout(form)

        self.l_disc_changer = QLabel()
        self.l_disc_changer.setObjectName("Subtitle")
        root.addWidget(self.l_disc_changer)

        n = max(album.track_count or 0, len(album.tracks), max(self._trk, default=0))
        self.table = QTableWidget(n, 4)
        self.table.setHorizontalHeaderLabels([tr("No."), tr("Title"), tr("In changer (25 chars)"), tr("Source")])
        self.table.verticalHeader().hide()
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(self.COL_NO, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(self.COL_CHANGER, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(self.COL_SRC, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(self.COL_CHANGER, 230)
        titles = {t.no: t for t in album.tracks}
        self._loading = True
        for row in range(n):
            no = row + 1
            t = titles.get(no)
            self._set(row, self.COL_NO, str(no), editable=False, align_right=True)
            self._set(row, self.COL_TITLE, t.title if t and t.source != "none" else "")
            self._set(row, self.COL_CHANGER, "", editable=False, muted=True)
            self._set(row, self.COL_SRC, SRC.get(t.source, "") if t else "–", editable=False, muted=True)
        self._loading = False
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.b_mb = QPushButton(tr("Take from MusicBrainz"))
        self.b_mb.clicked.connect(lambda: self._take("mb"))
        self.b_mb.setEnabled(bool(self._mb[1] or any(r.get("mb_title") for r in self._trk.values())))
        self.b_cd = QPushButton(tr("Take from CD-TEXT"))
        self.b_cd.clicked.connect(lambda: self._take("cdtext"))
        self.b_cd.setEnabled(bool(self._cd[1] or any(r.get("cdtext_title") for r in self._trk.values())))
        self.b_reset = QPushButton(tr("Reset"))
        self.b_reset.setToolTip(tr("Discard own entries (MusicBrainz / CD-TEXT / changer titles apply again)"))
        self.b_reset.clicked.connect(self._reset)
        for b in (self.b_mb, self.b_cd, self.b_reset):
            btns.addWidget(b)
        btns.addStretch()
        root.addLayout(btns)

        self.cb_write = QCheckBox(tr("Also write to the changer"))
        self.cb_write.setEnabled(can_write)
        if not can_write:
            self.cb_write.setToolTip(tr("Only possible if the changer is connected and the disc is loaded"))
        root.addWidget(self.cb_write)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {COLORS['warn']};")
        root.addWidget(self.warn)
        self.cb_write.toggled.connect(self._update_warn)
        self._update_warn()

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText(tr("Save"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self.e_artist.textChanged.connect(self._update_preview)
        self.e_album.textChanged.connect(self._update_preview)
        self._update_preview()

    # ------------------------------------------------------------------ helpers
    def _set(self, row: int, col: int, text: str, editable: bool = True, muted: bool = False,
             align_right: bool = False) -> None:
        it = QTableWidgetItem(text)
        if not editable:
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if muted:
            it.setForeground(QColor(COLORS["text2"]))
        if align_right:
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(row, col, it)

    def _title(self, row: int) -> str:
        it = self.table.item(row, self.COL_TITLE)
        return it.text().strip() if it else ""

    def _auto_title(self, no: int) -> str:
        r = self._trk.get(no, {})
        return _first(r.get("mb_title"), nice_case(r.get("cdtext_title")), nice_case(r.get("changer_title"))) or ""

    def _on_item_changed(self, it: QTableWidgetItem) -> None:
        if self._loading or it.column() != self.COL_TITLE:
            return
        no = it.row() + 1
        self._loading = True
        auto = self._auto_title(no)
        src_it = self.table.item(it.row(), self.COL_SRC)
        text = it.text().strip()
        if not text:
            src_it.setText(SRC["none"])
        elif text != auto:
            src_it.setText(SRC["user"])
        self._loading = False
        self._update_preview()

    def _update_preview(self) -> None:
        self._loading = True
        disc = to_changer_text(changer_disc_title(self.e_artist.text().strip(), self.e_album.text().strip()))
        self.l_disc_changer.setText(tr("Disc title in changer: „{0}“").format(disc.decode()))
        for row in range(self.table.rowCount()):
            it = self.table.item(row, self.COL_CHANGER)
            if row >= MAX_CHANGER_TRACKS:
                it.setText(tr("(not possible – max. 20)"))
            else:
                it.setText(to_changer_text(self._title(row)).decode())
        self._loading = False

    def _update_warn(self) -> None:
        msgs = []
        if self.cb_write.isChecked():
            if self.album.has_cdtext:
                msgs.append(tr("⚠ This disc has CD-TEXT: the changer replaces your own titles with the CD-TEXT when it is loaded next time. Genre and user files are kept."))
            if self.table.rowCount() > MAX_CHANGER_TRACKS:
                msgs.append(tr("The changer only stores the titles of the first {0} tracks.").format(MAX_CHANGER_TRACKS))
            msgs.append(tr("Titles are cut to 25 characters, umlauts are transliterated (preview in the column „In changer“)."))
        self.warn.setText("\n".join(msgs))
        self.warn.setVisible(bool(msgs))

    def _take(self, which: str) -> None:
        if which == "mb":
            a, b = self._mb
            col, src = "mb_title", "MusicBrainz"
        else:
            a, b = self._cd
            col, src = "cdtext_title", "CD-TEXT"
        if a:
            self.e_artist.setText(a)
        if b:
            self.e_album.setText(b)
        if which == "mb" and self._auto_year:
            self.e_year.setText(str(self._auto_year))
        self._loading = True
        for row in range(self.table.rowCount()):
            t = self._trk.get(row + 1, {}).get(col)
            t = t if which == "mb" else nice_case(t)
            if t:
                self.table.item(row, self.COL_TITLE).setText(t)
                self.table.item(row, self.COL_SRC).setText(src)
        self._loading = False
        self._update_preview()

    def _reset(self) -> None:
        self.e_artist.setText(self._auto_artist)
        self.e_album.setText(self._auto_album)
        self.e_year.setText(str(self._auto_year) if self._auto_year else "")
        self.c_genre.setCurrentIndex(music_type_index(self._changer_mt))
        for n, cb in enumerate(self.uf_boxes, 1):
            cb.setChecked(bool(self._changer_uf & (1 << (n - 1))))
        self._loading = True
        for row in range(self.table.rowCount()):
            no = row + 1
            r = self._trk.get(no, {})
            self.table.item(row, self.COL_TITLE).setText(self._auto_title(no))
            src = "musicbrainz" if r.get("mb_title") else "cdtext" if r.get("cdtext_title") else \
                "memory" if r.get("changer_title") else "none"
            self.table.item(row, self.COL_SRC).setText(SRC[src])
        self._loading = False
        self._update_preview()

    # ------------------------------------------------------------------ result
    @property
    def music_type(self) -> int:
        return music_type_code(self.c_genre.currentIndex())

    @property
    def user_files(self) -> int:
        return sum(1 << i for i, cb in enumerate(self.uf_boxes) if cb.isChecked())

    @property
    def write_to_changer(self) -> bool:
        return self.cb_write.isEnabled() and self.cb_write.isChecked()

    def titles(self) -> dict[int, str]:
        return {row + 1: self._title(row) for row in range(self.table.rowCount())}

    def user_values(self) -> dict:
        """Only what differs from the automatic sources is stored as 'user' (so later
        MusicBrainz/CD-TEXT improvements still apply to untouched fields)."""
        artist, album = self.e_artist.text().strip(), self.e_album.text().strip()
        year = int(self.e_year.text()) if self.e_year.text().strip() else None
        tracks = {}
        for no, t in self.titles().items():
            tracks[no] = t if t and t != self._auto_title(no) else None
        return {
            "artist": artist if artist != self._auto_artist else None,
            "album": album if album != self._auto_album else None,
            "year": year if year != self._auto_year else None,
            "music_type": self.music_type if self.music_type != self._changer_mt else None,
            "user_files": self.user_files if self.user_files != self._changer_uf else None,
            "tracks": tracks,
        }

    def changer_payload(self) -> dict:
        """Arguments for ChangerService.write_titles."""
        t = self.titles()
        return {
            "title": changer_disc_title(self.e_artist.text().strip(), self.e_album.text().strip()),
            "tracks": {no: s for no, s in t.items() if no <= MAX_CHANGER_TRACKS},
            "music_type": self.music_type,
            "user_files": self.user_files,
        }
