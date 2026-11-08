"""Import data of the original program (…\\CD Changer Controller\\data\\), Desktop_App_Design §5.4.

Files (PROT §11.6):
  discdata.txt   TOC_<n> / TRACKi = |MM|SS|FF / DISCID<n> / MINMAXTNO_<n> / INFO_<n> / UFILE_<n> / MTYPE_<n>
  DISC<n>.txt    DISC ID = / DISC NO = / MIN TNO = / MAX TNO = / Disc Title = / Track Title = + one line per track
  ufn.txt        8 user file names
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..protocol.parsers import split_artist_album
from .db import Database

ENCODING = "cp1252"


@dataclass
class ImportResult:
    tocs: int = 0
    titles: int = 0
    user_files: int = 0
    slots: set[int] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)


def _read(path: Path) -> list[str]:
    return path.read_text(encoding=ENCODING, errors="replace").splitlines()


def parse_discdata(path: Path) -> dict[int, dict]:
    """{slot: {"toc": [(m,s,f)...] incl. lead-out, "mtype": int, "ufile": int}}"""
    out: dict[int, dict] = {}
    lines = [l.strip() for l in _read(path)]
    i, section, slot = 0, None, None
    while i < len(lines):
        l = lines[i]
        m = re.match(r"^(TOC_|MINMAXTNO_|INFO_|UFILE_|MTYPE_|DISCID)(\d+)$", l)
        if m:
            section, slot = m.group(1), int(m.group(2))
            out.setdefault(slot, {"toc": []})
            if section in ("UFILE_", "MTYPE_", "INFO_") and i + 1 < len(lines) and lines[i + 1].isdigit():
                out[slot][section.strip("_").lower()] = int(lines[i + 1])
                i += 1
        elif section == "TOC_" and l.startswith("TRACK"):
            parts = [p for p in l.split("=", 1)[1].split("|") if p.strip() != ""]
            if len(parts) >= 3:
                out[slot]["toc"].append(tuple(int(p) for p in parts[:3]))
        i += 1
    return out


def parse_disc_file(path: Path) -> tuple[int | None, str | None, list[str]]:
    """(slot, disc title, track titles)"""
    lines = _read(path)
    slot, title, tracks = None, None, []
    mode = None
    for idx, raw in enumerate(lines):
        l = raw.rstrip()
        key = l.strip()
        if key == "DISC NO =":
            mode = "no"
            continue
        if key == "Disc Title =":
            mode = "title"
            continue
        if key == "Track Title =":
            mode = "tracks"
            continue
        if key.endswith("=") and key.isupper():
            mode = None
            continue
        if mode == "no":
            slot = int(key) if key.isdigit() else slot
            mode = None
        elif mode == "title":
            title = l.strip() or None
            mode = None
        elif mode == "tracks":
            tracks.append(l.strip())
    while tracks and not tracks[-1]:
        tracks.pop()
    return slot, title, tracks


def parse_ufn(path: Path) -> list[str]:
    """ufn.txt is a VB6 binary file: per name a 16-bit length + text, padded with NUL bytes."""
    data = path.read_bytes()
    names = []
    for chunk in re.findall(rb"[^\x00]+", data):
        txt = chunk.decode(ENCODING, errors="replace")
        txt = "".join(ch for ch in txt if ch >= " ").strip()
        if txt:
            names.append(txt)
    return names[:8]


def import_folder(folder: Path | str, db: Database) -> ImportResult:
    folder = Path(folder)
    res = ImportResult()
    dd = folder / "discdata.txt"
    if dd.exists():
        for slot, d in parse_discdata(dd).items():
            toc = d.get("toc") or []
            if len(toc) >= 2 and db.import_toc(slot, toc[:-1], toc[-1]):
                res.tocs += 1
                res.slots.add(slot)
    for f in sorted(folder.glob("DISC*.txt")):
        if not re.match(r"^DISC\d+\.txt$", f.name, re.I):
            continue
        slot, title, tracks = parse_disc_file(f)
        if not slot:
            continue
        src = db.source_titles(slot)
        d0 = (src or {}).get("disc") or {}
        user_artist = user_album = None
        if title:
            a, b = split_artist_album(title)
            if not a and not b:
                b = title
            same = lambda x, y: (x or "").strip().lower() == (y or "").strip().lower()
            ca, cb = split_artist_album(d0.get("cdtext_album"))
            if not ((same(a, ca) and same(b, cb))
                    or (same(a, d0.get("mb_artist")) and same(b, d0.get("mb_album")))):
                user_artist, user_album = a, b
        track_titles: dict[int, str | None] = {}
        srct = (src or {}).get("tracks", {})
        for no, t in enumerate(tracks, 1):
            if not t:
                continue
            known = srct.get(no, {})
            if t.strip().lower() not in {(known.get("cdtext_title") or "").strip().lower(),
                                         (known.get("mb_title") or "").strip().lower()}:
                track_titles[no] = t
        if user_artist or user_album or track_titles:
            d = (src or {}).get("disc") or {}
            db.save_user(slot, artist=user_artist or d.get("user_artist"), album=user_album or d.get("user_album"),
                         year=d.get("user_year"), music_type=d.get("user_mt"), user_files=d.get("user_uf"),
                         tracks=track_titles)
            res.titles += 1
            res.slots.add(slot)
            res.messages.append(f"Disc {slot}: eigene Titel übernommen ({len(track_titles)} Tracks)")
    ufn = folder / "ufn.txt"
    if ufn.exists():
        upd = {n: name for n, name in enumerate(parse_ufn(ufn), 1)
               if name and not re.fullmatch(r"USER ?FILE ?\d", name, re.I)}
        if upd:
            db.set_user_file_names(upd)
            res.user_files = len(upd)
    return res
