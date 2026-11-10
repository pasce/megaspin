"""Language support (Qt translation files).

All user-visible texts are written in English in the source code and wrapped in ``tr()``.
German (and every other language) lives in ``translations/megaspin_<code>.ts`` (source for translators,
edited with Qt Linguist or any text editor) and ``translations/megaspin_<code>.qm`` (compiled, loaded at start).

Language choice: Settings → Language (Auto / English / Deutsch). "Auto" follows the system language.
A change takes effect after restarting MegaSpin.

Importing this module does not need a running application. Texts are only translated after a
QApplication with the translator is created, so UI modules must be imported after that
(see ``megaspin.__main__``).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator

CONTEXT = "MegaSpin"            # one context for all texts (see tools/update_translations.py)
DEFAULT_LANGUAGE = "en"
_DIR = Path(__file__).resolve().parent / "translations"
# Names shown in the language menu. A language appears automatically once its megaspin_<code>.qm exists.
NAMES = {"en": "English", "de": "Deutsch", "fr": "Français", "es": "Español", "it": "Italiano",
         "nl": "Nederlands", "pl": "Polski", "cs": "Čeština", "sv": "Svenska", "pt": "Português"}


def available() -> dict[str, str]:
    """Code -> name for English and every language with a compiled translation file."""
    langs = {DEFAULT_LANGUAGE: NAMES[DEFAULT_LANGUAGE]}
    for qm in sorted(_DIR.glob("megaspin_*.qm")):
        code = qm.stem.removeprefix("megaspin_")
        langs[code] = NAMES.get(code, code)
    return langs
_translator: QTranslator | None = None
_active = DEFAULT_LANGUAGE


def tr(text: str) -> str:
    """Translate a source text (English) into the active language."""
    return QCoreApplication.translate(CONTEXT, text)


def system_language() -> str:
    code = QLocale.system().name().split("_")[0]
    return code if code in available() else DEFAULT_LANGUAGE


def resolve(setting: str | None) -> str:
    """'auto' or empty -> system language; unknown codes -> English."""
    if not setting or setting == "auto":
        return system_language()
    return setting if setting in available() else DEFAULT_LANGUAGE


def apply(app: QCoreApplication, setting: str | None) -> str:
    """Install the translator for the chosen language. Returns the language code in use."""
    global _translator, _active
    if _translator is not None:
        app.removeTranslator(_translator)
        _translator = None
    code = resolve(setting)
    if code != DEFAULT_LANGUAGE:
        translator = QTranslator(app)
        if translator.load(str(_DIR / f"megaspin_{code}.qm")) and app.installTranslator(translator):
            _translator = translator
        else:
            code = DEFAULT_LANGUAGE
    _active = code
    return code


def active() -> str:
    return _active
