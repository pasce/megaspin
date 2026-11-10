"""Connection dialog: choose port, auto-detect via Hello (Desktop_App_Design §9.1)."""
from __future__ import annotations
from ...i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from ...backend.serial_backend import SIM_TARGET, list_ports, probe_port


class ConnectDialog(QDialog):
    def __init__(self, backend, current: str = "", auto_connect: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Connect to changer"))
        self.setMinimumWidth(460)
        self.backend = backend
        self.selected = ""

        lay = QVBoxLayout(self)
        title = QLabel(tr("Choose serial port"))
        title.setObjectName("Title")
        lay.addWidget(title)
        hint = QLabel(tr("The changer is connected with an RS-232 cable (9600 baud)."))
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.info = QLabel("")
        self.info.setObjectName("Subtitle")
        lay.addWidget(self.info)

        self.cb_auto = QCheckBox(tr("Connect automatically at program start"))
        self.cb_auto.setChecked(auto_connect)
        lay.addWidget(self.cb_auto)

        row = QHBoxLayout()
        self.b_refresh = QPushButton(tr("Refresh"))
        self.b_search = QPushButton(tr("Search automatically"))
        self.b_ok = QPushButton(tr("Connect"))
        self.b_ok.setObjectName("Primary")
        self.b_ok.setDefault(True)
        b_cancel = QPushButton(tr("Cancel"))
        row.addWidget(self.b_refresh)
        row.addWidget(self.b_search)
        row.addStretch()
        row.addWidget(b_cancel)
        row.addWidget(self.b_ok)
        lay.addLayout(row)

        self.b_refresh.clicked.connect(lambda: self._fill(current))
        self.b_search.clicked.connect(self._search)
        self.b_ok.clicked.connect(self._accept)
        b_cancel.clicked.connect(self.reject)
        self.list.itemDoubleClicked.connect(lambda *_: self._accept())
        self._fill(current)

    def _fill(self, current: str) -> None:
        self.list.clear()
        for dev, desc in list_ports():
            it = QListWidgetItem(f"{dev}    {desc}")
            it.setData(Qt.ItemDataRole.UserRole, dev)
            self.list.addItem(it)
            if dev == current:
                self.list.setCurrentItem(it)
        sim = QListWidgetItem(tr("Simulator    (test without changer)"))
        sim.setData(Qt.ItemDataRole.UserRole, SIM_TARGET)
        self.list.addItem(sim)
        if current == SIM_TARGET:
            self.list.setCurrentItem(sim)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self.info.setText(tr("{0} serial port(s) found.").format(self.list.count() - 1))

    def _search(self) -> None:
        ports = [d for d, _ in list_ports()]
        if not ports:
            self.info.setText(tr("No serial port found."))
            return
        self.info.setText(tr("Searching for changer on ") + ", ".join(ports) + " …")
        self.b_search.setEnabled(False)

        def work():
            for dev in ports:
                model = probe_port(dev)
                if model:
                    return dev, model
            return None

        def done(ok, res):
            self.b_search.setEnabled(True)
            if ok and res:
                dev, model = res
                self.info.setText(tr("Found: {0} on {1}").format(model, dev))
                for i in range(self.list.count()):
                    if self.list.item(i).data(Qt.ItemDataRole.UserRole) == dev:
                        self.list.setCurrentRow(i)
            else:
                self.info.setText(tr("No changer found. Check cable, port and device (is another program using the port?)."))
        self.backend.run_async(work, done, report_errors=False)

    def _accept(self) -> None:
        it = self.list.currentItem()
        if not it:
            return
        self.selected = it.data(Qt.ItemDataRole.UserRole)
        self.accept()

    @property
    def auto_connect(self) -> bool:
        return self.cb_auto.isChecked()
