"""Write valid titles into the changer memory after reading discs (option in the "Read discs" dialog).

A disc is written when
  * its titles come from MusicBrainz (a clear or chosen match) or from the user's own entries,
  * it has no CD-TEXT (the changer replaces the memory with the CD-TEXT whenever such a disc is loaded),
  * and the changer memory differs from what would be written (titles, music type, user files).
The last rule keeps EEPROM writes to the necessary minimum. MusicBrainz data usually arrive only after a
disc was read, so every armed slot is checked again whenever its data change.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from ..data.db import Album, Database
from ..i18n import tr
from ..protocol.commands import changer_disc_title, to_changer_text
from ..protocol.constants import MEMORY_MAX_TRACKS

log = logging.getLogger(__name__)

VALID_SOURCES = ("user", "musicbrainz")


def changer_target(album: Album | None) -> dict | None:
    """What should be in the changer memory for this album, or None if nothing valid can be written."""
    if not album or not album.present or album.has_cdtext:
        return None
    if album.title_source not in VALID_SOURCES and not any(t.source in VALID_SOURCES for t in album.tracks):
        return None
    return {
        "title": changer_disc_title(album.artist or "", album.album or ""),
        "tracks": {t.no: (t.title if t.source != "none" else "") for t in album.tracks if t.no <= MEMORY_MAX_TRACKS},
        "music_type": album.music_type,
        "user_files": album.user_files,
    }


def _norm(text) -> str:
    return to_changer_text(text or "").decode("ascii").rstrip()


def differs_from_changer(target: dict, sources: dict) -> bool:
    """True if the changer memory (as last read) differs from target."""
    d = sources.get("disc", {})
    tracks = sources.get("tracks", {})
    if _norm(target["title"]) != _norm(d.get("changer_title")):
        return True
    for no, title in target["tracks"].items():
        if _norm(title) != _norm(tracks.get(no, {}).get("changer_title")):
            return True
    return target["music_type"] != (d.get("changer_mt") or 0) or target["user_files"] != (d.get("changer_uf") or 0)


class ChangerSync(QObject):
    message = Signal(str)
    written = Signal(int)

    def __init__(self, backend, db: Database, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.backend, self.db = backend, db
        self._armed: set[int] = set()
        self._busy: set[int] = set()

    def arm(self, slots: list[int]) -> None:
        """Called when a read with the option 'write valid titles' starts."""
        self._armed = set(slots)

    def disarm(self) -> None:
        self._armed.clear()

    @property
    def armed(self) -> set[int]:
        return set(self._armed)

    def check_all(self) -> None:
        for slot in sorted(self._armed):
            self.check(slot)

    def check(self, slot: int) -> None:
        if slot not in self._armed or slot in self._busy or not self.backend.connected:
            return
        album = self.db.album(slot)
        if album and album.has_cdtext:
            self._armed.discard(slot)              # never worth writing, see module doc
            return
        target = changer_target(album)
        if target is None:
            return                                 # maybe MusicBrainz data come later
        if not differs_from_changer(target, self.db.source_titles(slot)):
            self._armed.discard(slot)
            return
        self._write(slot, target)

    def _write(self, slot: int, target: dict) -> None:
        self._busy.add(slot)

        def work(svc):
            svc.write_titles(slot, target["title"], target["tracks"], target["music_type"], target["user_files"])
            texts, mt, uf = svc.read_memory(slot)          # check + update the stored changer values
            self.db.save_memory(slot, texts, mt, uf)
            return True

        def done(ok, res):
            self._busy.discard(slot)
            self._armed.discard(slot)
            if ok:
                self.message.emit(tr("Disc {0}: titles written to the changer").format(slot))
                self.written.emit(slot)
            else:
                log.warning("writing titles of disc %s failed: %s", slot, res)
                self.message.emit(tr("Disc {0}: writing to the changer failed ({1})").format(slot, res))
        self.backend.call(work, done)
