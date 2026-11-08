"""User settings (JSON in the platform config directory)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP = "megaspin"
log = logging.getLogger(__name__)


def config_dir() -> Path:
    p = Path(user_config_dir(APP, appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    p = Path(user_data_dir(APP, appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class Settings:
    port: str = ""
    auto_connect: bool = True
    theme: str = "dark"
    accent: str = "#E04848"
    window_geometry: str = ""
    window_state: str = ""
    mb_enabled: bool = True          # MusicBrainz/Cover Art Archive (titles + covers only)
    mb_contact: str = ""             # optional contact for the MusicBrainz User-Agent
    sort: str = "artist"
    group_by: str = "none"
    extra: dict = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except FileNotFoundError:
            return cls()
        except Exception:
            log.exception("settings unreadable, using defaults")
            return cls()

    def save(self) -> None:
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(self.path())
