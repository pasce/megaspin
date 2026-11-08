"""Frame builders for everything the PC sends (PROT §7)."""
from __future__ import annotations

import unicodedata

from .codec import build_frame
from .constants import KEY_RELEASE, KEYS, MEMORY_TITLE_LEN, FrameType, TextKind


def hello() -> bytes:
    return build_frame(FrameType.HELLO, b"I'm PC")


def cmd03(a: int, b: int, disc: int = 0, b4: int = 0, b6: int = 0, b7: int = 0) -> bytes:
    """Universal request/command frame (LEN 7)."""
    return build_frame(FrameType.CMD, [a, b, disc & 0xFF, (disc >> 8) & 0xFF, b4, b6, b7])


def key(name: str) -> bytes:
    custom, code = KEYS[name]
    return build_frame(FrameType.KEY, [custom, code])


def key_release() -> bytes:
    return build_frame(FrameType.KEY, list(KEY_RELEASE))


def select(disc: int, track: int = 1, play: bool = True) -> bytes:
    """Load disc (and play track if play=True)."""
    return build_frame(FrameType.SELECT, [disc & 0xFF, (disc >> 8) & 0xFF, track, 1 if play else 0])


def mode_reset() -> bytes:
    return build_frame(FrameType.MODE, [0, 0])


def program(entries: list[tuple[int, int]]) -> bytes:
    """Program list: [(disc, track)], track 0xAA = all tracks."""
    payload = [len(entries)]
    for disc, track in entries:
        payload += [disc & 0xFF, (disc >> 8) & 0xFF, track]
    return build_frame(FrameType.PROGRAM, payload)


_TRANSLIT = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
             "’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."}


def to_changer_text(text: str, limit: int = MEMORY_TITLE_LEN) -> bytes:
    """Transliterate to printable ASCII and cut to the changer limit (25 chars)."""
    s = "".join(_TRANSLIT.get(c, c) for c in (text or ""))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = "".join(c if 32 <= ord(c) < 127 else "?" for c in s)
    return s[:limit].encode("ascii")


def text_frame(disc: int, b4: int, kind: int, text: str, user_files: int = 0,
               music_type: int = 0) -> bytes:
    """0xFE text frame. Empty text -> single 0x01 byte (= no title)."""
    body = to_changer_text(text)
    if not body:
        body = b"\x01"
    payload = bytes([disc & 0xFF, (disc >> 8) & 0xFF, b4, user_files, kind, music_type, 0]) + body
    return build_frame(FrameType.TEXT, payload)


def disc_title_frames(disc: int, title: str, tracks: dict[int, str], user_files: int,
                      music_type: int, max_tracks: int = 20) -> list[bytes]:
    frames = [text_frame(disc, 0, TextKind.DISC_TITLE, title, user_files, music_type)]
    for no in range(1, max_tracks + 1):
        if no in tracks:
            frames.append(text_frame(disc, no, TextKind.TRACK_TITLE, tracks[no], user_files, music_type))
    return frames
