"""Local library database (SQLite), Desktop_App_Design §5."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..protocol.constants import MEMORY_MAX_TRACKS
from .names import nice_case
from ..protocol.parsers import TextEntry, Toc, split_artist_album

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS disc (
  slot INTEGER PRIMARY KEY, present INTEGER NOT NULL DEFAULT 0, attr INTEGER,
  first_track INTEGER, last_track INTEGER, toc_json TEXT, freedb_id TEXT,
  changer_title TEXT, changer_mt INTEGER, changer_uf INTEGER,
  cdtext_album TEXT,
  mb_release_id TEXT, mb_group_id TEXT, mb_artist TEXT, mb_album TEXT, mb_year INTEGER,
  mb_match_status TEXT,
  user_artist TEXT, user_album TEXT, user_year INTEGER, user_mt INTEGER, user_uf INTEGER,
  cover_source TEXT, cover_path TEXT,
  updated_at REAL, memory_read_at REAL, toc_read_at REAL, cdtext_read_at REAL, mb_read_at REAL,
  last_played_at REAL
);
CREATE TABLE IF NOT EXISTS track (
  slot INTEGER, no INTEGER, length_s INTEGER,
  changer_title TEXT, cdtext_title TEXT, mb_title TEXT, user_title TEXT,
  PRIMARY KEY (slot, no)
);
CREATE TABLE IF NOT EXISTS user_file (no INTEGER PRIMARY KEY, name TEXT, changer_name TEXT);
CREATE TABLE IF NOT EXISTS playlist (id INTEGER PRIMARY KEY, name TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS playlist_item (playlist_id INTEGER, pos INTEGER, slot INTEGER, track INTEGER,
  PRIMARY KEY (playlist_id, pos));
CREATE TABLE IF NOT EXISTS mb_candidate (slot INTEGER, release_id TEXT, score REAL, json TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class Track:
    no: int
    title: str
    source: str
    length_s: int | None


@dataclass
class Album:
    slot: int
    present: bool
    artist: str | None
    album: str | None
    year: int | None
    music_type: int
    user_files: int
    track_count: int | None
    duration_s: int | None
    has_toc: bool
    has_cdtext: bool
    title_source: str           # user | musicbrainz | cdtext | memory | none
    cover_path: str | None
    attr: int | None
    mb_status: str | None = None
    last_played_at: float | None = None
    tracks: list[Track] = field(default_factory=list)

    @property
    def display_album(self) -> str:
        return self.album or f"Disc {self.slot}"

    @property
    def display_artist(self) -> str:
        return self.artist or ("Unbekannter Interpret" if self.album else "")

    @property
    def complete(self) -> bool:
        """Everything readable from the changer has been read (TOC; CD-TEXT comes with it)."""
        return self.has_toc


def _first(*vals):
    for v in vals:
        if v not in (None, ""):
            return v
    return None


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock, self.conn:
            self.conn.executescript(SCHEMA)
            self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _ensure(self, slot: int) -> None:
        self.conn.execute("INSERT OR IGNORE INTO disc (slot, present, updated_at) VALUES (?, 0, ?)",
                          (slot, time.time()))

    # ------------------------------------------------------------------ writes from the changer
    def set_present_slots(self, slots: dict[int, tuple[str | None, int]]) -> list[int]:
        """slots: {slot: (memory disc title, attr)}. Returns slots that are new in the DB."""
        now = time.time()
        with self._lock, self.conn:
            known = {r[0] for r in self.conn.execute("SELECT slot FROM disc WHERE memory_read_at IS NOT NULL")}
            self.conn.execute("UPDATE disc SET present = 0")
            for slot, (title, attr) in slots.items():
                self._ensure(slot)
                self.conn.execute("UPDATE disc SET present=1, changer_title=?, attr=?, updated_at=? WHERE slot=?",
                                  (title, attr, now, slot))
        return sorted(s for s in slots if s not in known)

    def save_memory(self, slot: int, texts: list[TextEntry], music_type: int, user_files: int) -> None:
        now = time.time()
        with self._lock, self.conn:
            self._ensure(slot)
            mem = [e for e in texts if e.source == "memory"]
            cd = [e for e in texts if e.source == "cdtext"]
            if mem:
                title = next((e.text for e in mem if e.track == 0), None)
                self.conn.execute("UPDATE disc SET changer_title=?, memory_read_at=? WHERE slot=?",
                                  (title, now, slot))
                for e in mem:
                    if 1 <= e.track <= MEMORY_MAX_TRACKS:
                        if e.text:
                            self._upsert_track(slot, e.track, changer_title=e.text)
                        else:
                            self.conn.execute("UPDATE track SET changer_title=NULL WHERE slot=? AND no=?",
                                              (slot, e.track))
            if cd:
                self._save_cdtext(slot, cd)
            self.conn.execute("UPDATE disc SET changer_mt=?, changer_uf=?, updated_at=?, "
                              "memory_read_at=COALESCE(memory_read_at, ?) WHERE slot=?",
                              (music_type, user_files, now, now, slot))

    def save_cdtext(self, slot: int, texts: list[TextEntry]) -> None:
        with self._lock, self.conn:
            self._ensure(slot)
            self._save_cdtext(slot, [e for e in texts if e.source == "cdtext"])

    def _save_cdtext(self, slot: int, cd: list[TextEntry]) -> None:
        if not cd:
            return
        album = next((e.text for e in cd if e.track == 0), None)
        self.conn.execute("UPDATE disc SET cdtext_album=?, cdtext_read_at=?, updated_at=? WHERE slot=?",
                          (album, time.time(), time.time(), slot))
        for e in cd:
            if e.track >= 1:
                self._upsert_track(slot, e.track, cdtext_title=e.text)

    def save_toc(self, slot: int, toc: Toc) -> bool:
        """Store the TOC. Returns True if a *different* disc was found in this slot (the changer itself
        does not notice a swapped disc); all data of the old disc is discarded then."""
        swapped = False
        with self._lock, self.conn:
            self._ensure(slot)
            old = self.conn.execute("SELECT freedb_id FROM disc WHERE slot=?", (slot,)).fetchone()[0]
            if old and old != toc.freedb_id():
                self._reset(slot, keep_user=False, keep_memory=False)
                swapped = True
            data = [list(x) for x in toc.starts] + [list(toc.leadout)]
            self.conn.execute("UPDATE disc SET first_track=?, last_track=?, toc_json=?, freedb_id=?, attr=?, "
                              "toc_read_at=?, updated_at=? WHERE slot=?",
                              (toc.first, toc.last, json.dumps(data), toc.freedb_id(), toc.attr,
                               time.time(), time.time(), slot))
            for i, length in enumerate(toc.lengths()):
                self._upsert_track(slot, toc.first + i, length_s=length)
            self.conn.execute("DELETE FROM track WHERE slot=? AND no>? AND user_title IS NULL "
                              "AND cdtext_title IS NULL AND mb_title IS NULL", (slot, toc.last))
        return swapped

    def reset_discs(self, slots: list[int], keep_user: bool = True) -> None:
        """'Alles neu': forget TOC, CD-TEXT, MusicBrainz data and downloaded covers."""
        with self._lock, self.conn:
            for slot in slots:
                self._reset(slot, keep_user=keep_user, keep_memory=True)

    def _reset(self, slot: int, keep_user: bool, keep_memory: bool) -> None:
        c = self.conn
        c.execute("UPDATE disc SET first_track=NULL, last_track=NULL, toc_json=NULL, freedb_id=NULL, "
                  "toc_read_at=NULL, cdtext_album=NULL, cdtext_read_at=NULL, mb_release_id=NULL, "
                  "mb_group_id=NULL, mb_artist=NULL, mb_album=NULL, mb_year=NULL, mb_match_status=NULL, "
                  "mb_read_at=NULL, updated_at=? WHERE slot=?", (time.time(), slot))
        row = c.execute("SELECT cover_source FROM disc WHERE slot=?", (slot,)).fetchone()
        if not (keep_user and row and row[0] == "user"):
            c.execute("UPDATE disc SET cover_path=NULL, cover_source=NULL WHERE slot=?", (slot,))
        if not keep_user:
            c.execute("UPDATE disc SET user_artist=NULL, user_album=NULL, user_year=NULL, user_mt=NULL, "
                      "user_uf=NULL WHERE slot=?", (slot,))
        if not keep_memory:
            c.execute("UPDATE disc SET changer_title=NULL, memory_read_at=NULL WHERE slot=?", (slot,))
        c.execute("DELETE FROM mb_candidate WHERE slot=?", (slot,))
        c.execute("UPDATE track SET length_s=NULL, cdtext_title=NULL, mb_title=NULL"
                  + ("" if keep_user else ", user_title=NULL")
                  + ("" if keep_memory else ", changer_title=NULL") + " WHERE slot=?", (slot,))
        c.execute("DELETE FROM track WHERE slot=? AND changer_title IS NULL AND user_title IS NULL", (slot,))

    def _upsert_track(self, slot: int, no: int, **cols) -> None:
        self.conn.execute("INSERT OR IGNORE INTO track (slot, no) VALUES (?, ?)", (slot, no))
        sets = ", ".join(f"{k}=?" for k in cols)
        self.conn.execute(f"UPDATE track SET {sets} WHERE slot=? AND no=?", (*cols.values(), slot, no))

    def save_user_file_names(self, names: dict[int, str | None]) -> None:
        with self._lock, self.conn:
            for no, name in names.items():
                self.conn.execute("INSERT INTO user_file (no, changer_name) VALUES (?, ?) "
                                  "ON CONFLICT(no) DO UPDATE SET changer_name=excluded.changer_name", (no, name))

    def toc(self, slot: int):
        """Rebuild a Toc object from the stored TOC (or None)."""
        with self._lock:
            r = self.conn.execute("SELECT first_track, last_track, toc_json, attr FROM disc WHERE slot=?",
                                  (slot,)).fetchone()
        if not r or not r["toc_json"]:
            return None
        data = [tuple(x) for x in json.loads(r["toc_json"])]
        return Toc(slot, 1, r["attr"] or 0, r["first_track"], r["last_track"], data[:-1], data[-1])

    def needs_metadata(self) -> list[int]:
        with self._lock:
            return [r[0] for r in self.conn.execute(
                "SELECT slot FROM disc WHERE present=1 AND toc_json IS NOT NULL AND mb_read_at IS NULL "
                "AND (mb_match_status IS NULL OR mb_match_status NOT IN ('manual','none_selected')) ORDER BY slot")]

    def needs_cover(self) -> list[tuple[int, str, str | None]]:
        """Matched discs without a cover (e.g. Cover Art Archive was temporarily unavailable)."""
        with self._lock:
            return [(r[0], r[1], r[2]) for r in self.conn.execute(
                "SELECT slot, mb_release_id, mb_group_id FROM disc WHERE present=1 AND mb_release_id IS NOT NULL "
                "AND cover_path IS NULL AND (cover_source IS NULL OR cover_source='caa')")]

    def save_musicbrainz(self, slot: int, cand, status: str) -> None:
        with self._lock, self.conn:
            if cand is None:
                self.conn.execute("UPDATE disc SET mb_match_status=?, mb_read_at=?, updated_at=? WHERE slot=?",
                                  (status, time.time(), time.time(), slot))
                if status == "none_selected":
                    self.conn.execute("UPDATE disc SET mb_release_id=NULL, mb_group_id=NULL, mb_artist=NULL, "
                                      "mb_album=NULL, mb_year=NULL WHERE slot=?", (slot,))
                    self.conn.execute("UPDATE track SET mb_title=NULL WHERE slot=?", (slot,))
                return
            self.conn.execute("UPDATE disc SET mb_release_id=?, mb_group_id=?, mb_artist=?, mb_album=?, mb_year=?, "
                              "mb_match_status=?, mb_read_at=?, updated_at=? WHERE slot=?",
                              (cand.release_id, cand.group_id, cand.artist, cand.title, cand.year, status,
                               time.time(), time.time(), slot))
            for i, (title, _len) in enumerate(cand.tracks):
                self._upsert_track(slot, i + 1, mb_title=title)

    def save_candidates(self, slot: int, cands: list) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM mb_candidate WHERE slot=?", (slot,))
            for c in cands[:25]:
                self.conn.execute("INSERT INTO mb_candidate VALUES (?, ?, ?, ?)",
                                  (slot, c.release_id, c.score, c.to_json()))

    def candidates(self, slot: int) -> list:
        from ..metadata.musicbrainz import Candidate
        with self._lock:
            rows = self.conn.execute("SELECT json FROM mb_candidate WHERE slot=? ORDER BY score DESC",
                                     (slot,)).fetchall()
        return [Candidate.from_json(r[0]) for r in rows]

    def set_cover(self, slot: int, path: str | None, source: str) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE disc SET cover_path=?, cover_source=?, updated_at=? WHERE slot=?",
                              (path, source, time.time(), slot))

    def disc_row(self, slot: int) -> dict:
        with self._lock:
            r = self.conn.execute("SELECT * FROM disc WHERE slot=?", (slot,)).fetchone()
        return dict(r) if r else {}

    def save_user(self, slot: int, *, artist: str | None, album: str | None, year: int | None,
                  music_type: int | None, user_files: int | None, tracks: dict[int, str | None]) -> None:
        """User edits (never overwritten automatically). None/'' clears a field."""
        with self._lock, self.conn:
            self._ensure(slot)
            self.conn.execute("UPDATE disc SET user_artist=?, user_album=?, user_year=?, user_mt=?, user_uf=?, "
                              "updated_at=? WHERE slot=?",
                              (artist or None, album or None, year, music_type, user_files, time.time(), slot))
            for no, title in tracks.items():
                self._upsert_track(slot, no, user_title=title or None)

    def source_titles(self, slot: int) -> dict:
        """All title sources of a disc (for the edit dialog)."""
        with self._lock:
            d = self.conn.execute("SELECT * FROM disc WHERE slot=?", (slot,)).fetchone()
            t = self.conn.execute("SELECT * FROM track WHERE slot=? ORDER BY no", (slot,)).fetchall()
        if not d:
            return {}
        return {"disc": dict(d), "tracks": {r["no"]: dict(r) for r in t}}

    def set_user_file_names(self, names: dict[int, str | None]) -> None:
        with self._lock, self.conn:
            for no, name in names.items():
                self.conn.execute("INSERT INTO user_file (no, name) VALUES (?, ?) "
                                  "ON CONFLICT(no) DO UPDATE SET name=excluded.name", (no, name or None))

    def import_toc(self, slot: int, starts: list[tuple[int, int, int]], leadout: tuple[int, int, int]) -> bool:
        """TOC from the original program's discdata.txt (only if none stored yet)."""
        if self.toc(slot) is not None or not starts:
            return False
        self.save_toc(slot, Toc(slot, 1, 0, 1, len(starts), starts, leadout))
        return True

    def mark_played(self, slot: int) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE disc SET last_played_at=? WHERE slot=?", (time.time(), slot))

    # ------------------------------------------------------------------ reads
    def user_file_names(self) -> dict[int, str]:
        with self._lock:
            rows = {r["no"]: r for r in self.conn.execute("SELECT * FROM user_file")}
        def changer(n):            # the changer's default "USER FILE n" counts as "no name"
            v = rows[n]["changer_name"] if n in rows else None
            return None if v and re.fullmatch(r"USER ?FILE ?\d", v.strip(), re.I) else v
        return {n: (_first(rows[n]["name"] if n in rows else None, changer(n))) or f"User File {n}"
                for n in range(1, 9)}

    def disc_count(self) -> int:
        """All known discs, also those currently not in the changer."""
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM disc").fetchone()[0]

    # ------------------------------------------------------------------ playlists (track 0 = whole disc)
    def playlists(self) -> list[tuple[int, str, int]]:
        with self._lock:
            return [(r[0], r[1], r[2]) for r in self.conn.execute(
                "SELECT p.id, p.name, COUNT(i.pos) FROM playlist p LEFT JOIN playlist_item i "
                "ON i.playlist_id = p.id GROUP BY p.id ORDER BY lower(p.name)")]

    def create_playlist(self, name: str) -> int:
        with self._lock, self.conn:
            return self.conn.execute("INSERT INTO playlist (name, created_at) VALUES (?, ?)",
                                     (name, time.time())).lastrowid

    def rename_playlist(self, pid: int, name: str) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE playlist SET name=? WHERE id=?", (name, pid))

    def delete_playlist(self, pid: int) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM playlist_item WHERE playlist_id=?", (pid,))
            self.conn.execute("DELETE FROM playlist WHERE id=?", (pid,))

    def playlist_name(self, pid: int) -> str | None:
        with self._lock:
            r = self.conn.execute("SELECT name FROM playlist WHERE id=?", (pid,)).fetchone()
        return r[0] if r else None

    def playlist_items(self, pid: int) -> list[tuple[int, int]]:
        with self._lock:
            return [(r[0], r[1]) for r in self.conn.execute(
                "SELECT slot, track FROM playlist_item WHERE playlist_id=? ORDER BY pos", (pid,))]

    def set_playlist_items(self, pid: int, items: list[tuple[int, int]]) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM playlist_item WHERE playlist_id=?", (pid,))
            self.conn.executemany("INSERT INTO playlist_item (playlist_id, pos, slot, track) VALUES (?, ?, ?, ?)",
                                  [(pid, i, s, t) for i, (s, t) in enumerate(items)])

    def add_playlist_items(self, pid: int, items: list[tuple[int, int]]) -> None:
        self.set_playlist_items(pid, self.playlist_items(pid) + list(items))

    def present_slots(self) -> list[int]:
        with self._lock:
            return [r[0] for r in self.conn.execute("SELECT slot FROM disc WHERE present=1 ORDER BY slot")]

    def slot_count(self) -> int:
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM disc WHERE present=1").fetchone()[0]

    def albums(self, include_absent: bool = False) -> list[Album]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM disc" + ("" if include_absent else " WHERE present=1")
                                     + " ORDER BY slot").fetchall()
            tracks = self.conn.execute("SELECT slot, COUNT(*) AS n, SUM(length_s) AS d, "
                                       "SUM(cdtext_title IS NOT NULL) AS c FROM track GROUP BY slot").fetchall()
        tinfo = {r["slot"]: r for r in tracks}
        return [self._album(r, tinfo.get(r["slot"])) for r in rows]

    def album(self, slot: int) -> Album | None:
        with self._lock:
            r = self.conn.execute("SELECT * FROM disc WHERE slot=?", (slot,)).fetchone()
            if not r:
                return None
            trows = self.conn.execute("SELECT * FROM track WHERE slot=? ORDER BY no", (slot,)).fetchall()
        a = self._album(r, None)
        last = r["last_track"]
        for t in trows:
            if last and t["no"] > last and not t["user_title"]:
                continue
            title, src = None, "none"
            for col, s in (("user_title", "user"), ("mb_title", "musicbrainz"),
                           ("cdtext_title", "cdtext"), ("changer_title", "memory")):
                if t[col]:
                    title, src = (t[col] if s in ("user", "musicbrainz") else nice_case(t[col])), s
                    break
            a.tracks.append(Track(t["no"], title or f"Track {t['no']}", src, t["length_s"]))
        if last and not trows:
            a.tracks = [Track(n, f"Track {n}", "none", None) for n in range(1, last + 1)]
        a.track_count = last or (len(a.tracks) if a.has_toc else None)
        return a

    def _album(self, r: sqlite3.Row, tinfo) -> Album:
        cd_artist, cd_album = (nice_case(x) for x in split_artist_album(r["cdtext_album"]))
        mem_artist, mem_album = (nice_case(x) for x in split_artist_album(r["changer_title"]))
        artist = _first(r["user_artist"], r["mb_artist"], cd_artist, mem_artist)
        album = _first(r["user_album"], r["mb_album"], cd_album, mem_album)
        if r["user_album"] or r["user_artist"]:
            src = "user"
        elif r["mb_album"]:
            src = "musicbrainz"
        elif r["cdtext_album"]:
            src = "cdtext"
        elif r["changer_title"]:
            src = "memory"
        else:
            src = "none"
        has_toc = r["toc_json"] is not None
        duration = None
        if has_toc:
            toc = json.loads(r["toc_json"])
            duration = (toc[-1][0] * 60 + toc[-1][1]) - (toc[0][0] * 60 + toc[0][1])
        mt = _first(r["user_mt"], r["changer_mt"]) or 0
        uf = _first(r["user_uf"], r["changer_uf"]) or 0
        return Album(slot=r["slot"], present=bool(r["present"]), artist=artist, album=album,
                     year=_first(r["user_year"], r["mb_year"]), music_type=mt, user_files=uf,
                     track_count=r["last_track"], duration_s=duration, has_toc=has_toc,
                     has_cdtext=bool(r["cdtext_album"]) or bool(tinfo and tinfo["c"]),
                     title_source=src, cover_path=r["cover_path"], attr=r["attr"],
                     last_played_at=r["last_played_at"], mb_status=r["mb_match_status"])
