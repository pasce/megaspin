"""SerialBackend: direct RS-232 connection via the protocol core."""
from __future__ import annotations
from ..i18n import tr

import logging
import time

from PySide6.QtCore import QObject

from ..protocol.service import ChangerService, PlayerStatus
from ..protocol.session import ChangerError
from .base import ChangerBackend

log = logging.getLogger(__name__)
SIM_TARGET = "SIMULATOR"


def list_ports() -> list[tuple[str, str]]:
    """[(device, description)] of available serial ports."""
    try:
        from serial.tools import list_ports as lp
        return [(p.device, p.description or p.device) for p in sorted(lp.comports(), key=lambda p: p.device)]
    except Exception:
        return []


def probe_port(device: str, timeout: float = 2.0) -> str | None:
    """Send Hello on a port; return the model string ("I'm CD-425M") or None."""
    from ..protocol import commands as C
    from ..protocol.codec import Ctrl, Frame, FrameParser
    from ..protocol.constants import ACK, ENQ, EOT
    from ..protocol.transport import SerialTransport
    try:
        tr = SerialTransport(device)
    except Exception:
        return None
    parser = FrameParser()
    try:
        tr.write(bytes([ENQ]))
        end = time.monotonic() + timeout
        stage = "enq"
        while time.monotonic() < end:
            for m in parser.feed(tr.read(0.05), time.monotonic()):
                if stage == "enq" and isinstance(m, Ctrl) and m.byte == ACK:
                    tr.write(C.hello())
                    stage = "frame"
                elif isinstance(m, Frame):
                    tr.write(bytes([ACK]))
                    if m.ftype == 0 and m.payload.startswith(b"I'm CD"):
                        # let the changer finish its session cleanly
                        t2 = time.monotonic() + 0.5
                        while time.monotonic() < t2:
                            for m2 in parser.feed(tr.read(0.05), time.monotonic()):
                                if isinstance(m2, Ctrl) and m2.byte == EOT:
                                    tr.write(bytes([ACK]))
                                    return m.payload.decode("ascii", "replace")
                        return m.payload.decode("ascii", "replace")
        return None
    finally:
        tr.close()


class SerialBackend(ChangerBackend):
    sim_load_delay = 2.0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.svc: ChangerService | None = None
        self.target = ""
        self._sim = None

    # ---------------------------------------------------------------- connection
    @property
    def connected(self) -> bool:
        return self.svc is not None and self.svc.status.online

    def connect_to(self, target: str, callback=None) -> None:
        self.disconnect_from()
        self.target = target

        def work():
            if target == SIM_TARGET:
                from ..protocol.transport import pipe_pair
                from ..sim.simulator import ChangerSimulator
                pc, ch = pipe_pair()
                self._sim = ChangerSimulator(ch, load_delay=self.sim_load_delay).start()
                tr = pc
            else:
                from ..protocol.transport import SerialTransport
                tr = SerialTransport(target)
            svc = ChangerService(tr, on_raw=lambda d, data, t: self.rawData.emit(d, data, t))
            svc.add_listener(self._on_status)
            self.svc = svc
            svc.start(hello=False)
            model = svc.hello()
            svc.wait_for(lambda s: s.loaded_disc != 0 and s.play_state != "unknown", 3.0)
            return model

        def done(ok, res):
            if ok and self.svc is None:            # disconnected while connecting
                ok, res = False, "getrennt"
            if ok:
                self.connectionChanged.emit(True, f"{self.svc.status.model} · {self._label()}")
                self.statusChanged.emit(self.svc.status.to_dict(), ["*"])
            else:
                self.connectionChanged.emit(False, str(res))
                self._teardown()
            if callback:
                callback(ok, res)
        self.run_async(work, done)

    def disconnect_from(self) -> None:
        was = self.svc is not None
        self._teardown()
        if was:
            self.connectionChanged.emit(False, "getrennt")

    def _teardown(self) -> None:
        svc, self.svc = self.svc, None
        if svc:
            try:
                svc.stop()
                svc.engine._tr.close()
            except Exception:
                pass
        if self._sim:
            self._sim.stop()
            self._sim = None

    def _label(self) -> str:
        return tr("Simulator") if self.target == SIM_TARGET else self.target

    def _on_status(self, st: PlayerStatus, changed: set) -> None:   # engine thread -> signal
        if "online" in changed:
            self.connectionChanged.emit(st.online, f"{st.model} · {self._label()}" if st.online
                                        else tr("Changer is not responding"))
        self.statusChanged.emit(st.to_dict(), sorted(changed))

    def status(self) -> dict:
        return self.svc.status.to_dict() if self.svc else PlayerStatus().to_dict()

    # ---------------------------------------------------------------- commands
    def _do(self, fn, callback=None) -> None:
        svc = self.svc
        if not svc:
            self.error.emit("NOT_CONNECTED", tr("No connection to the changer"))
            return
        self.run_async(lambda: fn(svc), callback)

    def play(self, disc: int, track: int = 1, callback=None) -> None:
        self._do(lambda s: s.play(disc, track), callback)

    def load(self, disc: int, callback=None) -> None:
        self._do(lambda s: s.load(disc), callback)

    def key(self, name: str, action: str = "tap", callback=None) -> None:
        self._do(lambda s: s.key(name, action), callback)

    def reset_mode(self) -> None:
        self._do(lambda s: s.reset_mode())

    def resync(self) -> None:
        self._do(lambda s: s.hello())

    def call(self, fn, callback=None) -> None:
        """Run any ChangerService method in a worker: backend.call(lambda s: s.read_toc(150), cb)."""
        self._do(fn, callback)


__all__ = ["SerialBackend", "list_ports", "probe_port", "SIM_TARGET", "ChangerError"]
