"""About window: name, version, description, licence, links (plaintext.at and GitHub)."""
from __future__ import annotations
from ...i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from ... import __version__
from ...app.updates import ABOUT_URL, GITHUB_URL


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("About MegaSpin"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        name = QLabel(f"<h2>MegaSpin</h2><p><b>{tr('Version')} {__version__}</b></p>")
        name.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(name)
        desc = QLabel(tr("MegaSpin is a desktop app for 200-disc Kenwood mega CD changers (DPF-J6030, CD-425M). "
                         "It connects over the PC-LINK serial port and shows the changer as a cover library."))
        desc.setWordWrap(True)
        lay.addWidget(desc)
        links = QLabel(f'{tr("Website")}: <a href="{ABOUT_URL}">{ABOUT_URL}</a><br>'
                       f'{tr("Source code")}: <a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        links.setOpenExternalLinks(True)
        links.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(links)
        lic = QLabel(f"{tr('Licence')}: MIT<br>© 2026 MegaSpin contributors")
        lic.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(lic)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
