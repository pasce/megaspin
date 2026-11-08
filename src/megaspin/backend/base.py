"""Backend interface used by the UI (Desktop_App_Design §3.2).

Version 1: SerialBackend (direct RS-232). Later: NetworkBackend (M5Stack bridge).
All commands are asynchronous; results arrive via signals or callbacks in the GUI thread.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], done: Callable[[bool, Any], None]) -> None:
        super().__init__()
        self.fn, self.done = fn, done

    @Slot()
    def run(self) -> None:
        try:
            res = self.fn()
            ok = True
        except Exception as e:      # delivered to GUI thread as error
            res, ok = e, False
        self.done(ok, res)


class ChangerBackend(QObject):
    connectionChanged = Signal(bool, str)        # online, model/description
    statusChanged = Signal(dict, list)           # full status dict, changed field names
    rawData = Signal(str, bytes, float)          # "RX"/"TX", data, unix time
    error = Signal(str, str)                     # code, message
    _result = Signal(object, bool, object)       # internal: callback, ok, result

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self._result.connect(self._deliver)

    # -- helpers ---------------------------------------------------------------------------
    def run_async(self, fn: Callable[[], Any], callback: Callable[[bool, Any], None] | None = None,
                  report_errors: bool = True) -> None:
        def done(ok: bool, res: Any) -> None:
            self._result.emit((callback, report_errors), ok, res)
        self.pool.start(_Task(fn, done))

    @Slot(object, bool, object)
    def _deliver(self, cb_info, ok: bool, res) -> None:
        callback, report = cb_info
        if not ok and report:
            self.error.emit(getattr(res, "code", type(res).__name__), str(res))
        if callback:
            callback(ok, res)

    # -- interface (implemented by subclasses) --------------------------------------------
    @property
    def connected(self) -> bool: ...
    def connect_to(self, target: str, callback=None) -> None: ...
    def disconnect_from(self) -> None: ...
    def status(self) -> dict: ...
    def play(self, disc: int, track: int = 1) -> None: ...
    def load(self, disc: int) -> None: ...
    def key(self, name: str, action: str = "tap") -> None: ...
    def reset_mode(self) -> None: ...
    def resync(self) -> None: ...
