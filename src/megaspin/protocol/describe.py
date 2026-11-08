"""Human-readable description of control bytes and frames (protocol console, PROT §5–§9)."""
from __future__ import annotations

from .codec import BadFrame, Ctrl, Frame
from .constants import KEYS, MODES, PLAY_STATES, FrameType, music_type_name
from .parsers import parse_minmax, parse_status, parse_text, parse_toc

CTRL_TEXT = {0x05: "ENQ – Sitzung anfragen", 0x06: "ACK – bestätigt", 0x15: "NAK – abgelehnt",
             0x04: "EOT – Sitzung Ende"}
KEY_NAMES = {v: k for k, v in KEYS.items()}
KEY_TEXT = {"play_pause": "Play/Pause", "stop": "Stop", "repeat": "Repeat", "random": "Random",
            "prev": "Zurück", "next": "Weiter", "rew": "Rücklauf (gedrückt)", "ff": "Vorlauf (gedrückt)"}
PLAY_TEXT = {"stopped": "Stop", "stopping": "stoppt", "searching": "Suche/Laden", "playing": "Wiedergabe",
             "paused": "Pause", "ff": "Vorlauf", "rew": "Rücklauf"}
REQ_TEXT = {0x01: "Texte", 0x02: "Min/Max-Track", 0x04: "Inhaltsverzeichnis (TOC)", 0x08: "User Files",
            0x10: "Music Type", 0x20: "Programmliste"}
CHECK_TEXT = {0x80: "Titeleingabe prüfen", 0x40: "User-File-Namen prüfen", 0x20: "Programm prüfen",
              0x10: "Modus-Wiedergabe prüfen"}
TEXT_KIND = {0: "Disc-Titel", 1: "Track-Titel", 7: "User-File-Name"}
REQ_TEXT_KIND = {0: "Disc-Titel", 1: "alle Titel", 7: "User-File-Namen"}


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
                return f"Prüfung: {CHECK_TEXT.get(a, f'A={a:02X}')}" + (f" (Disc {disc})" if disc else "")
            what = REQ_TEXT.get(b, f"B={b:02X}")
            if b == 0x01 and len(p) > 5:
                what += f" ({REQ_TEXT_KIND.get(p[5], f'Art {p[5]}')})"
            return f"Anfrage: {what}" + (f" für Disc {disc}" if disc else " (alle Discs)")
        if t == FrameType.KEY:
            if tuple(p[:2]) == (0xFF, 0xFF):
                return "Taste losgelassen"
            k = KEY_NAMES.get(tuple(p[:2]))
            return "Taste: " + (KEY_TEXT.get(k, k) if k else p[:2].hex(" ").upper())
        if t == FrameType.SELECT:
            return f"Disc {_disc(p)} Track {p[2]} " + ("abspielen" if p[3] else "laden (ohne Wiedergabe)")
        if t == FrameType.MODE:
            return "Modus zurücksetzen (Track Mode)"
        if t == FrameType.PROGRAM:
            return f"Programmliste ({p[0] if p else 0} Einträge)"
        if t == FrameType.STATUS:
            s = parse_status(p)
            extra = [f"Modus {s.mode}"]
            if s.random != "off":
                extra.append(f"Random {s.random}")
            if s.repeat:
                extra.append("Repeat")
            if s.music_type:
                extra.append(music_type_name(s.music_type))
            if s.user_files:
                extra.append(f"UF 0x{s.user_files:02X}")
            return f"Status: Disc {s.disc} Track {s.track} · " + " · ".join(extra)
        if t == FrameType.PLAY_STATE:
            name = PLAY_STATES.get(p[0], f"{p[0]:02X}")
            return f"Zustand: {PLAY_TEXT.get(name, name)}"
        if t == FrameType.DISC_LOADED:
            return f"Geladen: Disc {_disc(p)}"
        if t == FrameType.EVENT:
            return {0: "Klappe geschlossen", 1: "Klappe offen"}.get(p[0], f"Ereignis {p[0]:02X}")
        if t == FrameType.MINMAX:
            m = parse_minmax(p)
            return f"Min/Max: Disc {m.disc} Track {m.first}–{m.last}"
        if t == FrameType.TOC:
            toc = parse_toc(p)
            if toc.status != 1:
                return f"TOC: Disc {toc.disc} nicht lesbar (nicht geladen)"
            return f"TOC: Disc {toc.disc}, {toc.track_count} Tracks, Länge {toc.leadout[0]}:{toc.leadout[1]:02d}"
        if t in (FrameType.USER_FILES, FrameType.MUSIC_TYPE):
            v = p[2] if len(p) > 2 else 0
            if t == FrameType.MUSIC_TYPE:
                return f"Music Type Disc {_disc(p)}: {music_type_name(v)}"
            return f"User Files Disc {_disc(p)}: 0x{v:02X}"
        if t == FrameType.RESULT:
            return f"Antwort: 0x{p[0]:02X}" if p else "Antwort"
        if t in (FrameType.TEXT, FrameType.CDTEXT):
            e = parse_text(t, p)
            src = "CD-TEXT" if t == FrameType.CDTEXT else "Speicher"
            kind = TEXT_KIND.get(e.kind, f"Art {e.kind}")
            if e.kind == 1 and e.index == 0:
                kind = "Disc-Titel"
            where = f"Disc {e.disc}" + (f" Track {e.index}" if e.kind == 1 and e.index else "")
            txt = e.text if e.text is not None else f"({e.marker or 'leer'})"
            return f"{src} {kind} {where}: {txt}"
    except Exception:
        pass
    return f"Frame {t:02X} ({len(p)} Bytes)"


def describe(msg) -> str:
    if isinstance(msg, Ctrl):
        return CTRL_TEXT.get(msg.byte, f"Steuerbyte {msg.byte:02X}")
    if isinstance(msg, BadFrame):
        return "Fehlerhafter Frame (Prüfsumme)"
    if isinstance(msg, Frame):
        return describe_frame(msg)
    return str(msg)


def mode_name(raw: int) -> str:
    return "/".join(MODES.get(raw, ("?", "?")))
