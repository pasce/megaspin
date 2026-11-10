"""User Files verwalten (Desktop_App_Design §9.6): names of the 8 user files."""
from __future__ import annotations
from ...i18n import tr

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit,
                               QVBoxLayout, QWidget)

from ...protocol.commands import to_changer_text


class UserFilesDialog(QDialog):
    def __init__(self, names: dict[int, str], can_write: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("User files"))
        self.resize(560, 380)
        root = QVBoxLayout(self)
        info = QLabel(tr("User files are 8 freely named groups. A disc can belong to several user files (assigned in the dialog „Edit album“)."))
        info.setWordWrap(True)
        info.setObjectName("Subtitle")
        root.addWidget(info)
        grid = QGridLayout()
        self.edits: list[QLineEdit] = []
        self.previews: list[QLabel] = []
        for n in range(1, 9):
            e = QLineEdit(names.get(n, ""))
            e.setPlaceholderText(f"User File {n}")
            p = QLabel()
            p.setObjectName("Subtitle")
            p.setMinimumWidth(190)
            e.textChanged.connect(lambda _t, i=n - 1: self._preview(i))
            grid.addWidget(QLabel(str(n)), n - 1, 0)
            grid.addWidget(e, n - 1, 1)
            grid.addWidget(p, n - 1, 2)
            self.edits.append(e)
            self.previews.append(p)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        for i in range(8):
            self._preview(i)
        self.cb_write = QCheckBox(tr("Also write to the changer"))
        self.cb_write.setEnabled(can_write)
        if not can_write:
            self.cb_write.setToolTip(tr("Only possible if the changer is connected"))
        root.addWidget(self.cb_write)
        root.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText(tr("Save"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _preview(self, i: int) -> None:
        t = self.edits[i].text().strip() or f"USER FILE {i + 1}"
        self.previews[i].setText(tr("Changer: ") + to_changer_text(t).decode())

    @property
    def write_to_changer(self) -> bool:
        return self.cb_write.isEnabled() and self.cb_write.isChecked()

    def names(self) -> dict[int, str]:
        return {n: self.edits[n - 1].text().strip() for n in range(1, 9)}
