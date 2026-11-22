"""Check for updates: the server decides whether a newer version exists (plaintext.at, PHP script).

Sent: the app version in the PHP format (0.1.0-beta2) and nothing else. No ID, no operating system.
The server does not log the IP address. The app opens only download addresses on the allowed list.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .. import __version__

UPDATE_URL = "https://plaintext.at/updates/index.php"
ABOUT_URL = "https://plaintext.at/megaspin/"
GITHUB_URL = "https://github.com/pasce/megaspin"
# links the app may open (the server's download link must be on one of these)
ALLOWED_PREFIXES = ("https://github.com/pasce/megaspin/", "https://plaintext.at/megaspin/")


class UpdateCheckError(Exception):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    latest: str
    url: str
    download: str
    update_available: bool


def allowed_link(url: str) -> bool:
    """Only https links on the allow list may be opened from the update check."""
    return isinstance(url, str) and url.startswith(ALLOWED_PREFIXES) and urlparse(url).scheme == "https"


def parse_response(data: dict) -> UpdateInfo:
    """Validate the answer of the server. Anything unexpected is an error, never a guess."""
    try:
        latest = str(data["latest"])
        url = str(data["url"])
        download = str(data["download"])
        available = data["update_available"]
    except (KeyError, TypeError) as e:
        raise UpdateCheckError(f"unexpected answer: {e}") from None
    if not isinstance(available, bool) or not latest:
        raise UpdateCheckError("unexpected answer")
    if not allowed_link(download) or not allowed_link(url):
        raise UpdateCheckError("download address not on the allow list")
    return UpdateInfo(latest, url, download, available)


def check_for_update(version: str = __version__, opener=urlopen, timeout: float = 6.0) -> UpdateInfo:
    """One request to the server. Raises UpdateCheckError when the check cannot be completed."""
    query = urlencode({"version": version})
    req = Request(f"{UPDATE_URL}?{query}", headers={"User-Agent": f"MegaSpin/{version}"})
    try:
        with opener(req, timeout=timeout) as r:
            raw = r.read(20000)
        data = json.loads(raw.decode("utf-8"))
    except UpdateCheckError:
        raise
    except Exception as e:                       # network, timeout, invalid JSON
        raise UpdateCheckError(str(e) or e.__class__.__name__) from None
    if not isinstance(data, dict):
        raise UpdateCheckError("unexpected answer")
    return parse_response(data)


def should_show_popup(info: UpdateInfo, dismissed: str) -> bool:
    """The popup appears once per new version: after 'Cancel' only the icon remains until a newer version comes."""
    return info.update_available and info.latest != dismissed
