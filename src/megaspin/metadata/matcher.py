"""Candidate scoring (Middleware_Design §10.2 / Desktop_App_Design §6)."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .musicbrainz import Candidate

AUTO_MIN_SCORE = 0.6
AUTO_MIN_MARGIN = 0.05


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)          # drop "(Live in …)" etc.
    s = s.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sim(a: str | None, b: str | None) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return max(0.8, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def score(c: Candidate, lengths: list[int], known_artist: str | None, known_album: str | None,
          known_tracks: dict[int, str]) -> float:
    if len(c.tracks) != len(lengths):
        return 0.0
    diffs = [abs((ln or 0) - tl) for (_, ln), tl in zip(c.tracks, lengths) if ln]
    length_score = max(0.0, 1.0 - (sum(diffs) / max(len(diffs), 1)) / 8.0) if diffs else 0.5
    s = 0.35 * length_score
    weights = 0.35
    if known_album:
        s += 0.25 * max(sim(c.title, known_album), sim(f"{c.artist} {c.title}", known_album))
        weights += 0.25
    if known_artist:
        s += 0.2 * sim(c.artist, known_artist)
        weights += 0.2
    if known_tracks:
        vals = [sim(c.tracks[n - 1][0], t) for n, t in known_tracks.items() if 0 < n <= len(c.tracks) and t]
        if vals:
            s += 0.2 * (sum(vals) / len(vals))
            weights += 0.2
    result = s / weights
    if c.has_cover:
        result += 0.03
    c.details = {"length": round(length_score, 2), "avg_diff_s": round(sum(diffs) / len(diffs), 1) if diffs else None}
    return round(min(result, 1.0), 3)


def rank(cands: list[Candidate], lengths: list[int], known_artist: str | None, known_album: str | None,
         known_tracks: dict[int, str]) -> tuple[list[Candidate], str]:
    """Returns (sorted candidates, status: ok | ambiguous | none)."""
    for c in cands:
        c.score = score(c, lengths, known_artist, known_album, known_tracks)
    pref = {"XE": 0, "DE": 1, "AT": 1, "CH": 1, "GB": 2, "EU": 2, "US": 3, "XW": 4}
    cands = sorted((c for c in cands if c.score > 0),
                   key=lambda c: (-c.score, c.medium_count != 1, pref.get(c.country, 9), c.year or 9999))
    # keep one entry per release (best medium)
    seen, uniq = set(), []
    for c in cands:
        if c.release_id not in seen:
            seen.add(c.release_id)
            uniq.append(c)
    if not uniq:
        return [], "none"
    best = uniq[0]
    if best.score < AUTO_MIN_SCORE:
        return uniq, "ambiguous"
    if len(uniq) > 1 and uniq[1].score > best.score - AUTO_MIN_MARGIN and \
            norm(uniq[1].title) != norm(best.title):
        return uniq, "ambiguous"
    return uniq, "ok"
