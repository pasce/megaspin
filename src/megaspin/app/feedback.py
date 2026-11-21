"""Feedback form on plaintext.at: the link opens the page in the browser, the app sends no data itself."""
from __future__ import annotations

from urllib.parse import urlencode

from .. import __version__

FEEDBACK_URLS = {
    "de": "https://plaintext.at/de/kontakt/",
    "en": "https://plaintext.at/contact/",
}
SOURCE = "megaspin"


def feedback_url(language: str, version: str = __version__) -> str:
    """Form address for the active language (any unknown language uses English)."""
    base = FEEDBACK_URLS.get(language, FEEDBACK_URLS["en"])
    return f"{base}?{urlencode({'source': SOURCE, 'version': version})}"
