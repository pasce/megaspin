"""Scan dialog (Desktop_App_Design §9.5): quick or full, all/incomplete/selected, progress, cancel."""
from __future__ import annotations

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget,
                               QMessageBox, QProgressBar, QPushButton, QRadioButton, QVBoxLayout)


class ScanDialog(QDialog):
    def __init__(self, scan, albums_fn, selected_slot_fn, is_playing_fn, stop_fn, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Discs einlesen")
        self.setMinimumWidth(520)
        self.setModal(False)
        self.scan = scan
        self.albums_fn = albums_fn
        self.selected_slot_fn = selected_slot_fn
        self.is_playing_fn = is_playing_fn
        self.stop_fn = stop_fn

        lay = QVBoxLayout(self)
        t = QLabel("Discs einlesen")
        t.setObjectName("Title")
        lay.addWidget(t)

        self.r_quick = QRadioButton("Schnell – Titel aus dem Wechsler-Speicher, Genre, User Files "
                                    "(ohne Mechanik, ca. 1 s pro Disc)")
        self.r_full = QRadioButton("Vollständig – jede Disc wird geladen: Inhaltsverzeichnis, Tracklängen, "
                                   "CD-TEXT (ca. 15 s pro Disc, keine Wiedergabe)")
        self.r_quick.setChecked(True)
        g1 = QButtonGroup(self)
        g1.addButton(self.r_quick)
        g1.addButton(self.r_full)
        for r in (self.r_quick, self.r_full):
            lay.addWidget(r)
        self.cb_fresh = QCheckBox("Alles neu – gespeicherte Daten verwerfen (Inhaltsverzeichnis, CD-TEXT, "
                                  "MusicBrainz, Cover) und neu holen (wie „Read All Discs“)")
        self.cb_keep_user = QCheckBox("Eigene Änderungen (Titel, Genre, User Files, eigene Cover) behalten")
        self.cb_keep_user.setChecked(True)
        for cb in (self.cb_fresh, self.cb_keep_user):
            cb.setContentsMargins(24, 0, 0, 0)
            lay.addWidget(cb)
        self.r_full.toggled.connect(self._update_fresh)
        self.cb_fresh.toggled.connect(self._update_fresh)
        lay.addSpacing(6)
        self.r_all = QRadioButton("Alle Discs")
        self.r_incomplete = QRadioButton("Nur unvollständige")
        self.r_selected = QRadioButton("Nur ausgewähltes Album")
        self.r_all.setChecked(True)
        g2 = QButtonGroup(self)
        row = QHBoxLayout()
        for r in (self.r_all, self.r_incomplete, self.r_selected):
            g2.addButton(r)
            row.addWidget(r)
        row.addStretch()
        lay.addLayout(row)
        self.r_selected.setEnabled(selected_slot_fn() is not None)
        for r in (self.r_quick, self.r_full, self.r_all, self.r_incomplete, self.r_selected):
            r.toggled.connect(self._update_estimate)

        self.estimate = QLabel()
        self.estimate.setObjectName("Subtitle")
        lay.addWidget(self.estimate)
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.status = QLabel("")
        self.log = QListWidget()
        self.log.setMinimumHeight(140)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        lay.addWidget(self.log, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        self.b_start = QPushButton("Starten")
        self.b_start.setObjectName("Primary")
        self.b_cancel = QPushButton("Abbrechen")
        self.b_close = QPushButton("Schließen")
        btns.addWidget(self.b_cancel)
        btns.addWidget(self.b_close)
        btns.addWidget(self.b_start)
        lay.addLayout(btns)
        self.b_start.clicked.connect(self._start)
        self.b_cancel.clicked.connect(self._cancel)
        self.b_close.clicked.connect(self.close)

        scan.progress.connect(self._on_progress)
        scan.logLine.connect(self.log.addItem)
        scan.finished.connect(self._on_finished)
        self._set_running(scan.running)
        self._update_estimate()

    def _update_fresh(self) -> None:
        on = self.r_full.isChecked() and not self.scan.running
        self.cb_fresh.setEnabled(on)
        self.cb_keep_user.setEnabled(on and self.cb_fresh.isChecked())
        if self.cb_fresh.isChecked() and self.r_full.isChecked():
            self.r_all.setChecked(True)
        self.r_incomplete.setEnabled(not (self.cb_fresh.isChecked() and self.r_full.isChecked()))

    def _slots(self) -> list[int]:
        albums = [a for a in self.albums_fn() if a.present]
        if self.r_selected.isChecked():
            s = self.selected_slot_fn()
            return [s] if s else []
        if self.r_incomplete.isChecked():
            return [a.slot for a in albums if not a.complete]
        return [a.slot for a in albums]

    def _update_estimate(self) -> None:
        n = len(self._slots())
        per = 15 if self.r_full.isChecked() else 1
        mins = n * per / 60
        self.estimate.setText(f"{n} Disc(s) · geschätzte Dauer: "
                              + (f"{mins:.0f} min" if mins >= 1 else f"{n * per} s"))

    def _set_running(self, on: bool) -> None:
        self.b_start.setEnabled(not on)
        self.b_cancel.setEnabled(on)
        for r in (self.r_quick, self.r_full, self.r_all, self.r_incomplete, self.r_selected):
            r.setEnabled(not on and (r is not self.r_selected or self.selected_slot_fn() is not None))
        if hasattr(self, "cb_fresh"):
            self._update_fresh()

    def _start(self) -> None:
        slots = self._slots()
        if not slots:
            self.status.setText("Keine passenden Discs.")
            return
        self.log.clear()
        if self.r_full.isChecked():
            if self.is_playing_fn():
                self.stop_fn()
            fresh = self.cb_fresh.isChecked()
            if fresh and QMessageBox.question(
                    self, "Alles neu einlesen",
                    f"Für {len(slots)} Disc(s) werden die gespeicherten Daten verworfen und neu gelesen"
                    + (" (eigene Änderungen bleiben erhalten)." if self.cb_keep_user.isChecked()
                       else " – auch deine eigenen Änderungen!") + " Fortfahren?") \
                    != QMessageBox.StandardButton.Yes:
                return
            ok = self.scan.full(slots, fresh=fresh, keep_user=self.cb_keep_user.isChecked())
        else:
            ok = self.scan.quick(slots=slots)
        if ok:
            self._set_running(True)

    def _cancel(self) -> None:
        self.scan.cancel()
        self.status.setText("Wird nach der aktuellen Disc abgebrochen …")

    def _on_progress(self, done: int, total: int, text: str) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.status.setText(text)

    def _on_finished(self, ok: bool, text: str) -> None:
        self._set_running(False)
        self.status.setText(text)
        self._update_estimate()
