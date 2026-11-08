"""Parsers for frames sent by the changer (PROT §8, §9)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .constants import MODES, PLAY_STATES


def _u16(p: bytes, i: int = 0) -> int:
    return p[i] | (p[i + 1] << 8)


def bcd(x: int) -> int:
    return (x >> 4) * 10 + (x & 0x0F)


def _text(raw: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else ("?" if c == 0x7F else "") for c in raw).rstrip()


# ---------------------------------------------------------------- status frames

@dataclass
class StatusInfo:          # 0x12
    disc: int
    track: int
    pgm_step: int
    music_type: int
    user_files: int
    unknown6: int
    mode: str
    random: str
    mode_raw: int
    repeat: bool


def parse_status(p: bytes) -> StatusInfo:
    p = p.ljust(9, b"\x00")
    mode, rnd = MODES.get(p[7], ("unknown", "off"))
    return StatusInfo(disc=_u16(p), track=p[2], pgm_step=p[3], music_type=p[4],
                      user_files=p[5], unknown6=p[6], mode=mode, random=rnd,
                      mode_raw=p[7], repeat=p[8] != 0)


def parse_play_state(p: bytes) -> tuple[str, int]:     # 0x13
    raw = p[0] if p else 0
    return PLAY_STATES.get(raw, f"unknown_{raw:02x}"), raw


def parse_disc_loaded(p: bytes) -> int:                 # 0x14
    return _u16(p) if len(p) >= 2 else 0


def parse_event(p: bytes) -> int:                       # 0x15
    return p[0] if p else 0


# ---------------------------------------------------------------- replies

@dataclass
class MinMax:              # 0x04
    disc: int
    first: int
    last: int
    attr: int

    @property
    def known(self) -> bool:
        return self.last != 0x63   # 99 = unknown (disc not loaded)


def parse_minmax(p: bytes) -> MinMax:
    return MinMax(_u16(p), p[2], p[3], p[4] if len(p) > 4 else 0)


@dataclass
class Toc:                 # 0x06
    disc: int
    status: int
    attr: int
    first: int
    last: int
    starts: list[tuple[int, int, int]]       # MSF of each track (BCD decoded)
    leadout: tuple[int, int, int]

    @property
    def track_count(self) -> int:
        return len(self.starts)

    def start_seconds(self) -> list[int]:
        return [m * 60 + s for m, s, _ in self.starts]

    @property
    def leadout_seconds(self) -> int:
        return self.leadout[0] * 60 + self.leadout[1]

    def lengths(self) -> list[int]:
        st = self.start_seconds() + [self.leadout_seconds]
        return [st[i + 1] - st[i] for i in range(len(self.starts))]

    def freedb_id(self) -> str:
        def digsum(n: int) -> int:
            return sum(int(d) for d in str(n))
        offs = self.start_seconds()
        xx = sum(digsum(o) for o in offs) % 255
        yyyy = self.leadout_seconds - offs[0]
        return f"{xx:02x}{yyyy:04x}{len(offs):02x}"

    def musicbrainz_toc(self) -> str:
        def lba(m: int, s: int, f: int) -> int:
            return (m * 60 + s) * 75 + f
        parts = [self.first, self.last, lba(*self.leadout)] + [lba(*x) for x in self.starts]
        return " ".join(str(x) for x in parts)


def parse_toc(p: bytes) -> Toc:
    disc, status, attr, first, last = _u16(p), p[2], p[3], p[4], p[5]
    entries = [(bcd(p[i]), bcd(p[i + 1]), bcd(p[i + 2])) for i in range(6, len(p) - 2, 3)]
    if not entries:
        raise ValueError("empty TOC")
    return Toc(disc, status, attr, first, last, entries[:-1], entries[-1])


def parse_disc_byte(p: bytes) -> tuple[int, int]:      # 0x07 / 0x08 -> (disc, value)
    return _u16(p), p[2] if len(p) > 2 else 0


def parse_result(p: bytes) -> int:                      # 0x09
    return p[0] if p else 0


@dataclass
class TextEntry:           # 0xFE (memory) / 0xFD (CD-TEXT)
    source: str            # "memory" | "cdtext"
    disc: int
    index: int             # track number (0 = disc title) or user-file bit
    kind: int              # 0 disc title, 1 track title, 7 user file name
    user_files: int
    music_type: int
    attr: int
    text: str | None       # None = no title / no disc
    marker: str = ""       # "" | "no_title" | "no_disc"
    extra: bytes = field(default=b"", repr=False)

    @property
    def track(self) -> int:
        return self.index


def parse_text(ftype: int, p: bytes) -> TextEntry:
    disc, index, b5, kind, b7, attr = _u16(p), p[2], p[3], p[4], p[5], p[6]
    if ftype == 0xFD:
        source, raw, extra = "cdtext", p[8:], p[7:8]
    else:
        source, raw, extra = "memory", p[7:], b""
    text, marker = None, ""
    if len(raw) == 1 and raw[0] in (0, 1):
        marker = "no_disc" if raw[0] == 0 else "no_title"
    else:
        text = _text(raw)
        if not text:
            marker = "no_title"
            text = None
    return TextEntry(source, disc, index, kind, b5, b7, attr, text, marker, extra)


def user_file_number(bit: int) -> int:
    """Bit mask (0x01..0x80) -> user file number 1..8."""
    for n in range(8):
        if bit == 1 << n:
            return n + 1
    return 0


def split_artist_album(s: str | None) -> tuple[str | None, str | None]:
    """Changer/CD-TEXT disc titles are 'Artist   Album' (three spaces)."""
    if not s:
        return None, None
    if "   " in s:
        a, b = s.split("   ", 1)
        return a.strip() or None, b.strip() or None
    return None, s.strip()
