"""Einstellungen (Desktop_App_Design §8.1 ⚙)."""
from __future__ import annotations
from ... import i18n
from ...i18n import tr

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from ...app.settings import data_dir
from ...backend.serial_backend import SIM_TARGET, list_ports

ACCENTS = [("#E04848", tr("Red")), ("#E07A2E", tr("Orange")), ("#D4A72C", tr("Gold")), ("#3FA864", tr("Green")),
           ("#2E8FE0", tr("Blue")), ("#8A5CE0", tr("Violet")), ("#D9488F", tr("Pink"))]


class SettingsDialog(QDialog):
    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Settings"))
        self.setMinimumWidth(560)
        self.settings = settings
        root = QVBoxLayout(self)

        # ---- connection
        g = QGroupBox(tr("Connection"))
        f = QFormLayout(g)
        self.c_port = QComboBox()
        self.c_port.setEditable(True)
        self._fill_ports()
        self.cb_auto = QCheckBox(tr("Connect automatically at start"))
        self.cb_auto.setChecked(settings.auto_connect)
        b_refresh = QToolButton()
        b_refresh.setText("⟳")
        b_refresh.setToolTip(tr("Search ports again"))
        b_refresh.clicked.connect(self._fill_ports)
        row = QHBoxLayout()
        row.addWidget(self.c_port, 1)
        row.addWidget(b_refresh)
        f.addRow(tr("Port"), row)
        f.addRow("", self.cb_auto)
        root.addWidget(g)

        # ---- metadata
        g = QGroupBox(tr("Titles and covers from the internet"))
        f = QFormLayout(g)
        self.cb_mb = QCheckBox(tr("Search MusicBrainz / Cover Art Archive"))
        self.cb_mb.setChecked(settings.mb_enabled)
        self.e_contact = QLineEdit(settings.mb_contact)
        self.e_contact.setPlaceholderText(tr("optional, e.g. an e-mail address or website"))
        hint = QLabel(tr("MusicBrainz asks for contact information from programs that use its service. It is only sent in the user-agent text of requests to MusicBrainz. Leaving it empty is fine too."))
        hint.setWordWrap(True)
        hint.setObjectName("Subtitle")
        f.addRow("", self.cb_mb)
        f.addRow(tr("Contact"), self.e_contact)
        f.addRow("", hint)
        self.cb_mb.toggled.connect(self.e_contact.setEnabled)
        self.e_contact.setEnabled(settings.mb_enabled)
        root.addWidget(g)

        # ---- appearance
        g = QGroupBox(tr("Appearance"))
        h = QHBoxLayout(g)
        h.addWidget(QLabel(tr("Accent colour")))
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

        # ---- language
        g = QGroupBox(tr("Language"))
        f = QFormLayout(g)
        self.c_lang = QComboBox()
        self.c_lang.addItem(tr("Automatic (system language)"), "auto")
        for code, name in i18n.available().items():
            self.c_lang.addItem(name, code)
        i = self.c_lang.findData(settings.language if settings.language else "auto")
        self.c_lang.setCurrentIndex(max(0, i))
        f.addRow(tr("Interface language"), self.c_lang)
        lang_hint = QLabel(tr("The language change takes effect after restarting MegaSpin."))
        lang_hint.setObjectName("Subtitle")
        lang_hint.setWordWrap(True)
        f.addRow("", lang_hint)
        root.addWidget(g)

        # ---- data
        g = QGroupBox(tr("Data"))
        h = QHBoxLayout(g)
        path = QLabel(str(data_dir()))
        path.setObjectName("Subtitle")
        b_open = QPushButton(tr("Open folder"))
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))
        h.addWidget(QLabel(tr("Library, covers, log file:")))
        h.addWidget(path, 1)
        h.addWidget(b_open)
        root.addWidget(g)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText(tr("Save"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _fill_ports(self) -> None:
        current = self.c_port.currentData() or self.settings.port
        self.c_port.clear()
        for dev, desc in list_ports():
            self.c_port.addItem(f"{dev} – {desc}" if desc and desc != dev else dev, dev)
        self.c_port.addItem(tr("Simulator (no changer)"), SIM_TARGET)
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
               "mb_contact": self.e_contact.text().strip(), "accent": self.accent,
               "language": self.c_lang.currentData()}
        changed = {k: v for k, v in new.items() if getattr(s, k) != v}
        for k, v in new.items():
            setattr(s, k, v)
        s.save()
        return changed
