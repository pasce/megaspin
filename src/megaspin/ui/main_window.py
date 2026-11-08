"""Main window (Desktop_App_Design §7): sidebar | album grid | now playing, player bar, status bar."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIntValidator, QKeySequence, QLinearGradient, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QTreeWidget, QTreeWidgetItem, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QSplitter, QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget, QApplication, QInputDialog)

from ..app.metadata import MetadataService
from ..app.scan import ScanManager
from ..app.slot_watch import SlotWatcher
from ..app.playlist_player import PlaylistPlayer
from ..app.settings import Settings, data_dir
from ..backend.serial_backend import SIM_TARGET, SerialBackend
from ..data.db import Album, Database
from ..protocol.constants import music_type_name
from .album_detail import AlbumDetail
from ..data.importer import import_folder
from .dialogs.connect import ConnectDialog
from .dialogs.edit_album import EditAlbumDialog
from .dialogs.console import ProtocolConsole
from .dialogs.settings import SettingsDialog
from .dialogs.user_files import UserFilesDialog
from .dialogs.match_select import MatchSelectDialog
from .dialogs.scan import ScanDialog
from .icons import icon
from .library import GROUPINGS, SORTS, AlbumRole, AlbumGrid, AlphabetBar, LibraryModel, placeholder_colors
from .player_bar import PLAY_STATE_TEXT, PlayerBar, fmt_time
from .sidebar import Sidebar
from .playlist_view import PlaylistView
from .theme import COLORS

MODE_TEXT = {"track": "Track Mode", "program": "Program Mode", "best_sel": "Best Selection",
             "music_type": "Music Type Mode", "user_file": "User File Mode"}
OLD_DATA_DIR = Path(r"C:\Program Files (x86)\CD Changer Controller\data")
ACTIVE_STATES = ("playing", "paused", "ff", "rew", "searching")


def cover_pixmap(album: Album | None, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    if album and album.cover_path:
        src = QPixmap(album.cover_path)
        if not src.isNull():
            return src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if album:
        c1, c2 = placeholder_colors(album)
    else:
        c1, c2 = QColor("#333"), QColor("#1C1C1C")
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, c1)
    g.setColorAt(1, c2)
    p.setBrush(QBrush(g))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, 10, 10)
    ic = size // 3
    p.drawPixmap((size - ic) // 2, (size - ic) // 2, icon("disc", "#FFFFFF", ic).pixmap(ic, ic))
    p.end()
    return pm


class NumberField(QLineEdit):
    """Small integer input (QSpinBox renders badly with the custom stylesheet)."""

    def __init__(self, placeholder: str, lo: int, hi: int) -> None:
        super().__init__()
        self.lo, self.hi = lo, hi
        self.setPlaceholderText(placeholder)
        self.setValidator(QIntValidator(lo, hi, self))
        self.setFixedWidth(64)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip(f"{placeholder} ({lo}–{hi})")

    def value(self) -> int:
        try:
            return max(self.lo, min(self.hi, int(self.text())))
        except ValueError:
            return self.lo

    def setValue(self, v: int) -> None:
        self.setText(str(v))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, db_path=None) -> None:
        super().__init__()
        self.settings = settings
        self.backend = SerialBackend(self)
        self.console = ProtocolConsole(self.backend, self)
        self.db = Database(db_path or (data_dir() / "library.sqlite"))
        self.scan = ScanManager(self.backend, self.db, self)
        covers = (Path(db_path).parent / "covers") if db_path else (data_dir() / "covers")
        self.meta = MetadataService(self.db, covers, settings, self)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(250)
        self._reload_timer.timeout.connect(self.reload_library)
        self.status: dict = self.backend.status()
        self._np_album: Album | None = None
        self._closed = False
        self.setWindowTitle("MegaSpin")
        self.setMinimumSize(1024, 640)
        self.resize(1360, 820)

        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.model = LibraryModel(self)
        self.sidebar = Sidebar(settings.accent)
        self.grid = AlbumGrid(self.model, settings.accent)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_center())
        self.pl_view = PlaylistView(self.db, cover_pixmap, settings.accent)
        pl_page = QWidget()
        pl_lay = QVBoxLayout(pl_page)
        pl_lay.setContentsMargins(16, 12, 8, 8)
        pl_lay.addWidget(self.pl_view)
        self.stack.addWidget(pl_page)
        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self._build_right())
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([230, 800, 320])
        root.addWidget(self.splitter, 1)

        self.player = PlayerBar(settings.accent)
        root.addWidget(self.player)
        self._build_statusbar()
        self._build_shortcuts()

        b = self.backend
        b.connectionChanged.connect(self._on_connection)
        b.statusChanged.connect(self._on_status)
        b.error.connect(self._on_error)
        self.player.keyRequested.connect(self._on_key)
        self.player.playPauseRequested.connect(self._play_pause)
        self.sidebar.filterChanged.connect(self._on_filter)
        self.grid.playRequested.connect(self.play_album)
        self.grid.contextRequested.connect(self._album_menu)
        self.sidebar.contextRequested.connect(self._sidebar_menu)
        self.detail.trackMenuRequested.connect(self._track_menu)
        self.playlist = PlaylistPlayer(self.backend, self._last_track,
                                       lambda s: (a := self.db.album(s)) is not None and a.present, self)
        self.playlist.changed.connect(self._on_playlist_changed)
        self.playlist.finished.connect(self._on_playlist_finished)
        self.pl_view.playRequested.connect(self.play_playlist)
        self.pl_view.changed.connect(self.reload_library)
        self.pl_view.renameRequested.connect(self.rename_playlist)
        self.pl_view.deleteRequested.connect(self.delete_playlist)
        QApplication.instance().installEventFilter(self)
        self.scan.progress.connect(self._on_scan_progress)
        self.scan.finished.connect(self._on_scan_finished)
        self.scan.libraryChanged.connect(self.reload_library)
        self.scan.finished.connect(lambda *_: self.meta.enqueue_missing())
        self.scan.discRead.connect(self._on_disc_read)
        self.scan.discSwapped.connect(lambda s: self.statusBar().showMessage(
            f"Disc {s}: andere CD als bisher erkannt – alte Daten verworfen, wird neu erkannt", 10000))
        self.slot_watch = SlotWatcher(self.backend, self.db, self.scan, self)
        self.slot_watch.changed.connect(self._on_changer_changed)
        self.meta.discUpdated.connect(lambda _slot: self._reload_timer.start())
        self.meta.statusText.connect(lambda t: self.statusBar().showMessage(t, 5000))
        QTimer.singleShot(1500, self.meta.enqueue_missing)

        if settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode()))
        for combo, value in ((self.sort, settings.sort), (self.group, settings.group_by)):
            i = combo.findData(value)
            if i >= 0:
                combo.setCurrentIndex(i)
        self.model.sort, self.model.group_by = self.sort.currentData(), self.group.currentData()
        self.reload_library()
        self._on_connection(False, "nicht verbunden")

    # ------------------------------------------------------------------ layout
    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Header")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 8, 12, 8)
        logo = QLabel()
        logo.setPixmap(icon("disc", self.settings.accent, 22).pixmap(22, 22))
        self.logo = logo
        name = QLabel("MegaSpin")
        name.setObjectName("AppName")
        lay.addWidget(logo)
        lay.addWidget(name)
        lay.addSpacing(30)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Suchen: Interpret, Album oder #Slot …")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(340)
        lay.addWidget(self.search)
        lay.addStretch()
        self.b_rescan = QToolButton()
        self.b_rescan.setIcon(icon("refresh"))
        self.b_rescan.setToolTip("Discs einlesen …")
        self.b_rescan.clicked.connect(self.open_scan_dialog)
        lay.addWidget(self.b_rescan)
        self.conn_btn = QToolButton()
        self.conn_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.conn_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.conn_btn.setToolTip("Verbindung einstellen (Strg+K)")
        self.conn_btn.clicked.connect(self.open_connect_dialog)
        lay.addWidget(self.conn_btn)
        self.b_menu = QToolButton()
        self.b_menu.setIcon(icon("menu"))
        self.b_menu.setToolTip("Menü")
        self.b_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.b_menu)
        menu.addAction("User Files bearbeiten …", self.edit_user_files)
        menu.addAction("Daten aus dem alten Programm importieren …", self.import_old_data)
        menu.addSeparator()
        menu.addAction(icon("settings"), "Einstellungen … (Strg+,)", self.open_settings)
        menu.addAction("Protokoll-Konsole … (F12)", self.open_console)
        self.b_menu.setMenu(menu)
        self.b_settings = QToolButton()
        self.b_settings.setIcon(icon("settings"))
        self.b_settings.setToolTip("Einstellungen (Strg+,)")
        self.b_settings.clicked.connect(self.open_settings)
        lay.addWidget(self.b_settings)
        lay.addWidget(self.b_menu)
        return w

    def _build_center(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 12, 8, 0)
        lay.setSpacing(8)
        top = QHBoxLayout()
        self.b_back = QToolButton()
        self.b_back.setText("←")
        self.b_back.setToolTip("Zurück zur Übersicht (Esc)")
        self.b_back.clicked.connect(self.leave_group)
        self.b_back.hide()
        top.addWidget(self.b_back)
        self.l_count = QLabel("Alben")
        self.l_count.setObjectName("Title")
        top.addWidget(self.l_count)
        top.addStretch()
        top.addWidget(QLabel("Sortieren:"))
        self.sort = QComboBox()
        for key, (label, _) in SORTS.items():
            self.sort.addItem(label, key)
        self.sort.currentIndexChanged.connect(self._on_sort)
        top.addWidget(self.sort)
        top.addSpacing(12)
        top.addWidget(QLabel("Gruppieren:"))
        self.group = QComboBox()
        for key, label in GROUPINGS.items():
            self.group.addItem(label, key)
        self.group.currentIndexChanged.connect(self._on_group)
        top.addWidget(self.group)
        lay.addLayout(top)
        self.az = AlphabetBar()
        self.az.letterClicked.connect(self._jump_letter)
        lay.addWidget(self.az)
        self.detail = AlbumDetail(self.settings.accent, cover_pixmap)
        self.detail.hide()
        self.detail.playRequested.connect(self.play_album)
        self.detail.readFullRequested.connect(self.read_full)
        self.detail.rereadRequested.connect(self._reread_memory)
        self.detail.closeRequested.connect(self.close_detail)
        self.detail.metadataRequested.connect(lambda s: self.meta.enqueue(s, force=True))
        self.detail.chooseMatchRequested.connect(self.choose_match)
        self.detail.coverRequested.connect(self.change_cover)
        self.detail.editRequested.connect(self.edit_album)
        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.setHandleWidth(6)
        self.vsplit.addWidget(self.grid)
        self.vsplit.addWidget(self.detail)
        self.vsplit.setStretchFactor(0, 3)
        self.vsplit.setStretchFactor(1, 2)
        lay.addWidget(self.vsplit, 1)
        self.grid.clicked.connect(lambda idx: idx.data(AlbumRole) is not None
                                  and self.open_detail(idx.data(AlbumRole).slot))
        self.grid.groupOpened.connect(self.enter_group)
        self.grid.groupContextRequested.connect(self._group_menu)
        self.search.textChanged.connect(self.model.set_search)
        self.model.modelReset.connect(self._update_count)
        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(260)
        w.setStyleSheet(f"background: {COLORS['panel']};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(6)
        head = QLabel("JETZT LÄUFT")
        head.setObjectName("Subtitle")
        lay.addWidget(head)
        self.np_cover = QLabel()
        self.np_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.np_cover.setPixmap(cover_pixmap(None, 240))
        lay.addWidget(self.np_cover)
        self.np_title = QLabel("–")
        self.np_title.setObjectName("Title")
        self.np_title.setWordWrap(True)
        self.np_artist = QLabel("")
        self.np_artist.setWordWrap(True)
        self.np_info = QLabel("")
        self.np_info.setObjectName("Subtitle")
        self.np_info.setWordWrap(True)
        for x in (self.np_title, self.np_artist, self.np_info):
            lay.addWidget(x)
        lay.addSpacing(6)
        tl = QLabel("TRACKS")
        tl.setObjectName("Subtitle")
        lay.addWidget(tl)
        self.tracklist = QTreeWidget()
        self.tracklist.setColumnCount(3)
        self.tracklist.setHeaderHidden(True)
        self.tracklist.setRootIsDecorated(False)
        self.tracklist.setIndentation(0)
        self.tracklist.setUniformRowHeights(True)
        self.tracklist.setStyleSheet(f"QTreeWidget {{ background: {COLORS['panel']}; border: none; outline: 0; }}"
                                     f"QTreeWidget::item {{ padding: 4px 2px; }}"
                                     f"QTreeWidget::item:hover {{ background: {COLORS['hover']}; }}")
        hdr = self.tracklist.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tracklist.itemDoubleClicked.connect(self._track_double_clicked)
        lay.addWidget(self.tracklist, 1)

        sel = QFrame()
        sl = QHBoxLayout(sel)
        sl.setContentsMargins(0, 6, 0, 0)
        sl.setSpacing(6)
        lab = QLabel("Direktwahl")
        lab.setObjectName("Subtitle")
        sl.addWidget(lab)
        sl.addStretch()
        self.sp_disc = NumberField("Disc", 1, 200)
        self.sp_track = NumberField("Track", 1, 99)
        sl.addWidget(self.sp_disc)
        sl.addWidget(self.sp_track)
        self.sp_disc.returnPressed.connect(lambda: self.b_playsel.click())
        self.sp_track.returnPressed.connect(lambda: self.b_playsel.click())
        self.b_playsel = QToolButton()
        self.b_playsel.setIcon(icon("play", self.settings.accent, 20))
        self.b_playsel.setToolTip("Direktwahl abspielen")
        self.b_playsel.clicked.connect(lambda: self.play_album(self.sp_disc.value(), self.sp_track.value()))
        sl.addWidget(self.b_playsel)
        self.b_loadsel = self.b_playsel
        lay.addWidget(sel)
        return w

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.sb_conn = QLabel()
        self.sb_state = QLabel()
        self.sb_mode = QLabel()
        self.sb_scan = QLabel()
        self.sb_prog = QProgressBar()
        self.sb_prog.setFixedWidth(140)
        self.sb_prog.setFixedHeight(4)
        self.sb_prog.setTextVisible(False)
        self.sb_prog.hide()
        sb.addWidget(self.sb_conn)
        sb.addWidget(self.sb_state)
        sb.addPermanentWidget(self.sb_scan)
        sb.addPermanentWidget(self.sb_prog)
        sb.addPermanentWidget(self.sb_mode)

    def _build_shortcuts(self) -> None:
        def sc(seq, fn, ctx=Qt.ShortcutContext.ApplicationShortcut):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(ctx)
            s.activated.connect(fn)
        sc(Qt.Key.Key_Space, self._play_pause, Qt.ShortcutContext.WindowShortcut)
        sc("Ctrl+Right", lambda: self._on_key("next", "tap"))
        sc("Ctrl+Left", lambda: self._on_key("prev", "tap"))
        sc("Ctrl+.", lambda: self._on_key("stop", "tap"))
        sc("Ctrl+R", lambda: self.backend.key("repeat"))
        sc("Ctrl+S", lambda: self.backend.key("random"))
        sc("Ctrl+K", self.open_connect_dialog)
        sc("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Ctrl+L", self.goto_playing)
        sc("Escape", self._escape, Qt.ShortcutContext.WindowShortcut)
        sc(Qt.Key.Key_Return, self._enter_pressed, Qt.ShortcutContext.WindowShortcut)
        sc(Qt.Key.Key_Enter, self._enter_pressed, Qt.ShortcutContext.WindowShortcut)
        sc("Ctrl+,", self.open_settings)
        sc("F12", self.open_console)
        sc("F2", lambda: self.grid.current_slot() and self.edit_album(self.grid.current_slot()))
        sc("F5", lambda: self.grid.current_slot() and self.read_full(self.grid.current_slot()))

    # ------------------------------------------------------------------ library
    def reload_library(self) -> None:
        if self._closed:
            return
        albums = self.db.albums()
        sel = self.grid.current_slot()
        self.model.set_albums(albums)
        self.sidebar.populate(albums, self.db.user_file_names(), self.db.playlists())
        if self.stack.currentIndex() == 1:
            self.pl_view.refresh()
        if sel:
            self.grid.scroll_to_slot(sel)
        if self.detail.isVisible() and self.detail.album:
            a = self.db.album(self.detail.album.slot)
            if a:
                self.detail.show_album(a, self.db.user_file_names())
        self._refresh_now_playing()

    def _update_count(self) -> None:
        m = self.model
        total = len(m.all)
        self.b_back.setVisible(m.open_group is not None)
        self.az.setVisible(not (m.showing_groups and m.group_by == "year"))
        if not total:
            self.l_count.setText("Alben – bitte verbinden, dann erscheinen die Discs im Wechsler"
                                 if self.db.disc_count() else "Alben – noch nicht eingelesen")
            return
        if m.showing_groups:
            what = {"artist": "Interpreten", "year": "Jahre"}[m.group_by]
            n = len(m.visible_albums())
            self.l_count.setText(f"{what} ({len(m.groups)})"
                                 + ("" if n == total else f" · {n} von {total} Alben"))
            return
        g = m.current_group()
        n = len(m.items)
        if g is not None:
            self.l_count.setText(f"{g.title} ({n})")
            return
        self.l_count.setText(f"Alben ({n})" if n == total else f"Alben ({n} von {total})")

    def _on_sort(self, _i: int = 0) -> None:
        self.settings.sort = self.sort.currentData()
        self.model.set_sort(self.settings.sort)

    def _on_group(self, _i: int = 0) -> None:
        self.settings.group_by = self.group.currentData()
        self.close_detail()
        self.model.set_group_by(self.settings.group_by)

    def goto_playing(self) -> None:
        slot = self.status.get("disc", 0)
        if not slot:
            return
        self.stack.setCurrentIndex(0)
        m = self.model
        if m.group_by != "none" and not any(getattr(a, "slot", None) == slot for a in m.items):
            g = next((g for g in m.groups if any(a.slot == slot for a in g.albums)), None)
            if g is not None:
                m.enter_group(g.key)
        self.grid.scroll_to_slot(slot)

    def enter_group(self, key) -> None:
        self.close_detail()
        self.model.enter_group(key)
        self.grid.scrollToTop()

    def leave_group(self) -> None:
        key = self.model.open_group
        self.close_detail()
        self.model.leave_group()
        for row, g in enumerate(self.model.items):
            if getattr(g, "key", None) == key:
                idx = self.model.index(row)
                self.grid.setCurrentIndex(idx)
                self.grid.scrollTo(idx, self.grid.ScrollHint.PositionAtCenter)
                break

    def _group_menu(self, g, pos) -> None:
        m = QMenu(self)
        m.addAction("Öffnen", lambda: self.enter_group(g.key))
        entries = [(a.slot, 0) for a in g.albums]
        m.addAction(icon("play"), "Alle abspielen",
                    lambda: self._start_group_entries(g.title, entries, False))
        m.addAction(icon("shuffle"), "Zufällig abspielen",
                    lambda: self._start_group_entries(g.title, entries, True))
        self._add_to_playlist_menu(m, entries)
        m.exec(pos)

    def _start_group_entries(self, name: str, entries, shuffle: bool) -> None:
        self._playing_pid = None
        self._start_playlist(name, [e for e in entries if (a := self.db.album(e[0])) and a.present], shuffle)

    def _on_filter(self, kind: str, value) -> None:
        if kind == "newplaylist":
            self.new_playlist()
            return
        if kind == "playlist":
            self.show_playlist(value)
            return
        self.stack.setCurrentIndex(0)
        self.model.set_filter(kind, value)

    def _jump_letter(self, letter: str) -> None:
        row = self.model.first_row_for_letter(letter)
        if row >= 0:
            idx = self.model.index(row)
            self.grid.setCurrentIndex(idx)
            self.grid.scrollTo(idx, self.grid.ScrollHint.PositionAtTop)

    def _album_menu(self, slot: int, pos) -> None:
        m = QMenu(self)
        m.addAction(icon("play"), "Abspielen", lambda: self.play_album(slot))
        m.addAction("Nur laden", lambda: self.backend.load(slot))
        m.addAction("Details anzeigen", lambda: self.open_detail(slot))
        m.addAction(icon("edit"), "Bearbeiten … (F2)", lambda: self.edit_album(slot))
        self._add_to_playlist_menu(m, [(slot, 0)])
        m.addSeparator()
        m.addAction(icon("refresh"), "Vollständig einlesen (F5)", lambda: self.read_full(slot))
        m.addAction("Titel neu einlesen (ohne Mechanik)", lambda: self._reread_memory(slot))
        m.addSeparator()
        album = self.db.album(slot)
        a_meta = m.addAction("Metadaten suchen (MusicBrainz)", lambda: self.meta.enqueue(slot, force=True))
        a_meta.setEnabled(bool(album and album.has_toc))
        a_match = m.addAction("Treffer wählen …", lambda: self.choose_match(slot))
        a_match.setEnabled(bool(album and self.db.candidates(slot)))
        m.addAction("Cover ändern …", lambda: self.change_cover(slot))
        if album and album.cover_path:
            m.addAction("Cover entfernen", lambda: self.meta.remove_cover(slot))
        m.exec(pos)

    def choose_match(self, slot: int) -> None:
        album = self.db.album(slot)
        if not album:
            return
        dlg = MatchSelectDialog(slot, album, self.db.candidates(slot), self.meta, self)
        if dlg.exec():
            if dlg.none_fits:
                self.meta.select(slot, None)
            elif dlg.choice:
                self.meta.select(slot, dlg.choice)

    # ------------------------------------------------------------------ editing (D6)
    def edit_album(self, slot: int) -> None:
        album = self.db.album(slot)
        if not album:
            return
        can_write = self.backend.connected and album.present
        dlg = EditAlbumDialog(album, self.db.source_titles(slot), self.db.user_file_names(), can_write, self)
        if not dlg.exec():
            return
        self.db.save_user(slot, **dlg.user_values())
        self.reload_library()
        if dlg.write_to_changer:
            self.write_titles_to_changer(slot, dlg.changer_payload())

    # ------------------------------------------------------------------ playlists (D7)
    def _last_track(self, slot: int):
        a = self.db.album(slot)
        return a.track_count if a and a.has_toc else None

    def _on_key(self, key: str, action: str) -> None:
        if self.playlist.active and action == "tap":
            if key == "next":
                self.playlist.next()
                return
            if key == "prev":
                self.playlist.prev()
                return
            if key == "stop":
                self.playlist.stop("stopped")
        self.backend.key(key, action)

    def _start_playlist(self, name: str, entries, shuffle: bool = False, start: int = 0) -> None:
        if not self.backend.connected:
            self._on_error("NOT_CONNECTED", "")
            return
        if self.scan.mode == "full":
            self.scan.cancel()
        if self.playlist.active:
            self.playlist.stop("user")
        if not self.playlist.start(name, entries, shuffle=shuffle, start_index=start):
            self.statusBar().showMessage("Nichts abzuspielen (keine der Discs ist im Wechsler).", 6000)

    def play_playlist(self, pid: int, start: int = 0, shuffle: bool = False) -> None:
        self._playing_pid = pid
        self._start_playlist(self.db.playlist_name(pid) or "Playlist", self.db.playlist_items(pid),
                             shuffle, start)

    def play_group(self, kind: str, value, shuffle: bool) -> None:
        """Genre / user file / artist: all matching discs, played one after the other."""
        from ..data.names import artist_key
        from .library import SORTS
        albums = sorted((a for a in self.model.all if a.present), key=SORTS[self.model.sort][1])
        if kind == "genre":
            albums, name = [a for a in albums if a.music_type == value], music_type_name(value)
        elif kind == "userfile":
            albums = [a for a in albums if a.user_files & (1 << (value - 1))]
            name = self.db.user_file_names().get(value, f"User File {value}")
        elif kind == "artist":
            albums = [a for a in albums if artist_key(a.artist) == value]
            name = albums[0].display_artist if albums else ""
        else:
            name = "Alle Alben"
        self._playing_pid = None
        self._start_playlist(name, [(a.slot, 0) for a in albums], shuffle)

    def _on_playlist_changed(self) -> None:
        self.player.set_playlist(self.playlist.label())
        pid = getattr(self, "_playing_pid", None)
        on_view = self.playlist.active and pid is not None and self.pl_view.pid == pid
        self.pl_view.mark_playing(self.playlist.index if on_view else -1)

    def _on_playlist_finished(self, reason: str) -> None:
        self.player.set_playlist("")
        self.pl_view.mark_playing(-1)
        text = {"end": "Playlist zu Ende", "user": "Playlist beendet (andere Auswahl)",
                "stopped": "Playlist gestoppt"}.get(reason, "Playlist beendet")
        self.statusBar().showMessage(text, 5000)

    def show_playlist(self, pid: int) -> None:
        self.close_detail()
        self.pl_view.show_playlist(pid)
        self.stack.setCurrentIndex(1)
        self.sidebar.select("playlist", pid)
        self._on_playlist_changed()

    def new_playlist(self, items=None) -> int | None:
        name, ok = QInputDialog.getText(self, "Neue Playlist", "Name:")
        if not ok or not name.strip():
            return None
        pid = self.db.create_playlist(name.strip())
        if items:
            self.db.add_playlist_items(pid, items)
        self.reload_library()
        if not items:
            self.show_playlist(pid)
        return pid

    def rename_playlist(self, pid: int) -> None:
        name, ok = QInputDialog.getText(self, "Playlist umbenennen", "Name:",
                                        text=self.db.playlist_name(pid) or "")
        if ok and name.strip():
            self.db.rename_playlist(pid, name.strip())
            self.reload_library()
            self.pl_view.refresh()

    def delete_playlist(self, pid: int) -> None:
        name = self.db.playlist_name(pid)
        if QMessageBox.question(self, "Playlist löschen", f"Playlist „{name}“ löschen?") \
                != QMessageBox.StandardButton.Yes:
            return
        if self.playlist.active and getattr(self, "_playing_pid", None) == pid:
            self.playlist.stop("stopped")
        self.db.delete_playlist(pid)
        self.stack.setCurrentIndex(0)
        self.sidebar.select("all")
        self.model.set_filter("all")
        self.reload_library()

    def _add_to_playlist_menu(self, menu: QMenu, items: list[tuple[int, int]]) -> None:
        sub = menu.addMenu("Zu Playlist hinzufügen")
        for pid, name, _n in self.db.playlists():
            sub.addAction(name, lambda p=pid, n=name: self._add_items(p, n, items))
        if self.db.playlists():
            sub.addSeparator()
        sub.addAction("Neue Playlist …", lambda: self.new_playlist(items))

    def _add_items(self, pid: int, name: str, items) -> None:
        self.db.add_playlist_items(pid, items)
        self.reload_library()
        self.statusBar().showMessage(f"Zu „{name}“ hinzugefügt", 4000)

    def _track_menu(self, slot: int, track: int, pos) -> None:
        m = QMenu(self)
        m.addAction(icon("play"), "Abspielen", lambda: self.play_album(slot, track))
        self._add_to_playlist_menu(m, [(slot, track)])
        m.exec(pos)

    def _sidebar_menu(self, kind: str, value, pos) -> None:
        m = QMenu(self)
        if kind in ("genre", "userfile", "artist", "all"):
            m.addAction(icon("play"), "Alle abspielen", lambda: self.play_group(kind, value, False))
            m.addAction(icon("shuffle"), "Zufällig abspielen", lambda: self.play_group(kind, value, True))
        elif kind == "playlist":
            m.addAction(icon("play"), "Abspielen", lambda: self.play_playlist(value))
            m.addAction(icon("shuffle"), "Zufällig abspielen", lambda: self.play_playlist(value, 0, True))
            m.addSeparator()
            m.addAction("Umbenennen …", lambda: self.rename_playlist(value))
            m.addAction("Löschen", lambda: self.delete_playlist(value))
        else:
            return
        m.exec(pos)

    def _enter_pressed(self) -> None:
        if self.stack.currentIndex() == 0 and self.grid.hasFocus() and self.grid.current_slot():
            self.play_album(self.grid.current_slot())

    def eventFilter(self, obj, ev) -> bool:
        """Ctrl+Shift+→ / ← held = fast forward / rewind (press on key down, release on key up)."""
        from PySide6.QtCore import QEvent
        t = ev.type()
        if t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and self.isActiveWindow() \
                and ev.key() in (Qt.Key.Key_Right, Qt.Key.Key_Left) and not ev.isAutoRepeat():
            name = "ff" if ev.key() == Qt.Key.Key_Right else "rew"
            mods = ev.modifiers()
            ctrl_shift = (mods & Qt.KeyboardModifier.ControlModifier) and (mods & Qt.KeyboardModifier.ShiftModifier)
            if t == QEvent.Type.KeyPress and ctrl_shift and self.backend.connected:
                self._held = name
                self.backend.key(name, "press")
                return True
            if t == QEvent.Type.KeyRelease and getattr(self, "_held", None) == name:
                self._held = None
                self.backend.key(name, "release")
                return True
        return super().eventFilter(obj, ev)

    def _on_disc_read(self, slot: int) -> None:
        if self._closed:
            return
        if slot in self.db.needs_metadata():
            self.meta.enqueue(slot)
        else:
            self.meta.enqueue_missing_covers()

    def _on_changer_changed(self) -> None:
        if self.backend.connected and not self.scan.busy:
            self.statusBar().showMessage("Discs im Wechsler haben sich geändert – neue Discs werden eingelesen …",
                                         6000)
            self.scan.quick(only_new=True)

    def write_titles_to_changer(self, slot: int, payload: dict) -> None:
        self.statusBar().showMessage(f"Disc {slot}: Titel werden in den Wechsler geschrieben …")

        def work(svc):
            svc.write_titles(slot, payload["title"], payload["tracks"], payload["music_type"],
                             payload["user_files"])
            texts, mt, uf = svc.read_memory(slot)          # check + update changer values
            self.db.save_memory(slot, texts, mt, uf)
            return mt == payload["music_type"] and uf == payload["user_files"]

        def done(ok, res):
            if ok:
                self.statusBar().showMessage(f"Disc {slot}: in den Wechsler geschrieben"
                                             + ("" if res else " – Kontrolle abweichend, bitte prüfen"), 8000)
            else:
                self.statusBar().showMessage(f"Disc {slot}: Schreiben fehlgeschlagen ({res})", 10000)
            self.reload_library()
        self.backend.call(work, done)

    def edit_user_files(self) -> None:
        current = self.db.user_file_names()
        shown = {n: ("" if name == f"User File {n}" else name) for n, name in current.items()}
        dlg = UserFilesDialog(shown, self.backend.connected, self)
        if not dlg.exec():
            return
        names = dlg.names()
        self.db.set_user_file_names(names)
        self.reload_library()
        if dlg.write_to_changer:
            self.statusBar().showMessage("User-File-Namen werden in den Wechsler geschrieben …")

            def work(svc):
                svc.write_user_file_names({n: v for n, v in names.items() if v})
                self.db.save_user_file_names(svc.read_user_file_names())

            def done(ok, res):
                self.statusBar().showMessage("User-File-Namen in den Wechsler geschrieben" if ok
                                             else f"Schreiben fehlgeschlagen ({res})", 8000)
                self.reload_library()
            self.backend.call(work, done)

    # ------------------------------------------------------------------ settings / console (D8)
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if not dlg.exec():
            return
        changed = dlg.apply()
        if "accent" in changed:
            self.apply_accent(self.settings.accent)
        if changed.get("mb_enabled"):
            self.meta.enqueue_missing()
        if "port" in changed and self.settings.port:
            if QMessageBox.question(self, "Verbindung", f"Jetzt mit {self.settings.port} verbinden?") \
                    == QMessageBox.StandardButton.Yes:
                self.connect_to(self.settings.port)
        self.statusBar().showMessage("Einstellungen gespeichert", 4000)

    def apply_accent(self, accent: str) -> None:
        """New accent colour without restart: stylesheet plus all widgets that paint it themselves."""
        from PySide6.QtGui import QColor as _QColor
        from .theme import stylesheet
        QApplication.instance().setStyleSheet(stylesheet(accent))
        self.sidebar.set_accent(accent)
        self.grid.delegate.accent = _QColor(accent)
        self.grid.viewport().update()
        self.detail.accent = accent
        self.pl_view.accent = accent
        self.player.set_accent(accent, self.status)
        self.logo.setPixmap(icon("disc", accent, 22).pixmap(22, 22))
        self.b_playsel.setIcon(icon("play", accent, 20))
        if self.detail.album:
            self.detail.mark_playing(*self.detail.playing)
        self.pl_view.mark_playing(self.pl_view.playing_index)
        self._refresh_now_playing()

    def open_console(self) -> None:
        self.console.show()
        self.console.raise_()
        self.console.activateWindow()

    def import_old_data(self) -> None:
        start = str(OLD_DATA_DIR) if OLD_DATA_DIR.exists() else ""
        folder = QFileDialog.getExistingDirectory(self, "Datenordner des alten Programms wählen", start)
        if not folder:
            return
        try:
            res = import_folder(folder, self.db)
        except Exception as e:
            QMessageBox.warning(self, "Import", f"Import fehlgeschlagen:\n{e}")
            return
        self.reload_library()
        self.meta.enqueue_missing()
        QMessageBox.information(
            self, "Import abgeschlossen",
            f"Inhaltsverzeichnisse: {res.tocs}\nDiscs mit eigenen Titeln: {res.titles}\n"
            f"User-File-Namen: {res.user_files}\n\n"
            "Discs, die nicht im Wechsler sind, erscheinen erst, wenn sie eingelegt und eingelesen werden.")

    def change_cover(self, slot: int) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Cover für Disc {slot} wählen", "",
                                              "Bilder (*.jpg *.jpeg *.png)")
        if path:
            self.meta.set_cover_file(slot, path)

    # ------------------------------------------------------------------ details / scanning
    def open_detail(self, slot: int) -> None:
        album = self.db.album(slot)
        if not album:
            return
        self.detail.show_album(album, self.db.user_file_names())
        self.detail.mark_playing(self.status.get("disc", 0) if self.status.get("play_state") in ACTIVE_STATES
                                 else 0, self.status.get("track", 0))
        if self.detail.isHidden():
            self.detail.show()
            total = self.vsplit.height()
            self.vsplit.setSizes([int(total * 0.55), int(total * 0.45)])
        self.grid.scroll_to_slot(slot)

    def close_detail(self) -> None:
        self.detail.hide()
        self.detail.album = None

    def _escape(self) -> None:
        if self.detail.isVisible():
            self.close_detail()
        elif self.stack.currentIndex() == 0 and self.model.open_group is not None:
            self.leave_group()
        else:
            self.search.clear()

    def read_full(self, slot: int) -> None:
        if not self.backend.connected:
            self._on_error("NOT_CONNECTED", "")
            return
        if self.status.get("play_state") in ("playing", "paused", "ff", "rew") and                 self.status.get("loaded_disc") != slot:
            r = QMessageBox.question(self, "Disc einlesen",
                                     f"Zum Einlesen muss Disc {slot} geladen werden. "
                                     "Die laufende Wiedergabe wird dabei beendet. Fortfahren?")
            if r != QMessageBox.StandardButton.Yes:
                return
            self.backend.key("stop")
        if self.scan.running:
            self.statusBar().showMessage(f"Disc {slot} wird nach dem laufenden Einlesen gelesen.", 5000)
        self.scan.full([slot])

    def open_scan_dialog(self) -> None:
        if not hasattr(self, "_scan_dialog") or self._scan_dialog is None:
            self._scan_dialog = ScanDialog(
                self.scan, lambda: self.model.all, self.grid.current_slot,
                lambda: self.status.get("play_state") in ("playing", "paused", "ff", "rew"),
                lambda: self.backend.key("stop"), self)
        self._scan_dialog.show()
        self._scan_dialog.raise_()

    def _reread_memory(self, slot: int) -> None:
        def work(svc):
            texts, mt, uf = svc.read_memory(slot)
            self.db.save_memory(slot, texts, mt, uf)
        self.backend.call(work, lambda ok, _: self.reload_library())

    def play_album(self, slot: int, track: int = 1) -> None:
        if not self.backend.connected:
            self._on_error("NOT_CONNECTED", "")
            return
        if self.scan.mode == "full":
            self.scan.cancel()
            self.statusBar().showMessage("Einlesen wird nach der aktuellen Disc abgebrochen.", 5000)
        if self.playlist.active:
            self.playlist.stop("user")
        self.backend.play(slot, track)
        self.db.mark_played(slot)

    def _track_double_clicked(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        no = item.data(0, Qt.ItemDataRole.UserRole)
        if self._np_album and no:
            self.play_album(self._np_album.slot, no)

    # ------------------------------------------------------------------ scanning
    def _on_scan_progress(self, done: int, total: int, text: str) -> None:
        self.sb_prog.show()
        self.sb_prog.setRange(0, max(total, 1))
        self.sb_prog.setValue(done)
        self.sb_scan.setText(text)

    def _on_scan_finished(self, ok: bool, text: str) -> None:
        self.sb_prog.hide()
        self.sb_scan.setText("")
        self.statusBar().showMessage(("Einlesen: " + text) if ok else f"Einlesen fehlgeschlagen: {text}", 6000)

    # ------------------------------------------------------------------ connection
    def auto_connect(self) -> None:
        if self.settings.auto_connect and self.settings.port:
            self.connect_to(self.settings.port)
        else:
            self.open_connect_dialog()

    def open_connect_dialog(self) -> None:
        dlg = ConnectDialog(self.backend, self.settings.port, self.settings.auto_connect, self)
        if dlg.exec():
            self.settings.port = dlg.selected
            self.settings.auto_connect = dlg.auto_connect
            self.settings.save()
            self.connect_to(dlg.selected)

    def connect_to(self, target: str) -> None:
        label = "Simulator" if target == SIM_TARGET else target
        self._set_conn_indicator("warn", f"Verbinde mit {label} …")

        def done(ok, res):
            if ok:
                self.scan.quick(only_new=self.db.slot_count() > 0)
            else:
                QMessageBox.warning(self, "Verbindung fehlgeschlagen",
                                    f"Keine Verbindung zum Wechsler über {label}.\n\n{res}\n\n"
                                    "Bitte Kabel, Schnittstelle und Wechsler prüfen. "
                                    "Läuft noch ein anderes Programm auf dieser Schnittstelle?")
        self.backend.connect_to(target, done)

    def _set_conn_indicator(self, level: str, text: str) -> None:
        color = {"ok": COLORS["ok"], "warn": COLORS["warn"], "err": COLORS["err"]}[level]
        self.conn_btn.setIcon(icon("plug", color, 18))
        self.conn_btn.setIconSize(QSize(18, 18))
        self.conn_btn.setText(f"  {text}")
        self.sb_conn.setText(f"<span style='color:{color}'>●</span> {text}")

    def _on_connection(self, online: bool, text: str) -> None:
        if online:
            self._set_conn_indicator("ok", f"Verbunden: {text}")
            self.slot_watch.start()
        else:
            self._set_conn_indicator("err" if self.backend.svc is None else "warn", text or "Nicht verbunden")
        self.player.set_enabled(online)
        self.b_playsel.setEnabled(online)
        self.b_loadsel.setEnabled(online)
        self.b_rescan.setEnabled(online)
        if not online:
            self.player.set_now_playing("Nicht verbunden", "", None)
            self.slot_watch.stop()

    def _on_error(self, code: str, msg: str) -> None:
        texts = {"BUSY": "Wechsler beschäftigt – bitte erneut versuchen",
                 "NOT_RESPONDING": "Wechsler antwortet nicht",
                 "NOT_CONNECTED": "Keine Verbindung zum Wechsler"}
        self.statusBar().showMessage(texts.get(code, f"Fehler: {msg}"), 6000)

    # ------------------------------------------------------------------ status
    def _on_status(self, st: dict, changed: list) -> None:
        if self._closed:
            return
        self.status = st
        self.player.update_status(st)
        if "loaded_disc" in changed or "*" in changed:
            self.scan.loaded_disc(st.get("loaded_disc", 0))
        self.slot_watch.on_status(st, changed)
        self.playlist.on_status(st)
        playing_disc = st.get("disc", 0) if st.get("play_state") in ACTIVE_STATES else 0
        self.model.set_playing(playing_disc)
        self.detail.mark_playing(playing_disc, st.get("track", 0))
        self._refresh_now_playing()

    def _refresh_now_playing(self) -> None:
        st = self.status
        disc, track = st.get("disc", 0), st.get("track", 0)
        album = self.db.album(disc) if disc else None
        sig = (album.slot, tuple((t.no, t.title, t.length_s) for t in album.tracks)) if album else None
        if sig != getattr(self, "_np_sig", None):
            self._np_sig = sig
            self._fill_tracklist(album)
        self._np_album = album
        tracks = {t.no: t for t in album.tracks} if album else {}
        t = tracks.get(track)
        track_title = t.title if t else (f"Track {track}" if track else "–")
        artist = album.display_artist if album else ""
        title = album.display_album if album else (f"Disc {disc}" if disc else "")
        state = PLAY_STATE_TEXT.get(st.get("play_state", "unknown"), "")

        self.np_cover.setPixmap(cover_pixmap(album, 240))
        self.np_title.setText(track_title)
        self.np_artist.setText(" – ".join(x for x in (artist, title) if x))
        extra = [f"Disc {disc}", f"Track {track}", state]
        if st.get("disc_music_type"):
            extra.append(music_type_name(st["disc_music_type"]))
        self.np_info.setText(" · ".join(x for x in extra if x))
        for i in range(self.tracklist.topLevelItemCount()):
            it = self.tracklist.topLevelItem(i)
            on = it.data(0, Qt.ItemDataRole.UserRole) == track and st.get("play_state") in ACTIVE_STATES
            it.setForeground(1, QColor(self.settings.accent if on else COLORS["text"]))
        self.player.set_now_playing(track_title, " – ".join(x for x in (artist, title) if x),
                                    t.length_s if t else None)
        self.sb_state.setText(f"{state} · Disc {disc} · Track {track}" if disc else state)
        rnd = {"one": " · Random 1 Disc", "all": " · Random alle"}.get(st.get("random", "off"), "")
        rep = " · Repeat" if st.get("repeat") else ""
        self.sb_mode.setText(MODE_TEXT.get(st.get("mode", "track"), "") + rnd + rep)
        if disc and not self.sp_disc.hasFocus():
            self.sp_disc.setValue(disc)

    def _fill_tracklist(self, album: Album | None) -> None:
        self.tracklist.clear()
        if not album:
            return
        for t in album.tracks:
            it = QTreeWidgetItem([str(t.no), t.title, fmt_time(t.length_s) if t.length_s else ""])
            it.setData(0, Qt.ItemDataRole.UserRole, t.no)
            it.setToolTip(1, t.title)
            it.setTextAlignment(0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setForeground(0, QColor(COLORS["text2"]))
            it.setForeground(2, QColor(COLORS["text2"]))
            self.tracklist.addTopLevelItem(it)

    # ------------------------------------------------------------------ actions
    def _play_pause(self) -> None:
        if not self.backend.connected:
            return
        if self.status.get("play_state") in ("stopped", "unknown"):
            sel = self.grid.current_slot()
            if sel and sel != self.status.get("disc"):
                self.play_album(sel)
                return
        self.backend.key("play_pause")

    def closeEvent(self, ev) -> None:
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.save()
        self._closed = True
        self.playlist.stop("stopped")
        # late results of background jobs must not reach the UI / the closed database
        for obj in (self.scan, self.meta, self.slot_watch, self.playlist, self.console):
            obj.blockSignals(True)
        self.scan.cancel()
        self.meta.stop()
        self.backend.disconnect_from()
        self.backend.pool.waitForDone(3000)
        self.backend.blockSignals(True)
        QApplication.instance().removeEventFilter(self)
        self._reload_timer.stop()
        self.slot_watch.stop()
        self.db.close()
        super().closeEvent(ev)
