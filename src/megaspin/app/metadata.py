"""Background metadata service: MusicBrainz lookup + cover download (Desktop_App_Design §6)."""
from __future__ import annotations

import logging
import queue
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..data.db import Database
from ..metadata import musicbrainz as mb
from ..metadata.matcher import rank

log = logging.getLogger(__name__)


def save_cover(data: bytes, dest: Path, max_px: int = 600) -> None:
    """Store cover as JPEG, scaled down to max_px (originals can be several MB)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    img = QImage.fromData(data)
    if img.isNull():
        dest.write_bytes(data)
        return
    if max(img.width(), img.height()) > max_px:
        img = img.scaled(max_px, max_px, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    img.save(str(dest), "JPG", 90)


class MetadataService(QObject):
    discUpdated = Signal(int)               # slot
    ambiguous = Signal(int)                 # slot needs a user decision
    statusText = Signal(str)
    queueChanged = Signal(int)

    def __init__(self, db: Database, covers_dir: Path, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.covers_dir = Path(covers_dir)
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._pending: set[int] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="metadata", daemon=True)
        self._thread.start()

    @property
    def enabled(self) -> bool:
        return not self._stop.is_set() and bool(getattr(self.settings, "mb_enabled", True))

    @property
    def contact(self) -> str:
        return getattr(self.settings, "mb_contact", "") or ""

    def stop(self) -> None:
        self._stop.set()
        self._q.put(("stop",))

    # ------------------------------------------------------------------ public API
    def enqueue(self, slot: int, force: bool = False) -> None:
        if not self.enabled or slot in self._pending:
            return
        self._pending.add(slot)
        self._q.put(("lookup", slot, force))
        self.queueChanged.emit(len(self._pending))

    def enqueue_missing(self) -> None:
        if not self.enabled:
            return
        for slot in self.db.needs_metadata():
            self.enqueue(slot)
        self.enqueue_missing_covers()

    def select(self, slot: int, cand) -> None:
        """User picked a candidate (or None = 'none fits')."""
        if self._stop.is_set():
            return
        self._q.put(("select", slot, cand))

    def search(self, slot: int, query: str, callback) -> None:
        self._q.put(("search", slot, query, callback))

    def set_cover_file(self, slot: int, path: str) -> None:
        dest = self.covers_dir / f"{slot}.jpg"
        shutil.copyfile(path, dest)
        self.db.set_cover(slot, str(dest), "user")
        self.discUpdated.emit(slot)

    def remove_cover(self, slot: int) -> None:
        self.db.set_cover(slot, None, "none")
        self.discUpdated.emit(slot)

    # ------------------------------------------------------------------ worker
    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._q.get()
            if job[0] == "stop":
                return
            try:
                if job[0] == "lookup":
                    self._lookup(job[1], job[2])
                elif job[0] == "cover":
                    if self._fetch_cover(job[1], job[2], job[3]):
                        self.discUpdated.emit(job[1])
                elif job[0] == "select":
                    self._apply(job[1], job[2], "manual" if job[2] else "none_selected")
                elif job[0] == "search":
                    _, slot, query, cb = job
                    toc = self.db.toc(slot)
                    n = toc.track_count if toc else 0
                    cands = mb.search_releases(query, n, self.contact) if n else []
                    a = self.db.album(slot)
                    ranked, _ = rank(cands, toc.lengths(), a.artist, a.album,
                                     {t.no: t.title for t in a.tracks}) if toc else ([], "none")
                    cb(ranked)
            except Exception as e:
                log.warning("metadata job %s failed: %s", job[:2], e)
                self.statusText.emit(f"Metadaten: Fehler ({e.__class__.__name__}) – später erneut")
            finally:
                if job[0] == "lookup":
                    self._pending.discard(job[1])
                    self.queueChanged.emit(len(self._pending))

    def _lookup(self, slot: int, force: bool) -> None:
        row = self.db.disc_row(slot)
        if not row or (row.get("mb_match_status") in ("manual", "none_selected") and not force):
            return
        toc = self.db.toc(slot)
        if not toc:
            return
        album = self.db.album(slot)
        known_tracks = {t.no: t.title for t in album.tracks if t.source in ("cdtext", "memory", "user")}
        self.statusText.emit(f"Metadaten für Disc {slot} suchen …")
        cands = mb.lookup_toc(toc.musicbrainz_toc(), toc.track_count, self.contact)
        ranked, status = rank(cands, toc.lengths(), album.artist, album.album, known_tracks)
        self.db.save_candidates(slot, ranked)
        if status == "ok":
            self._apply(slot, ranked[0], "ok")
        else:
            self.db.save_musicbrainz(slot, None, status)       # "ambiguous" | "none"
            self.discUpdated.emit(slot)
            if status == "ambiguous":
                self.ambiguous.emit(slot)
        self.statusText.emit({"ok": f"Disc {slot}: Metadaten gefunden",
                              "ambiguous": f"Disc {slot}: mehrere Treffer – bitte auswählen",
                              "none": f"Disc {slot}: kein Treffer bei MusicBrainz"}[status])

    def _apply(self, slot: int, cand, status: str) -> None:
        self.db.save_musicbrainz(slot, cand, status)
        row = self.db.disc_row(slot)
        if cand and row.get("cover_source") != "user":
            self._fetch_cover(slot, cand.release_id, cand.group_id)
        self.discUpdated.emit(slot)

    def _fetch_cover(self, slot: int, release_id: str, group_id: str | None) -> bool:
        data = mb.fetch_cover_ids(release_id, group_id, self.contact)
        if not data:
            return False
        dest = self.covers_dir / f"{slot}.jpg"
        save_cover(data, dest)
        self.db.set_cover(slot, str(dest), "caa")
        return True

    def enqueue_missing_covers(self) -> None:
        if not self.enabled:
            return
        for slot, rid, gid in self.db.needs_cover():
            self._q.put(("cover", slot, rid, gid))
