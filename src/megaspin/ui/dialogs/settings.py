"""Einstellungen (Desktop_App_Design §8.1 ⚙)."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from ...app.settings import data_dir
from ...backend.serial_backend import SIM_TARGET, list_ports

ACCENTS = [("#E04848", "Rot"), ("#E07A2E", "Orange"), ("#D4A72C", "Gold"), ("#3FA864", "Grün"),
           ("#2E8FE0", "Blau"), ("#8A5CE0", "Violett"), ("#D9488F", "Pink")]


class SettingsDialog(QDialog):
    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(560)
        self.settings = settings
        root = QVBoxLayout(self)

        # ---- connection
        g = QGroupBox("Verbindung")
        f = QFormLayout(g)
        self.c_port = QComboBox()
        self.c_port.setEditable(True)
        self._fill_ports()
        self.cb_auto = QCheckBox("Beim Start automatisch verbinden")
        self.cb_auto.setChecked(settings.auto_connect)
        b_refresh = QToolButton()
        b_refresh.setText("⟳")
        b_refresh.setToolTip("Ports neu suchen")
        b_refresh.clicked.connect(self._fill_ports)
        row = QHBoxLayout()
        row.addWidget(self.c_port, 1)
        row.addWidget(b_refresh)
        f.addRow("Port", row)
        f.addRow("", self.cb_auto)
        root.addWidget(g)

        # ---- metadata
        g = QGroupBox("Titel und Cover aus dem Internet")
        f = QFormLayout(g)
        self.cb_mb = QCheckBox("Bei MusicBrainz / Cover Art Archive suchen")
        self.cb_mb.setChecked(settings.mb_enabled)
        self.e_contact = QLineEdit(settings.mb_contact)
        self.e_contact.setPlaceholderText("optional, z. B. eine E-Mail-Adresse oder Webseite")
        hint = QLabel("MusicBrainz bittet um eine Kontaktangabe für Programme, die seinen Dienst nutzen. "
                      "Sie wird nur im Kennungstext der Anfragen an MusicBrainz übertragen. Leer lassen geht auch.")
        hint.setWordWrap(True)
        hint.setObjectName("Subtitle")
        f.addRow("", self.cb_mb)
        f.addRow("Kontakt", self.e_contact)
        f.addRow("", hint)
        self.cb_mb.toggled.connect(self.e_contact.setEnabled)
        self.e_contact.setEnabled(settings.mb_enabled)
        root.addWidget(g)

        # ---- appearance
        g = QGroupBox("Darstellung")
        h = QHBoxLayout(g)
        h.addWidget(QLabel("Akzentfarbe"))
        self.accent = settings.accent
        self._swatches = QButtonGroup(self)
        for color, name in ACCENTS:
            b = QToolButton()
            b.setCheckable(True)
            b.setToolTip(name)
            b.setFixedSize(28, 28)
            b.setStyleSheet(f"QToolButton {{ background: {color}; border-radius: 14px; border: 2px solid transparent; }}"
                            f"QToolButton:checked {{ border: 2px solid white; }}")
            b.setChecked(color.lower() == settings.accent.lower())
            b.clicked.connect(lambda _=False, c=color: setattr(self, "accent", c))
            self._swatches.addButton(b)
            h.addWidget(b)
        h.addStretch()
        root.addWidget(g)

        # ---- data
        g = QGroupBox("Daten")
        h = QHBoxLayout(g)
        path = QLabel(str(data_dir()))
        path.setObjectName("Subtitle")
        b_open = QPushButton("Ordner öffnen")
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))
        h.addWidget(QLabel("Bibliothek, Cover, Logdatei:"))
        h.addWidget(path, 1)
        h.addWidget(b_open)
        root.addWidget(g)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _fill_ports(self) -> None:
        current = self.c_port.currentData() or self.settings.port
        self.c_port.clear()
        for dev, desc in list_ports():
            self.c_port.addItem(f"{dev} – {desc}" if desc and desc != dev else dev, dev)
        self.c_port.addItem("Simulator (ohne Wechsler)", SIM_TARGET)
        i = self.c_port.findData(current)
        if i < 0 and current:
            self.c_port.insertItem(0, current, current)
            i = 0
        self.c_port.setCurrentIndex(max(0, i))

    @property
    def port(self) -> str:
        data = self.c_port.currentData()
        text = self.c_port.currentText().strip()
        if data and self.c_port.itemText(self.c_port.currentIndex()) == text:
            return data
        return text.split(" ")[0] if text else ""

    def apply(self) -> dict:
        """Write the values into the settings; returns what changed."""
        s = self.settings
        new = {"port": self.port, "auto_connect": self.cb_auto.isChecked(), "mb_enabled": self.cb_mb.isChecked(),
               "mb_contact": self.e_contact.text().strip(), "accent": self.accent}
        changed = {k: v for k, v in new.items() if getattr(s, k) != v}
        for k, v in new.items():
            setattr(s, k, v)
        s.save()
        return changed
