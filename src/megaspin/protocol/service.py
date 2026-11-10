"""High-level changer operations on top of the session engine (PROT §7, §10)."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

from . import commands as C
from .codec import Frame
from .constants import HOLD_KEYS, KEYS, STEP_KEYS, Check, FrameType, Req, TextKind
from .parsers import (MinMax, TextEntry, Toc, parse_disc_byte, parse_disc_loaded, parse_event,
                      parse_minmax, parse_play_state, parse_result, parse_status, parse_text,
                      parse_toc, user_file_number)
from .session import ChangerError, SessionEngine, Timeouts
from .transport import Transport

log = logging.getLogger(__name__)


@dataclass
class PlayerStatus:
    online: bool = False
    model: str = ""
    disc: int = 0
    track: int = 0
    loaded_disc: int = 0
    play_state: str = "unknown"
    play_state_raw: int = 0
    mode: str = "track"
    random: str = "off"
    repeat: bool = False
    disc_music_type: int = 0
    disc_user_files: int = 0
    pgm_step: int = 0
    changer_event: int = -1
    event_count: int = 0            # incremented on every 0x15 frame (door / inventory / memory change)
    updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DiscRead:
    disc: int
    toc: Toc | None
    minmax: MinMax | None
    music_type: int
    user_files: int
    texts: list[TextEntry]

    @property
    def text_source(self) -> str:
        return self.texts[0].source if self.texts else "none"


@dataclass
class SlotInfo:
    disc: int
    title: str | None
    marker: str
    attr: int


StatusListener = Callable[[PlayerStatus, set], None]   # status, changed field names


TEXT_STREAM_EMPTY_LIMIT = 25     # frames without any text before a reply counts as an endless stream
TEXT_STREAM_MAX_FRAMES = 150     # hard cap for any single text reply


def _has_text(frame) -> bool:
    if frame.ftype not in (FrameType.TEXT, FrameType.CDTEXT):
        return False
    try:
        return bool(parse_text(frame.ftype, frame.payload).text)
    except Exception:
        return False


def _text_stream_give_up(frames) -> bool:
    """True = stop reading this reply (endless empty stream or unreasonably long answer)."""
    if len(frames) >= TEXT_STREAM_MAX_FRAMES:
        return True
    return len(frames) >= TEXT_STREAM_EMPTY_LIMIT and not any(_has_text(f) for f in frames)


class ChangerService:
    """Thread-safe facade. All methods block until the changer answered (use from workers)."""

    def __init__(self, transport: Transport, *, timeouts: Timeouts | None = None,
                 on_raw: Callable[[str, bytes, float], None] | None = None,
                 resync_interval: float = 60.0) -> None:
        self.status = PlayerStatus()
        self._listeners: list[StatusListener] = []
        self._cond = threading.Condition()
        self.resync_interval = resync_interval
        self.engine = SessionEngine(transport, timeouts=timeouts, on_unsolicited=self._on_frame,
                                    on_raw=on_raw, on_online=self._on_online, on_idle=self._on_idle,
                                    idle_interval=10.0)

    # ------------------------------------------------------------------ lifecycle
    def start(self, hello: bool = True) -> PlayerStatus:
        self.engine.start()
        if hello:
            self.hello()
        return self.status

    def stop(self) -> None:
        self.engine.stop()

    def add_listener(self, fn: StatusListener) -> None:
        self._listeners.append(fn)

    # ------------------------------------------------------------------ status handling
    def _update(self, **changes) -> None:
        changed = {k for k, v in changes.items() if getattr(self.status, k) != v}
        if not changed:
            return
        with self._cond:
            for k in changed:
                setattr(self.status, k, changes[k])
            self.status.updated = time.time()
            self._cond.notify_all()
        for fn in list(self._listeners):
            try:
                fn(self.status, changed)
            except Exception:
                log.exception("status listener failed")

    def _on_online(self, online: bool) -> None:
        self._update(online=online)

    def _on_idle(self, idle_for: float) -> None:
        # Status messages are sent only once per change; re-sync with Hello (PROT §15.4).
        if (not self.status.online) or idle_for >= self.resync_interval:
            self.engine.request(C.hello(), priority=4, first_timeout=3.0, label="resync")

    def _on_frame(self, fr: Frame) -> None:
        t, p = fr.ftype, fr.payload
        try:
            if t == FrameType.STATUS:
                s = parse_status(p)
                self._update(disc=s.disc, track=s.track, pgm_step=s.pgm_step,
                             disc_music_type=s.music_type, disc_user_files=s.user_files,
                             mode=s.mode, random=s.random, repeat=s.repeat)
            elif t == FrameType.PLAY_STATE:
                name, raw = parse_play_state(p)
                self._update(play_state=name, play_state_raw=raw)
            elif t == FrameType.DISC_LOADED:
                self._update(loaded_disc=parse_disc_loaded(p))
                with self._cond:
                    self._cond.notify_all()
            elif t == FrameType.EVENT:
                self._update(changer_event=parse_event(p), event_count=self.status.event_count + 1)
            else:
                log.info("unsolicited frame type %02X ignored", t)
        except Exception:
            log.exception("bad unsolicited frame %02X %s", t, p.hex())

    def wait_for(self, predicate: Callable[[PlayerStatus], bool], timeout: float) -> bool:
        end = time.monotonic() + timeout
        with self._cond:
            while not predicate(self.status):
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
        return True

    # ------------------------------------------------------------------ helpers
    def _req(self, frame: bytes, label: str, priority: int = 2, timeout: float = 30.0,
             first: float | None = None, give_up=None) -> list[Frame]:
        return self.engine.request(frame, priority=priority, first_timeout=first, label=label,
                                   give_up=give_up).result(timeout)

    def _cmd(self, *sessions, label: str, priority: int = 1, timeout: float = 30.0) -> None:
        self.engine.command(*sessions, priority=priority, label=label).result(timeout)

    @staticmethod
    def _expect(frames: list[Frame], ftype: int) -> Frame | None:
        for f in frames:
            if f.ftype == ftype:
                return f
        return None

    # ------------------------------------------------------------------ operations
    def hello(self) -> str:
        frames = self._req(C.hello(), "hello", priority=0, first=3.0)
        f = self._expect(frames, FrameType.HELLO)
        if not f:
            raise ChangerError("NO_HELLO", "no hello answer")
        model = f.payload.decode("ascii", "replace")
        self._update(model=model.removeprefix("I'm ").strip(), online=True)
        return model

    def play(self, disc: int, track: int = 1) -> None:
        self._cmd(C.select(disc, track, True), label=f"play {disc}/{track}")

    def load(self, disc: int) -> None:
        self._cmd(C.select(disc, 1, False), label=f"load {disc}")

    def key(self, name: str, action: str = "tap") -> None:
        if name not in KEYS:
            raise ValueError(f"unknown key {name}")
        if action == "press" or (action == "tap" and name not in STEP_KEYS and name not in HOLD_KEYS):
            self._cmd(C.key(name), label=f"key {name}")
        elif action == "release":
            self._cmd(C.key_release(), label="key release", priority=0)
        else:   # tap of step/hold key: press + release as two sessions (PROT §7.3)
            self._cmd(C.key(name), C.key_release(), label=f"key {name} tap")

    def reset_mode(self) -> None:
        self._cmd(C.mode_reset(), label="mode reset")

    def read_minmax(self, disc: int) -> MinMax | None:
        f = self._expect(self._req(C.cmd03(0, Req.MINMAX, disc), "minmax"), FrameType.MINMAX)
        return parse_minmax(f.payload) if f else None

    def read_toc(self, disc: int) -> Toc | None:
        """Only works for the loaded disc; otherwise the changer answers EOT only."""
        f = self._expect(self._req(C.cmd03(0, Req.TOC, disc), "toc"), FrameType.TOC)
        if not f:
            return None
        toc = parse_toc(f.payload)
        return toc if toc.status == 1 else None

    def read_user_files(self, disc: int) -> int:
        f = self._expect(self._req(C.cmd03(0, Req.USER_FILES, disc), "user files"), FrameType.USER_FILES)
        return parse_disc_byte(f.payload)[1] if f else 0

    def read_music_type(self, disc: int) -> int:
        f = self._expect(self._req(C.cmd03(0, Req.MUSIC_TYPE, disc), "music type"), FrameType.MUSIC_TYPE)
        return parse_disc_byte(f.payload)[1] if f else 0

    def read_texts(self, disc: int) -> list[TextEntry]:
        """Loaded disc with CD-TEXT -> 0xFD entries; otherwise memory titles (0xFE).

        Firmware bug (Ken-Changer, live-verified): a CD-TEXT disc without disc title answers the
        all-tracks request with an endless stream of empty frames. Then we give up on the stream and
        read the titles one track at a time (P[4] = track number, one reply per track)."""
        try:
            frames = self._req(C.cmd03(0, Req.TEXT, disc, 0, TextKind.TRACK_TITLE, 0), f"text {disc}",
                               give_up=_text_stream_give_up)
        except ChangerError as e:
            if e.code != "STREAM_ABORTED":
                raise
            log.warning("disc %s: endless text stream, reading tracks one by one", disc)
            return self.read_texts_per_track(disc)
        return [parse_text(f.ftype, f.payload) for f in frames
                if f.ftype in (FrameType.TEXT, FrameType.CDTEXT)]

    def read_texts_per_track(self, disc: int, max_tracks: int = 20) -> list[TextEntry]:
        """Track titles one request per track. Stops at the first track without a reply."""
        out: list[TextEntry] = []
        for track in range(1, max_tracks + 1):
            try:
                frames = self._req(C.cmd03(0, Req.TEXT, disc, track, TextKind.TRACK_TITLE, 0),
                                   f"text {disc}/{track}", give_up=_text_stream_give_up)
            except ChangerError as e:
                if e.code == "STREAM_ABORTED":
                    break
                raise
            entries = [parse_text(f.ftype, f.payload) for f in frames
                       if f.ftype in (FrameType.TEXT, FrameType.CDTEXT)]
            if not entries:
                break
            out.extend(entries)
        return out

    def read_slot_list(self) -> list[SlotInfo]:
        """Disc titles of all occupied slots (fast, no mechanics)."""
        frames = self._req(C.cmd03(0, Req.TEXT, 0, 0, TextKind.DISC_TITLE, 0), "slot list")
        out = []
        for f in frames:
            if f.ftype == FrameType.TEXT:
                e = parse_text(f.ftype, f.payload)
                out.append(SlotInfo(e.disc, e.text, e.marker, e.attr))
        return out

    def read_user_file_names(self) -> dict[int, str | None]:
        frames = self._req(C.cmd03(0, Req.TEXT, 0, 0, TextKind.USER_FILE_NAME, 0), "user file names")
        names: dict[int, str | None] = {}
        for f in frames:
            if f.ftype == FrameType.TEXT:
                e = parse_text(f.ftype, f.payload)
                names[user_file_number(e.index)] = e.text
        return names

    def read_program(self) -> list[tuple[int, int]]:
        f = self._expect(self._req(C.cmd03(0, Req.PROGRAM, 0), "program"), FrameType.PROGRAM)
        if not f or not f.payload:
            return []
        n, p = f.payload[0], f.payload
        return [(p[1 + 3 * i] | p[2 + 3 * i] << 8, p[3 + 3 * i]) for i in range(n)]

    def read_memory(self, disc: int) -> tuple[list[TextEntry], int, int]:
        """Memory titles (only if disc is not loaded), music type, user files."""
        return self.read_texts(disc), self.read_music_type(disc), self.read_user_files(disc)

    def read_disc_full(self, disc: int, load_timeout: float = 40.0,
                       progress: Callable[[str], None] | None = None) -> DiscRead:
        """Load disc (no play) if needed, then read TOC, min/max, MT, UF and texts (PROT §10.3)."""
        say = progress or (lambda s: None)
        if self.status.loaded_disc != disc:
            if self.status.mode != "track":
                say("Wiedergabemodus zurücksetzen")
                self.reset_mode()
            say(f"Disc {disc} wird geladen")
            self.load(disc)
            if not self.wait_for(lambda s: s.loaded_disc == disc, load_timeout):
                raise ChangerError("LOAD_TIMEOUT", f"disc {disc} not loaded")
            self.wait_for(lambda s: s.play_state in ("stopped", "playing", "paused"), 5.0)
        say("Inhaltsverzeichnis lesen")
        toc = self.read_toc(disc)
        minmax = self.read_minmax(disc)
        mt = self.read_music_type(disc)
        uf = self.read_user_files(disc)
        say("Titel lesen")
        texts = self.read_texts(disc)
        return DiscRead(disc, toc, minmax, mt, uf, texts)

    def write_titles(self, disc: int, title: str, tracks: dict[int, str], music_type: int = 0,
                     user_files: int = 0, max_tracks: int = 20) -> None:
        """Write disc/track titles, music type and user-file bits into changer memory (PROT §7.7)."""
        res = self._expect(self._req(C.cmd03(Check.TITLES, 0, disc, 0, 1, music_type), "title check"),
                           FrameType.RESULT)
        if not res or not (parse_result(res.payload) & 1):
            raise ChangerError("TITLE_INPUT_REFUSED", "changer refused title input")
        frames = C.disc_title_frames(disc, title, tracks, user_files, music_type, max_tracks)
        self._cmd(frames, label=f"write titles {disc}", timeout=60)

    def write_user_file_names(self, names: dict[int, str]) -> None:
        self._req(C.cmd03(Check.USER_FILE_NAMES, 0, 0, 0, 1, 0), "uf name check")
        frames = [C.text_frame(0, 1 << (n - 1), TextKind.USER_FILE_NAME,
                               names.get(n) or f"USER FILE {n}") for n in range(1, 9)]
        self._cmd(frames, label="write user file names", timeout=60)
