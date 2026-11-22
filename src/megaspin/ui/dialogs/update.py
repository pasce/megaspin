"""Popup for a new version: installed version, new version, Download, Cancel (Desktop_App_Design §8.4)."""
from __future__ import annotations
from ...i18n import tr

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...app.updates import UpdateInfo


class UpdateDialog(QDialog):
    def __init__(self, installed: str, info: UpdateInfo, on_download, on_cancel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Update available"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        title = QLabel(tr("A new version of MegaSpin is available."))
        title.setObjectName("Title")
        title.setWordWrap(True)
        lay.addWidget(title)
        form = QFormLayout()
        form.addRow(tr("Installed version"), QLabel(installed))
        form.addRow(tr("New version"), QLabel(info.latest))
        lay.addLayout(form)
        bb = QDialogButtonBox()
        b_download = QPushButton(tr("Download"))
        b_download.setObjectName("Primary")
        b_cancel = QPushButton(tr("Cancel"))
        bb.addButton(b_download, QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(b_cancel, QDialogButtonBox.ButtonRole.RejectRole)
        lay.addWidget(bb)
        b_download.clicked.connect(lambda: (on_download(), self.accept()))
        b_cancel.clicked.connect(lambda: (on_cancel(), self.reject()))
