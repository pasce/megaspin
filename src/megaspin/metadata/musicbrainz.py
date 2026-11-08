"""MusicBrainz TOC lookup and Cover Art Archive (replacement for the defunct CDDB).

Rules: max. 1 request/second, meaningful User-Agent (https://musicbrainz.org/doc/MusicBrainz_API).
Only titles and covers are used – no other web content.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .. import __version__

log = logging.getLogger(__name__)

MB_BASE = "https://musicbrainz.org/ws/2"
JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF])
PNG_MAGIC = bytes([0x89, 0x50, 0x4E])
CAA_BASE = "https://coverartarchive.org"


class RateLimiter:
    def __init__(self, interval: float = 1.1) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self.interval:
                time.sleep(self.interval - delta)
            self._last = time.monotonic()


_mb_limit = RateLimiter(1.1)
_caa_limit = RateLimiter(1.0)


def user_agent(contact: str = "") -> str:
    return f"MegaSpin/{__version__} ( {contact or 'local desktop app'} )"


def _get(url: str, contact: str, limiter: RateLimiter, accept: str = "application/json",
         timeout: float = 15.0, max_bytes: int = 4_000_000) -> bytes | None:
    limiter.wait()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(contact), "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(max_bytes + 1)[:max_bytes]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


@dataclass
class Candidate:
    release_id: str
    group_id: str | None
    title: str
    artist: str
    year: int | None
    country: str
    label: str
    medium: int                     # medium position matching the TOC (multi-disc releases)
    medium_count: int
    tracks: list[tuple[str, int | None]]   # (title, length seconds)
    has_cover: bool
    score: float = 0.0
    details: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, s: str) -> "Candidate":
        d = json.loads(s)
        d["tracks"] = [tuple(t) for t in d["tracks"]]
        return cls(**d)


def _artist(credit: list[dict]) -> str:
    return "".join(c.get("name", "") + c.get("joinphrase", "") for c in credit or []).strip()


def parse_releases(data: dict, track_count: int) -> list[Candidate]:
    """One candidate per (release, medium with the right track count)."""
    out: list[Candidate] = []
    for rel in data.get("releases", []):
        media = rel.get("media") or []
        for med in media:
            tracks = med.get("tracks") or []
            n = med.get("track-count", len(tracks))
            if n != track_count:
                continue
            labels = rel.get("label-info") or []
            label = (labels[0].get("label") or {}).get("name", "") if labels else ""
            date = rel.get("date") or ""
            out.append(Candidate(
                release_id=rel["id"],
                group_id=(rel.get("release-group") or {}).get("id"),
                title=rel.get("title", ""),
                artist=_artist(rel.get("artist-credit")),
                year=int(date[:4]) if date[:4].isdigit() else None,
                country=rel.get("country") or "",
                label=label,
                medium=med.get("position", 1),
                medium_count=len(media),
                tracks=[(t.get("title", ""), round(t["length"] / 1000) if t.get("length") else None)
                        for t in tracks],
                has_cover=bool((rel.get("cover-art-archive") or {}).get("front")),
            ))
    return out


def lookup_toc(toc: str, track_count: int, contact: str = "") -> list[Candidate]:
    """Fuzzy TOC lookup (changer TOC has second precision only)."""
    q = urllib.parse.urlencode({"toc": toc, "fmt": "json", "inc": "artists+recordings+release-groups+labels"},
                               safe="+")
    raw = _get(f"{MB_BASE}/discid/-?{q}", contact, _mb_limit)
    if not raw:
        return []
    data = json.loads(raw)
    if "releases" not in data and "disc" in data:          # exact disc id hit
        data = {"releases": data["disc"].get("releases", [])}
    return parse_releases(data, track_count)


def search_releases(query: str, track_count: int, contact: str = "", limit: int = 15) -> list[Candidate]:
    """Free-text search (manual search in the selection dialog)."""
    q = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": limit})
    raw = _get(f"{MB_BASE}/release/?{q}", contact, _mb_limit)
    if not raw:
        return []
    ids = [r["id"] for r in json.loads(raw).get("releases", [])][:limit]
    out: list[Candidate] = []
    for rid in ids[:8]:                                     # fetch details (tracks) for the best hits
        raw = _get(f"{MB_BASE}/release/{rid}?fmt=json&inc=artists+recordings+release-groups+labels",
                    contact, _mb_limit)
        if raw:
            out += parse_releases({"releases": [json.loads(raw)]}, track_count)
    return out


def fetch_cover_ids(release_id: str, group_id: str | None, contact: str = "", size: int = 500) -> bytes | None:
    """Front cover from the Cover Art Archive.

    Order: release-group thumbnail, release thumbnail, original image of the release
    (thumbnails sometimes fail with HTTP 500 on the server side). The caller scales large images.
    """
    urls = []
    if group_id:
        urls.append(f"{CAA_BASE}/release-group/{group_id}/front-{size}")
    urls.append(f"{CAA_BASE}/release/{release_id}/front-{size}")
    urls.append(f"{CAA_BASE}/release/{release_id}/front")
    for url in urls:
        try:
            data = _get(url, contact, _caa_limit, accept="image/*", max_bytes=12_000_000, timeout=40)
        except Exception as e:
            log.info("cover %s failed: %s", url, e)
            data = None
        if data and data[:3] in (JPEG_MAGIC, PNG_MAGIC):
            return data
    return None


def fetch_cover(cand: Candidate, contact: str = "", size: int = 500) -> bytes | None:
    return fetch_cover_ids(cand.release_id, cand.group_id, contact, size)
