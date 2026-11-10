"""Human-readable description of control bytes and frames (protocol console, PROT §5–§9)."""
from __future__ import annotations

from ..i18n import tr
from .codec import BadFrame, Ctrl, Frame
from .constants import KEYS, MODES, PLAY_STATES, FrameType, music_type_name
from .parsers import parse_minmax, parse_status, parse_text, parse_toc

CTRL_TEXT = {0x05: tr("ENQ – request session"), 0x06: tr("ACK – acknowledged"), 0x15: tr("NAK – rejected"),
             0x04: tr("EOT – end of session")}
KEY_NAMES = {v: k for k, v in KEYS.items()}
KEY_TEXT = {"play_pause": "Play/Pause", "stop": "Stop", "repeat": "Repeat", "random": "Random",
            "prev": tr("Previous"), "next": tr("Next"), "rew": tr("Rewind (held)"), "ff": tr("Fast forward (held)")}
PLAY_TEXT = {"stopped": "Stop", "stopping": tr("stopping"), "searching": tr("searching / loading"),
             "playing": tr("playing"), "paused": tr("paused"), "ff": tr("Fast forward"), "rew": tr("Rewind")}
REQ_TEXT = {0x01: tr("texts"), 0x02: tr("Min/Max track"), 0x04: tr("table of contents (TOC)"),
            0x08: tr("user files"), 0x10: "Music Type", 0x20: tr("program list")}
CHECK_TEXT = {0x80: tr("check title input"), 0x40: tr("check user file names"), 0x20: tr("check program"),
              0x10: tr("check playback mode")}
TEXT_KIND = {0: tr("disc title"), 1: tr("track title"), 7: tr("user file name")}
REQ_TEXT_KIND = {0: tr("disc title"), 1: tr("all titles"), 7: tr("user file names")}


def _disc(p: bytes, i: int = 0) -> int:
    return p[i] | (p[i + 1] << 8) if len(p) > i + 1 else 0


def describe_frame(f: Frame) -> str:
    t, p = f.ftype, f.payload
    try:
        if t == FrameType.HELLO:
            return "Hello: " + p.decode("ascii", "replace")
        if t == FrameType.CMD:
            a, b = p[0], p[1]
            disc = _disc(p, 2)
            if a:
                text = tr("Check: {0}").format(CHECK_TEXT.get(a, f"A={a:02X}"))
                return text + (tr(" (disc {0})").format(disc) if disc else "")
            what = REQ_TEXT.get(b, f"B={b:02X}")
            if b == 0x01 and len(p) > 5:
                what += " (" + REQ_TEXT_KIND.get(p[5], tr("type {0}").format(p[5])) + ")"
            return tr("Request: {0}").format(what) + (tr(" for disc {0}").format(disc) if disc
                                                       else tr(" (all discs)"))
        if t == FrameType.KEY:
            if tuple(p[:2]) == (0xFF, 0xFF):
                return tr("Key released")
            k = KEY_NAMES.get(tuple(p[:2]))
            return tr("Key: {0}").format(KEY_TEXT.get(k, k) if k else p[:2].hex(" ").upper())
        if t == FrameType.SELECT:
            mode = tr("play") if p[3] else tr("load (no playback)")
            return tr("Disc {0} track {1}: {2}").format(_disc(p), p[2], mode)
        if t == FrameType.MODE:
            return tr("Reset mode (track mode)")
        if t == FrameType.PROGRAM:
            return tr("Program list ({0} entries)").format(p[0] if p else 0)
        if t == FrameType.STATUS:
            s = parse_status(p)
            extra = [tr("mode {0}").format(s.mode)]
            if s.random != "off":
                extra.append(f"Random {s.random}")
            if s.repeat:
                extra.append("Repeat")
            if s.music_type:
                extra.append(music_type_name(s.music_type))
            if s.user_files:
                extra.append(f"UF 0x{s.user_files:02X}")
            return tr("Status: disc {0} track {1}").format(s.disc, s.track) + " · " + " · ".join(extra)
        if t == FrameType.PLAY_STATE:
            name = PLAY_STATES.get(p[0], f"{p[0]:02X}")
            return tr("State: {0}").format(PLAY_TEXT.get(name, name))
        if t == FrameType.DISC_LOADED:
            return tr("Loaded: disc {0}").format(_disc(p))
        if t == FrameType.EVENT:
            if p[0] in (0, 1):
                return tr("Door closed") if p[0] == 0 else tr("Door open")
            return tr("Event {0}").format(f"{p[0]:02X}")
        if t == FrameType.MINMAX:
            m = parse_minmax(p)
            return tr("Min/Max: disc {0} track {1}–{2}").format(m.disc, m.first, m.last)
        if t == FrameType.TOC:
            toc = parse_toc(p)
            if toc.status != 1:
                return tr("TOC: disc {0} not readable (not loaded)").format(toc.disc)
            return tr("TOC: disc {0}, {1} tracks, length {2}:{3:02d}").format(
                toc.disc, toc.track_count, toc.leadout[0], toc.leadout[1])
        if t in (FrameType.USER_FILES, FrameType.MUSIC_TYPE):
            v = p[2] if len(p) > 2 else 0
            if t == FrameType.MUSIC_TYPE:
                return tr("Music type disc {0}: {1}").format(_disc(p), music_type_name(v))
            return tr("User files disc {0}: 0x{1:02X}").format(_disc(p), v)
        if t == FrameType.RESULT:
            return tr("Result: 0x{0:02X}").format(p[0]) if p else tr("Result")
        if t in (FrameType.TEXT, FrameType.CDTEXT):
            e = parse_text(t, p)
            src = tr("CD-TEXT") if t == FrameType.CDTEXT else tr("memory")
            kind = TEXT_KIND.get(e.kind, tr("type {0}").format(e.kind))
            if e.kind == 1 and e.index == 0:
                kind = tr("disc title")
            where = tr("disc {0}").format(e.disc) + (tr(" track {0}").format(e.index)
                                                    if e.kind == 1 and e.index else "")
            txt = e.text if e.text is not None else f"({e.marker or tr('empty')})"
            return f"{src} {kind} {where}: {txt}"
    except Exception:
        pass
    return tr("Frame {0} ({1} bytes)").format(f"{t:02X}", len(p))


def describe(msg) -> str:
    if isinstance(msg, Ctrl):
        return CTRL_TEXT.get(msg.byte, tr("Control byte {0}").format(f"{msg.byte:02X}"))
    if isinstance(msg, BadFrame):
        return tr("Faulty frame (checksum)")
    if isinstance(msg, Frame):
        return describe_frame(msg)
    return str(msg)


def mode_name(raw: int) -> str:
    return "/".join(MODES.get(raw, ("?", "?")))
