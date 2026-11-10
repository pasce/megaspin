"""Library scanning (Desktop_App_Design §9.5 / §10.1)."""
from __future__ import annotations
from ..i18n import tr

import logging
import threading

from PySide6.QtCore import QObject, Signal

from ..data.db import Database
from ..protocol.service import ChangerService
from ..protocol.session import ChangerError

log = logging.getLogger(__name__)


def quick_scan(svc: ChangerService, db: Database, *, only_new: bool = False, slots: list[int] | None = None,
               progress=lambda done, total, text: None, cancel: threading.Event | None = None) -> int:
    """Slot list + memory titles, music type and user files. No mechanics."""
    progress(0, 0, tr("Reading occupied slots …"))
    present = svc.read_slot_list()
    if not present:
        # the changer answers with an empty list while it is busy (door open, disc detection);
        # an empty changer is practically impossible -> never mark the whole library as absent
        raise ChangerError("EMPTY_SLOT_LIST", tr("Changer busy – slot list empty, please try again later"))
    new = db.set_present_slots({s.disc: (s.title, s.attr) for s in present})
    try:
        db.save_user_file_names(svc.read_user_file_names())
    except Exception:
        log.exception("user file names")
    all_slots = [s.disc for s in present]
    todo = new if only_new else [s for s in (slots or all_slots) if s in all_slots]
    for i, slot in enumerate(todo):
        if cancel and cancel.is_set():
            break
        progress(i, len(todo), tr("Reading disc {0} …").format(slot))
        texts, mt, uf = svc.read_memory(slot)
        db.save_memory(slot, texts, mt, uf)
    progress(len(todo), len(todo), tr("Done"))
    return len(todo)


def store_disc_read(db: Database, r) -> bool:
    """Returns True if a different disc than before was found in the slot."""
    swapped = bool(r.toc) and db.save_toc(r.disc, r.toc)
    db.save_memory(r.disc, r.texts, r.music_type, r.user_files)
    return swapped


def full_scan(svc: ChangerService, db: Database, slots: list[int], *,
              progress=lambda done, total, text: None, cancel: threading.Event | None = None,
              log_line=lambda text: None, disc_done=lambda slot: None) -> tuple[int, list[int]]:
    """Load each disc (no playback), read TOC, CD-TEXT, MT, UF. Returns (done, failed slots)."""
    previous = svc.status.loaded_disc
    done, failed = 0, []
    for i, slot in enumerate(slots):
        if cancel and cancel.is_set():
            log_line(tr("Cancelled."))
            break
        progress(i, len(slots), tr("Disc {0} …").format(slot))
        try:
            r = svc.read_disc_full(slot, progress=lambda m, s=slot, i=i: progress(i, len(slots), tr("Disc {0}: {1}").format(s, m)))
            swapped = store_disc_read(db, r)
            done += 1
            src = {"cdtext": "CD-TEXT", "memory": tr("changer memory")}.get(r.text_source, tr("no titles"))
            log_line(tr("Disc {0}: {1} tracks, titles from {2}").format(
                         slot, r.toc.track_count if r.toc else "?", src)
                     + (tr(" – different CD than before, old data discarded") if swapped else ""))
            disc_done(slot)
        except ChangerError as e:
            failed.append(slot)
            log_line(tr("Disc {0}: error ({1})").format(slot, e.code))
            log.warning("full scan disc %s failed: %s", slot, e)
    if previous and svc.status.loaded_disc != previous and not (cancel and cancel.is_set()):
        progress(len(slots), len(slots), tr("Reloading disc {0} …").format(previous))
        try:
            svc.load(previous)
        except ChangerError:
            pass
    progress(len(slots), len(slots), tr("Done"))
    return done, failed


def store_loaded_disc(svc: ChangerService, db: Database, disc: int) -> bool:
    """TOC + CD-TEXT of the loaded disc (no mechanics, does not disturb playback).
    Returns True if a different disc than before was found in the slot."""
    toc = svc.read_toc(disc)
    swapped = bool(toc) and db.save_toc(disc, toc)
    texts = svc.read_texts(disc)
    if any(e.source == "cdtext" for e in texts):
        db.save_cdtext(disc, texts)
    if swapped:
        try:
            db.save_memory(disc, [e for e in texts if e.source == "memory"],
                           svc.read_music_type(disc), svc.read_user_files(disc))
        except Exception:
            log.exception("memory after swap")
    return swapped


class ScanManager(QObject):
    progress = Signal(int, int, str)
    logLine = Signal(str)
    finished = Signal(bool, str)
    libraryChanged = Signal()
    started = Signal(str)          # "quick" | "full"
    discRead = Signal(int)         # a disc got a (new) TOC -> metadata lookup can start right away
    discSwapped = Signal(int)      # a different CD than before was found in this slot

    def __init__(self, backend, db: Database, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.backend, self.db = backend, db
        self._cancel = threading.Event()
        self.running = False
        self.mode = ""
        self._queue: list[tuple[str, object, object]] = []

    @property
    def busy(self) -> bool:
        return self.running or bool(self._queue)

    def _start(self, mode: str, work_fn, summary) -> bool:
        """Start now, or queue behind the running job. Returns False only if not connected."""
        if not self.backend.svc:
            return False
        if self.running:
            self._queue.append((mode, work_fn, summary))
            self.logLine.emit("In Warteschlange: " + ("vollständiges" if mode == "full" else "schnelles")
                              + " Einlesen")
            return True
        self.running, self.mode = True, mode
        self._cancel.clear()
        self.started.emit(mode)

        def done(ok, res):
            self.running, self.mode = False, ""
            self.libraryChanged.emit()
            self.finished.emit(ok, summary(res) if ok else str(res))
            if self._queue and self.backend.svc:
                self._start(*self._queue.pop(0))
        self.backend.call(work_fn, done)
        return True

    def quick(self, only_new: bool = False, slots: list[int] | None = None) -> bool:
        return self._start(
            "quick",
            lambda svc: quick_scan(svc, self.db, only_new=only_new, slots=slots, cancel=self._cancel,
                                   progress=lambda d, t, s: self.progress.emit(d, t, s)),
            lambda n: tr("{0} disc(s) read quickly").format(n))

    def full(self, slots: list[int], fresh: bool = False, keep_user: bool = True) -> bool:
        """fresh=True ('Alles neu'): forget stored TOC/CD-TEXT/MusicBrainz/cover first."""
        def work(svc):
            if fresh:
                self.db.reset_discs(slots, keep_user=keep_user)
                self.libraryChanged.emit()
            res = full_scan(svc, self.db, slots, cancel=self._cancel,
                            progress=lambda d, t, s: self.progress.emit(d, t, s),
                            log_line=lambda t: (self.logLine.emit(t), self.libraryChanged.emit()),
                            disc_done=self.discRead.emit)
            return res

        def summary(res):
            n, failed = res
            return tr("{0} disc(s) fully read").format(n) + (tr(", errors for {0}").format(failed) if failed else "")
        return self._start("full", work, summary)

    def cancel(self) -> None:
        self._queue.clear()
        self._cancel.set()

    def loaded_disc(self, disc: int) -> None:
        if not disc or not self.backend.svc or self.mode == "full":
            return

        def done(ok, swapped):
            if ok:
                if swapped:
                    self.discSwapped.emit(disc)
                self.discRead.emit(disc)
                self.libraryChanged.emit()
        self.backend.call(lambda svc: store_loaded_disc(svc, self.db, disc), done)
