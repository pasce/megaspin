"""Start the desktop application: python -m megaspin [--sim] [--port COM4]"""
from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    ap = argparse.ArgumentParser(prog="megaspin")
    ap.add_argument("--port", help="serial port to connect to (overrides settings)")
    ap.add_argument("--sim", action="store_true", help="connect to the built-in simulator")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format=fmt)
    try:                                  # rotating log file next to the library (helps with diagnosis)
        from logging.handlers import RotatingFileHandler
        from .app.settings import data_dir
        fh = RotatingFileHandler(data_dir() / "megaspin.log", maxBytes=2_000_000, backupCount=2,
                                 encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))
        fh.setLevel(logging.INFO)
        logging.getLogger().addHandler(fh)
    except Exception:
        pass

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .app.settings import Settings
    from .backend.serial_backend import SIM_TARGET
    from .ui.main_window import MainWindow
    from .ui.theme import stylesheet

    app = QApplication(sys.argv)
    from PySide6.QtCore import Qt
    app.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, False)     # no flicker when combo boxes open
    app.setApplicationName("MegaSpin")
    app.setOrganizationName("megaspin")
    settings = Settings.load()
    app.setStyleSheet(stylesheet(settings.accent))
    win = MainWindow(settings)
    win.show()
    if args.sim:
        QTimer.singleShot(100, lambda: win.connect_to(SIM_TARGET))
    elif args.port:
        QTimer.singleShot(100, lambda: win.connect_to(args.port))
    else:
        QTimer.singleShot(100, win.auto_connect)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
