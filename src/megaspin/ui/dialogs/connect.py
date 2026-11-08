"""Connection dialog: choose port, auto-detect via Hello (Desktop_App_Design §9.1)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from ...backend.serial_backend import SIM_TARGET, list_ports, probe_port


class ConnectDialog(QDialog):
    def __init__(self, backend, current: str = "", auto_connect: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mit Wechsler verbinden")
        self.setMinimumWidth(460)
        self.backend = backend
        self.selected = ""

        lay = QVBoxLayout(self)
        title = QLabel("Serielle Schnittstelle wählen")
        title.setObjectName("Title")
        lay.addWidget(title)
        hint = QLabel("Der Wechsler wird über ein RS-232-Kabel (9600 Baud) angeschlossen.")
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.info = QLabel("")
        self.info.setObjectName("Subtitle")
        lay.addWidget(self.info)

        self.cb_auto = QCheckBox("Beim Programmstart automatisch verbinden")
        self.cb_auto.setChecked(auto_connect)
        lay.addWidget(self.cb_auto)

        row = QHBoxLayout()
        self.b_refresh = QPushButton("Aktualisieren")
        self.b_search = QPushButton("Automatisch suchen")
        self.b_ok = QPushButton("Verbinden")
        self.b_ok.setObjectName("Primary")
        self.b_ok.setDefault(True)
        b_cancel = QPushButton("Abbrechen")
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
        sim = QListWidgetItem("Simulator    (Test ohne Wechsler)")
        sim.setData(Qt.ItemDataRole.UserRole, SIM_TARGET)
        self.list.addItem(sim)
        if current == SIM_TARGET:
            self.list.setCurrentItem(sim)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self.info.setText(f"{self.list.count() - 1} serielle Schnittstelle(n) gefunden.")

    def _search(self) -> None:
        ports = [d for d, _ in list_ports()]
        if not ports:
            self.info.setText("Keine serielle Schnittstelle gefunden.")
            return
        self.info.setText("Suche Wechsler auf " + ", ".join(ports) + " …")
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
                self.info.setText(f"Gefunden: {model} an {dev}")
                for i in range(self.list.count()):
                    if self.list.item(i).data(Qt.ItemDataRole.UserRole) == dev:
                        self.list.setCurrentRow(i)
            else:
                self.info.setText("Kein Wechsler gefunden. Kabel, Port und Gerät prüfen "
                                  "(läuft ein anderes Programm auf dem Port?).")
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
