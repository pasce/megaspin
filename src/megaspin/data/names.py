"""Name normalisation for display and grouping (artists, album and track titles)."""
from __future__ import annotations

import re
import unicodedata

_KEEP = re.compile(r"[\d/.]")          # AC/DC, R.E.M., U2 stay as they are
_SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "vs",
          "feat", "der", "die", "das", "und", "von", "mit", "im"}


def artist_key(s: str | None) -> str:
    """Grouping key: case, accents, spacing and a leading 'The' are ignored."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\s+", " ", s.replace("&", " and ")).strip()
    return s[4:] if s.startswith("the ") else s


def _cap_word(w: str, first: bool) -> str:
    if not w or _KEEP.search(w):
        return w
    low = w.lower()
    if not first and low.strip("()[]-'\"") in _SMALL:
        return low
    # capitalise the first letter (also after an opening bracket / quote)
    for i, ch in enumerate(low):
        if ch.isalpha():
            return low[:i] + ch.upper() + low[i + 1:]
    return low


def nice_case(s: str | None) -> str | None:
    """'PEARL JAM' -> 'Pearl Jam'. Only all-uppercase text (changer memory, CD-TEXT) is changed;
    text that already contains lowercase letters is kept exactly as it is."""
    if not s or any(ch.islower() for ch in s) or not any(ch.isalpha() for ch in s):
        return s
    parts = re.split(r"(\s+)", s)
    out, first = [], True
    for p in parts:
        if p.isspace() or not p:
            out.append(p)
            continue
        out.append(_cap_word(p, first))
        first = p.endswith((":", "-", "(")) or False
    return "".join(out)


def best_variant(names: list[str]) -> str:
    """Display name for a group of spellings: prefer mixed case (e.g. from MusicBrainz), then the most
    frequent one; all-uppercase names are converted with nice_case."""
    from collections import Counter
    c = Counter(names)
    mixed = [n for n in c if any(ch.islower() for ch in n)]
    pool = mixed or list(c)
    pick = max(pool, key=lambda n: (c[n], n))
    return nice_case(pick) or pick
