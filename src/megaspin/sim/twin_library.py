"""Library for the digital twin (`megaspin --sim`).

The simulator's discs are fictional. This module gives them their own library (a separate database
and cover folder under the data directory), so the real collection is neither shown nor changed in
simulator mode. The covers are drawn here; no image files are shipped.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..app.settings import data_dir
from ..data.db import Database

# slot: (artist, album, year, cover colour)
TWIN_ALBUMS: dict[int, tuple[str, str, int, tuple[int, int, int]]] = {
    5: ("Lena Marsh", "Paper Harbour", 2011, (46, 110, 128)),
    147: ("The Velvet Owls", "Night Market", 2016, (118, 52, 84)),
    148: ("Hollow Pines", "Glass Orchard", 2008, (58, 98, 62)),
    149: ("Dana Reyes", "Quiet Engines", 2019, (84, 92, 108)),
    150: ("Northline", "Live at Harbour Hall", 2001, (150, 52, 48)),
    151: ("Northline", "Live in Riverton", 1999, (42, 62, 110)),
}

SIZE = 600


def twin_dir() -> Path:
    return data_dir() / "simulator"


def make_cover(artist: str, album: str, color: tuple[int, int, int]) -> Image.Image:
    """A plain fictional cover: colour field, a disc motif and the names."""
    img = Image.new("RGB", (SIZE, SIZE), color)
    draw = ImageDraw.Draw(img)
    dark = tuple(int(c * 0.55) for c in color)
    draw.rectangle([0, SIZE * 0.62, SIZE, SIZE], fill=dark)
    cx, cy, r = SIZE * 0.5, SIZE * 0.38, SIZE * 0.22
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(235, 235, 235), width=10)
    draw.ellipse([cx - r * 0.28, cy - r * 0.28, cx + r * 0.28, cy + r * 0.28], fill=(235, 235, 235))
    font_big = ImageFont.load_default(size=52)
    font_small = ImageFont.load_default(size=36)
    _centered(draw, artist, SIZE * 0.70, font_big)
    _centered(draw, album, SIZE * 0.82, font_small)
    return img


def _centered(draw: ImageDraw.ImageDraw, text: str, y: float, font) -> None:
    # shrink the text until it fits the cover width
    size = font.size
    while size > 16:
        f = ImageFont.load_default(size=size)
        box = draw.textbbox((0, 0), text, font=f)
        if box[2] - box[0] <= SIZE * 0.9:
            break
        size -= 2
    f = ImageFont.load_default(size=size)
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((SIZE - (box[2] - box[0])) / 2, y), text, fill=(250, 250, 250), font=f)


def prepare() -> Path:
    """Create the twin library if needed and return its database path."""
    base = twin_dir()
    covers = base / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    db_path = base / "library.sqlite"
    db = Database(db_path)
    try:
        for slot, (artist, album, year, color) in TWIN_ALBUMS.items():
            cover = covers / f"{slot}.jpg"
            if not cover.exists():
                make_cover(artist, album, color).save(cover, "JPEG", quality=90)
            if not db.disc_row(slot).get("user_artist"):
                db.save_user(slot, artist=artist, album=album, year=year, music_type=None,
                             user_files=None, tracks={})
                db.set_cover(slot, str(cover), "user")
                # fictional names must not be looked up on MusicBrainz
                db.save_musicbrainz(slot, None, "none_selected")
    finally:
        db.close()
    return db_path
