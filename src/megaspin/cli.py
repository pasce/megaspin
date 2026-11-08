"""Command line tool for the protocol core.

  python -m megaspin.cli --port COM4 status
  python -m megaspin.cli --port COM4 slots
  python -m megaspin.cli --port COM4 disc 150          # memory/CD-TEXT, MT, UF (no loading)
  python -m megaspin.cli --port COM4 read 150          # load + TOC + CD-TEXT
  python -m megaspin.cli --port COM4 play 150 3
  python -m megaspin.cli --port COM4 key next
  python -m megaspin.cli --port COM4 monitor 30
  python -m megaspin.cli --sim status                  # against the built-in simulator
"""
from __future__ import annotations

import argparse
import logging
import time

from .protocol.codec import hexs
from .protocol.constants import music_type_name
from .protocol.parsers import split_artist_album
from .protocol.service import ChangerService


def _service(args) -> tuple[ChangerService, object]:
    raw = None
    if args.raw:
        def raw(d, data, t):  # noqa: E306
            print(f"  {time.strftime('%H:%M:%S')} {d} {hexs(data)}")
    if args.sim:
        from .protocol.transport import pipe_pair
        from .sim.simulator import ChangerSimulator
        pc, ch = pipe_pair()
        sim = ChangerSimulator(ch).start()
        return ChangerService(pc, on_raw=raw), sim
    from .protocol.transport import SerialTransport
    return ChangerService(SerialTransport(args.port), on_raw=raw), None


def _print_status(s) -> None:
    print(f"Modell {s.model} | online {s.online} | Disc {s.disc} Track {s.track} | geladen {s.loaded_disc} | "
          f"{s.play_state} | Modus {s.mode} Random {s.random} Repeat {s.repeat} | "
          f"Genre {music_type_name(s.disc_music_type)} UF {s.disc_user_files:#04x}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="megaspin")
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--sim", action="store_true", help="use the built-in simulator")
    ap.add_argument("--raw", action="store_true", help="print raw bytes")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.v else logging.WARNING)
    svc, sim = _service(a)
    try:
        svc.start(hello=True)
        svc.wait_for(lambda s: s.loaded_disc != 0 and s.play_state != "unknown", 3)
        c, x = a.cmd, a.args
        if c == "status":
            _print_status(svc.status)
        elif c == "slots":
            for s in svc.read_slot_list():
                print(f"#{s.disc:3}  attr={s.attr:#04x}  {s.text if hasattr(s, 'text') else s.title or '* ' + s.marker}")
        elif c == "disc":
            d = int(x[0])
            texts, mt, uf = svc.read_memory(d)
            print(f"Disc {d}: Quelle {texts[0].source if texts else '-'}, Genre {music_type_name(mt)}, UF {uf:#04x}")
            for e in texts:
                print(f"  {e.track:2}  {e.text or '* ' + e.marker}")
        elif c == "read":
            d = int(x[0])
            r = svc.read_disc_full(d, progress=lambda m: print("  ..", m))
            if r.toc:
                print(f"TOC: {r.toc.track_count} Tracks, freedb {r.toc.freedb_id()}, Längen {r.toc.lengths()}")
            print(f"Texte ({r.text_source}):")
            for e in r.texts:
                print(f"  {e.track:2}  {e.text or '* ' + e.marker}")
            if r.texts:
                print("  Interpret/Album:", split_artist_album(r.texts[0].text))
        elif c == "play":
            svc.play(int(x[0]), int(x[1]) if len(x) > 1 else 1)
        elif c == "load":
            svc.load(int(x[0]))
        elif c == "key":
            svc.key(x[0], x[1] if len(x) > 1 else "tap")
        elif c == "monitor":
            svc.add_listener(lambda s, ch: (print("  geändert:", sorted(ch)), _print_status(s)))
            time.sleep(float(x[0]) if x else 30)
        else:
            ap.error(f"unknown command {c}")
        time.sleep(0.5)
        if c in ("play", "load", "key"):
            time.sleep(2)
            _print_status(svc.status)
        return 0
    finally:
        svc.stop()
        if sim:
            sim.stop()


if __name__ == "__main__":
    raise SystemExit(main())
