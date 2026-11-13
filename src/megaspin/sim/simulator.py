"""CD-425M simulator (changer side), built from the live measurements.

Reproduces: hello + status burst, all requests, key codes incl. auto-repeat until release,
disc loading with delays, CD-TEXT only for the loaded disc (with optional pause between frames),
memory titles (25 chars, tracks 0..20), title writes, CD-TEXT overwriting memory titles on load,
2 s retries when the PC does not acknowledge.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from ..protocol.codec import BadFrame, Ctrl, Frame, FrameParser, build_frame
from ..protocol.constants import ACK, ENQ, EOT, NAK, FrameType
from ..protocol.transport import Transport

log = logging.getLogger(__name__)


def _bcd(n: int) -> int:
    return ((n // 10) << 4) | (n % 10)


@dataclass
class SimDisc:
    slot: int
    starts: list[tuple[int, int]]                  # track start (min, sec)
    leadout: tuple[int, int]
    memory_title: str | None = None
    memory_tracks: dict[int, str] = field(default_factory=dict)
    cdtext: dict[int, str] | None = None           # 0 = "Artist   Album"
    music_type: int = 0
    user_files: int = 0
    attr: int = 0x00

    @property
    def last(self) -> int:
        return len(self.starts)


def _toc(durations: list[int]) -> tuple[list[tuple[int, int]], tuple[int, int]]:
    """Track starts (min, sec) and lead-out for track lengths in seconds (2 s pre-gap, like a real disc)."""
    def mmss(t: int) -> tuple[int, int]:
        return t // 60, t % 60
    pos = 2
    starts = []
    for d in durations:
        starts.append(mmss(pos))
        pos += d
    return starts, mmss(pos)


def _disc(slot: int, album_title: str, tracks: list[tuple[str, int]], *, suffix: str = "",
          **kw) -> SimDisc:
    """A fictional disc: CD-TEXT title 'Artist   Album' and track titles, lengths in seconds."""
    starts, leadout = _toc([d for _, d in tracks])
    cdtext = {0: album_title, **{i + 1: t + suffix for i, (t, _) in enumerate(tracks)}}
    return SimDisc(slot, starts, leadout, cdtext=cdtext, **kw)


def default_discs() -> dict[int, SimDisc]:
    """Six fictional discs for the digital twin. Artists, albums, tracks and lengths are invented;
    the slots and track counts follow the layout of a real changer."""
    d: dict[int, SimDisc] = {}
    d[5] = _disc(5, "Lena Marsh   Paper Harbour", [
        ("Morning Ferry", 204), ("Salt on the Glass", 231), ("Low Tide Lights", 187),
        ("Paper Harbour", 259), ("Gull Song", 176), ("Second Pier", 213), ("Tin Roof Rain", 242),
        ("Halfway Home", 198), ("Blue Cranes", 221), ("Ropes and Knots", 189), ("Slow Bell", 264),
        ("Last Lantern", 310)])
    d[147] = _disc(147, "The Velvet Owls   Night Market", [
        ("Open Door", 183), ("Neon Sparrow", 242), ("Night Market", 268), ("Copper Coins", 201),
        ("Velvet Owl", 226), ("Red Lantern Street", 195), ("Quiet Trams", 214), ("Sugar Hour", 178),
        ("Third Floor", 232), ("Static Hearts", 209), ("Harbour Lights Fade", 247),
        ("Empty Carousel", 199), ("Afterglow Diner", 221), ("Goodnight Market", 286),
        ("Closing Shutters", 192)])
    d[148] = _disc(148, "Hollow Pines   Glass Orchard", [
        ("Glass Orchard", 215), ("Winter Fence", 188), ("Hollow Pines", 254), ("Honey Creek", 201),
        ("Pale Morning", 232), ("Iron Gate", 176), ("Orchard Bells", 209), ("Long Shadow", 243),
        ("Small Hours", 198), ("Sparrow Road", 221), ("Water Mill", 187), ("Last Frost", 262)])
    d[149] = _disc(149, "Dana Reyes   Quiet Engines", [
        ("Quiet Engines", 238), ("Ignition Waltz", 201), ("Cold Start", 186), ("Diesel Hymn", 254),
        ("Rust and Chrome", 219), ("Idle Ground", 196), ("Night Shift", 233), ("Highway Mercy", 271),
        ("Turnpike Blues", 205), ("Engine Room", 184), ("Coasting", 228), ("Cool Down", 302)],
        attr=0x93, music_type=7)
    d[150] = _disc(150, "NORTHLINE   LIVE AT HARBOUR HALL, MARCH 3 2001 / CD2", [
        ("Signal Fire", 312), ("Undertow", 264), ("Glass Coast", 287), ("Harbour Hall", 341),
        ("Tidewater", 229), ("Night Crossing", 298), ("Blue Ferry", 256), ("Cliff Road", 274),
        ("Storm Watch", 318), ("Lighthouse", 243), ("Last Call", 365)],
        suffix=" (Live at Harbour Hall)", music_type=3, user_files=1, attr=0x13)
    d[151] = _disc(151, "NORTHLINE   LIVE IN RIVERTON, OCTOBER 7 1999", [
        ("Riverbed", 276), ("Bright Cargo", 232), ("Fog Horn", 198), ("Ballast", 311),
        ("Paper Boats", 224), ("Rope Swing", 257), ("Tin Lanterns", 203), ("Sea Glass", 289),
        ("Cold Dock", 246), ("Low Gulls", 215), ("Sail Away", 268), ("Stone Pier", 194),
        ("Dry Land", 232), ("Undertow Again", 301), ("Warm Harbour", 219), ("Last Light", 342)],
        suffix=" (Live in Riverton)", attr=0x13)
    for disc in d.values():                    # memory mirrors CD-TEXT (changer copies it on load)
        if disc.cdtext:
            disc.memory_title = (disc.cdtext.get(0) or "")[:25] or None
            disc.memory_tracks = {n: t[:25] for n, t in disc.cdtext.items() if 0 < n <= 20}
    for slot in (5, 147, 148):                 # discs without any title: TOC only, as on the real changer
        d[slot].cdtext = None
        d[slot].memory_title = None
        d[slot].memory_tracks = {}
    return d


class ChangerSimulator:
    def __init__(self, transport: Transport, discs: dict[int, SimDisc] | None = None, *,
                 load_delay: float = 0.3, model: str = "CD-425M", cdtext_pause_after: int | None = 12,
                 cdtext_pause: float = 0.38, retry_interval: float = 2.0, retries: int = 5) -> None:
        self.tr = transport
        self.discs = discs if discs is not None else default_discs()
        self.load_delay = load_delay
        self.model = model
        self.cdtext_pause_after = cdtext_pause_after
        self.cdtext_pause = cdtext_pause
        self.retry_interval = retry_interval
        self.retries = retries
        # changer state
        self.disc = 149
        self.track = 1
        self.loaded = 149
        self.play_state = 0x40
        self.mode_raw = 0
        self.repeat = False
        self.held_key: tuple[int, int] | None = None
        self.uf_names: dict[int, str | None] = {n: None for n in range(1, 9)}
        self.ack_disabled = False           # test hook: changer stops answering
        # internals
        self._parser = FrameParser()
        self._pending: deque = deque()
        self._outbox: deque[bytes] = deque()
        self._timers: list[tuple[float, callable]] = []
        self._next_repeat = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.received: list[Frame] = []     # all frames the PC sent (for tests)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> "ChangerSimulator":
        self._thread = threading.Thread(target=self._run, name="changer-sim", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    # ------------------------------------------------------------------ helpers
    def _w(self, b: bytes) -> None:
        self.tr.write(b)

    def _next(self, timeout: float):
        end = time.monotonic() + timeout
        while not self._pending:
            rem = end - time.monotonic()
            if rem <= 0 or self._stop.is_set():
                return None
            data = self.tr.read(min(rem, 0.02))
            for m in self._parser.feed(data, time.monotonic()):
                self._pending.append(m)
        return self._pending.popleft()

    def _status_frame(self) -> bytes:
        d = self.discs.get(self.disc)
        mt, uf = (d.music_type, d.user_files) if d else (0, 0)
        return build_frame(FrameType.STATUS, [self.disc & 0xFF, self.disc >> 8, self.track, 0, mt, uf,
                                              0, self.mode_raw, 1 if self.repeat else 0])

    def _push_status(self) -> None:
        self._outbox.append(self._status_frame())

    def _push_play(self, raw: int) -> None:
        self.play_state = raw
        self._outbox.append(build_frame(FrameType.PLAY_STATE, [raw]))

    def finish_track(self) -> None:
        """Test hook: the current track has played to its end (next track, or stop after the last)."""
        d = self.discs.get(self.disc)
        if d and self.track < d.last:
            self.track += 1
            self._push_status()
            return
        # live-verified: the CD-425M goes on to the next occupied slot (status first, then search/load)
        slots = sorted(self.discs)
        nxt = next((s for s in slots if s > self.disc), slots[0])
        self._select(nxt, 1, True)

    def door_cycle(self, remove: list[int] = (), add: dict | None = None, open_s: float = 0.3) -> None:
        """Test hook, as measured live: 0x15 [01] door open -> discs changed -> 0x15 [00] door closed ->
        0x60 searching (disc detection) -> 0x40 stopped."""
        self._outbox.append(build_frame(FrameType.EVENT, [1]))

        def close():
            for slot in remove:
                self.discs.pop(slot, None)
            for slot, disc in (add or {}).items():
                self.discs[slot] = disc
            self._outbox.append(build_frame(FrameType.EVENT, [0]))
            self._push_play(0x60)
            self._after(0.5, lambda: self._push_play(0x40))
        self._after(open_s, close)

    def _after(self, delay: float, fn) -> None:
        self._timers.append((time.monotonic() + delay, fn))

    # ------------------------------------------------------------------ main loop
    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            for t, fn in [x for x in self._timers if x[0] <= now]:
                self._timers.remove((t, fn))
                fn()
            if self.held_key and now >= self._next_repeat:
                self._apply_key(self.held_key, repeat=True)
            m = self._next(0.02)
            if m is not None:
                self._handle(m)
                continue
            if self._outbox:
                self._send_unsolicited(self._outbox.popleft())

    def _handle(self, m) -> None:
        if self.ack_disabled:
            return
        if isinstance(m, Ctrl) and m.byte == ENQ:
            self._w(bytes([ACK]))
            self._pc_session()
        elif isinstance(m, Ctrl) and m.byte == EOT:
            self._w(bytes([ACK]))

    def _pc_session(self) -> None:
        """PC opened a session; receive frames until EOT or answer a request."""
        while True:
            m = self._next(8.0)
            if m is None:
                return
            if isinstance(m, BadFrame):
                self._w(bytes([NAK]))
                continue
            if isinstance(m, Ctrl):
                if m.byte == EOT:
                    self._w(bytes([ACK]))
                    return
                if m.byte == ENQ:
                    self._w(bytes([ACK]))
                continue
            self._w(bytes([ACK]))
            self.received.append(m)
            replies = self._process(m)
            if replies is not None:          # request: answer in the same session
                self._send_replies(replies)
                return

    def _wait_ack(self) -> bool:
        m = self._next(self.retry_interval)
        while m is not None and not (isinstance(m, Ctrl) and m.byte in (ACK, NAK, EOT)):
            m = self._next(self.retry_interval)
        return m is not None and isinstance(m, Ctrl) and m.byte == ACK

    def _send_with_retry(self, data: bytes) -> bool:
        for _ in range(self.retries):
            self._w(data)
            if self._wait_ack():
                return True
        return False

    def _send_replies(self, frames: list[bytes | tuple[float, bytes]]) -> None:
        for item in frames:
            if isinstance(item, tuple):
                time.sleep(item[0])
                item = item[1]
            if not self._send_with_retry(item):
                self._w(bytes([EOT]))
                return
        self._w(bytes([EOT]))
        self._wait_ack()

    def _send_unsolicited(self, frame: bytes) -> None:
        if not self._send_with_retry(bytes([ENQ])):
            return                             # PC never answered: status is lost (like the real one)
        if self._send_with_retry(frame):
            self._w(bytes([EOT]))
            self._wait_ack()

    # ------------------------------------------------------------------ request/command processing
    def _process(self, f: Frame) -> list | None:
        t, p = f.ftype, f.payload
        if t == FrameType.HELLO:
            for fr in (self._status_frame(), build_frame(FrameType.EVENT, [0]),
                       build_frame(FrameType.PLAY_STATE, [self.play_state]),
                       build_frame(FrameType.DISC_LOADED, [self.loaded & 0xFF, self.loaded >> 8])):
                self._outbox.append(fr)
            return [build_frame(FrameType.HELLO, f"I'm {self.model}".encode())]
        if t == FrameType.CMD:
            return self._process_cmd03(p)
        if t == FrameType.KEY:
            self._apply_key((p[0], p[1]))
        elif t == FrameType.SELECT:
            self._select(p[0] | p[1] << 8, p[2], bool(p[3]))
        elif t == FrameType.MODE:
            self.mode_raw = 0
            self._push_status()
        elif t == FrameType.TEXT:
            self._store_text(p)
        return None

    def _process_cmd03(self, p: bytes) -> list:
        a, b, disc, b4, b6, b7 = p[0], p[1], p[2] | p[3] << 8, p[4], p[5], p[6]
        if a == 0x80:
            return [build_frame(FrameType.RESULT, [0x01])]
        if a == 0x40:
            return [build_frame(FrameType.RESULT, [0x02])]
        if a in (0x10, 0x20):
            return [build_frame(FrameType.RESULT, [0x01])]
        d = self.discs.get(disc)
        dl = [disc & 0xFF, disc >> 8]
        if b == 0x02:
            if not d:
                return []
            loaded = disc == self.loaded
            return [build_frame(FrameType.MINMAX, dl + [1, d.last if loaded else 0x63, d.attr])]
        if b == 0x04:
            if not d or disc != self.loaded:
                return []                      # EOT only
            payload = dl + [1, d.attr, 1, d.last]
            for m, s in d.starts + [d.leadout]:
                payload += [_bcd(m), _bcd(s), 0]
            return [build_frame(FrameType.TOC, payload)]
        if b == 0x08:
            return [build_frame(FrameType.USER_FILES, dl + [d.user_files if d else 0])]
        if b == 0x10:
            return [build_frame(FrameType.MUSIC_TYPE, dl + [d.music_type if d else 0])]
        if b == 0x20:
            return [build_frame(FrameType.PROGRAM, [0])]
        if b == 0x01:
            return self._texts(disc, b6, b4)
        return []

    def _mem_frame(self, disc: int, idx: int, kind: int, text: str | None, attr: int,
                   uf: int = 0, mt: int = 0) -> bytes:
        body = text.encode("ascii", "replace")[:25] if text else b"\x01"
        return build_frame(FrameType.TEXT, [disc & 0xFF, disc >> 8, idx, uf, kind, mt, attr] + list(body))

    def _cdtext_frame(self, disc: int, n: int, text: str, attr: int, seq: int = 1) -> bytes:
        return build_frame(FrameType.CDTEXT, [disc & 0xFF, disc >> 8, n, 0, 1, 0, attr, seq]
                           + list(text.encode("ascii", "replace")))

    def _endless_empty_stream(self, disc: int, attr: int) -> list:
        """What the changer sends for a CD-TEXT disc without disc title: 70 empty frames (seq 1..70),
        ~1.75 s silence, then again, endlessly (live-measured, 15 cycles simulated)."""
        out: list = []
        for cycle in range(15):
            for seq in range(1, 71):
                fr = build_frame(FrameType.CDTEXT, [disc & 0xFF, disc >> 8, 0, 0, 1, 0, attr, seq, 0x01])
                out.append((1.75, fr) if (cycle and seq == 1) else fr)
        return out

    def _texts(self, disc: int, kind: int, track: int = 0) -> list:
        if kind == 7:
            return [self._mem_frame(0, 1 << (n - 1), 7, self.uf_names[n], 0) for n in range(1, 9)]
        if disc == 0:
            return [self._mem_frame(d.slot, 0, 0, d.memory_title, d.attr) for d in
                    sorted(self.discs.values(), key=lambda x: x.slot)]
        d = self.discs.get(disc)
        if not d:
            return []
        if disc == self.loaded and d.cdtext:
            if track:                                   # one track (P[4] = track number)
                if track in d.cdtext:
                    return [self._cdtext_frame(disc, track, d.cdtext[track], d.attr)]
                return []
            if 0 not in d.cdtext:                       # firmware bug: CD-TEXT without disc title
                return self._endless_empty_stream(disc, d.attr)
            out: list = []
            for n in sorted(d.cdtext):
                fr = self._cdtext_frame(disc, n, d.cdtext[n], d.attr)
                if self.cdtext_pause_after is not None and n == self.cdtext_pause_after + 1:
                    out.append((self.cdtext_pause, fr))
                else:
                    out.append(fr)
            return out
        frames = [self._mem_frame(disc, 0, 1, d.memory_title, d.attr, d.user_files, d.music_type)]
        for n in range(1, 21):
            frames.append(self._mem_frame(disc, n, 1, d.memory_tracks.get(n), d.attr,
                                          d.user_files, d.music_type))
        return frames

    def _store_text(self, p: bytes) -> None:
        disc, idx, uf, kind, mt = p[0] | p[1] << 8, p[2], p[3], p[4], p[5]
        raw = p[7:]
        text = None if raw == b"\x01" else raw.decode("ascii", "replace")[:25]
        if kind == 7:
            for n in range(8):
                if idx == 1 << n:
                    self.uf_names[n + 1] = text
            return
        d = self.discs.get(disc)
        if not d:
            return
        d.music_type, d.user_files = mt, uf
        if kind == 0:
            d.memory_title = text
        elif text is None:
            d.memory_tracks.pop(idx, None)
        else:
            d.memory_tracks[idx] = text
        if disc == self.disc:
            self._push_status()

    # ------------------------------------------------------------------ mechanics
    def _select(self, disc: int, track: int, play: bool) -> None:
        if disc not in self.discs:
            return
        self.disc, self.track = disc, track
        self._push_status()
        if disc == self.loaded:
            self._after(self.load_delay / 3, lambda: self._push_play(0x70 if play else 0x40))
            return
        self._after(self.load_delay * 0.6, lambda: self._push_play(0x60))

        def loaded() -> None:
            self.loaded = disc
            d = self.discs[disc]
            if d.cdtext:                       # the real changer overwrites memory titles on load
                d.memory_title = (d.cdtext.get(0) or "")[:25] or None
                d.memory_tracks = {n: t[:25] for n, t in d.cdtext.items() if 0 < n <= 20}
            self._outbox.append(build_frame(FrameType.DISC_LOADED, [disc & 0xFF, disc >> 8]))
            if play:
                self._push_play(0x70)
            else:
                self._push_play(0x50)
                self._after(0.05, lambda: self._push_play(0x40))
        self._after(self.load_delay, loaded)

    def _apply_key(self, key: tuple[int, int], repeat: bool = False) -> None:
        d = self.discs.get(self.disc)
        if key == (0xFF, 0xFF):
            if self.held_key in ((0xA0, 0x07), (0xA0, 0x06)):
                self._push_play(0x70)
            self.held_key = None
            return
        if key == (0xA0, 0xCB):
            self._push_play(0x80 if self.play_state == 0x70 else 0x70)
        elif key == (0xA0, 0xC9):
            self.track = 1
            self._push_status()
            self._push_play(0x50)
            self._after(0.05, lambda: self._push_play(0x40))
        elif key == (0xA0, 0xCC):
            self.repeat = not self.repeat
            self._push_status()
        elif key == (0xA1, 0xD4):
            self.mode_raw = {0: 1, 1: 2}.get(self.mode_raw, 0)
            self._push_status()
        elif key in ((0xA0, 0xCF), (0xA0, 0xCE)):
            if key == (0xA0, 0xCF) and d and self.track < d.last:
                self.track += 1
                self._push_status()
            elif key == (0xA0, 0xCE) and repeat and self.track > 1:
                self.track -= 1
                self._push_status()
            if not repeat:
                self.held_key = key
            self._next_repeat = time.monotonic() + 0.4
        elif key in ((0xA0, 0x07), (0xA0, 0x06)):
            if not repeat:
                self._push_play(0x90 if key == (0xA0, 0x07) else 0xA0)
                self.held_key = key
            self._next_repeat = time.monotonic() + 3600
