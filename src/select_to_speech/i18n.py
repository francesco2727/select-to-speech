"""Internationalisation support for select-to-speech using gettext."""

import gettext
import locale
import os
from pathlib import Path
from typing import Callable

SUPPORTED_LANGUAGES = ("en", "it", "es", "fr")
_LOCALE_DIR = Path(__file__).parent / "locale"

def compile_translations() -> None:
    """Compile all .po files to .mo files if they are missing or outdated."""
    import subprocess
    import shutil

    msgfmt = shutil.which("msgfmt")
    if not msgfmt:
        return

    for lang in SUPPORTED_LANGUAGES:
        po_path = _LOCALE_DIR / lang / "LC_MESSAGES" / "select_to_speech.po"
        mo_path = _LOCALE_DIR / lang / "LC_MESSAGES" / "select_to_speech.mo"
        if po_path.exists():
            if not mo_path.exists() or po_path.stat().st_mtime > mo_path.stat().st_mtime:
                try:
                    mo_path.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run(
                        [msgfmt, "-o", str(mo_path), str(po_path)],
                        check=True,
                        capture_output=True,
                    )
                except Exception:
                    pass


# Compile translations on import to ensure .mo files are up-to-date
compile_translations()

# Module-level translation function — replaced by set_language()
_current: gettext.GNUTranslations | gettext.NullTranslations = gettext.NullTranslations()


def detect_system_language() -> str:
    """Return the best supported language code based on the system locale."""
    for env_var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(env_var, "")
        if val:
            code = val.split(".")[0].split("_")[0].lower()
            if code in SUPPORTED_LANGUAGES:
                return code
    try:
        loc = locale.getlocale()[0] or ""
        code = loc.split("_")[0].lower()
        if code in SUPPORTED_LANGUAGES:
            return code
    except Exception:
        pass
    return "en"


def set_language(lang: str) -> None:
    """Activate translations for *lang* (e.g. ``"it"``, ``"en"``)."""
    global _current
    if lang == "auto":
        lang = detect_system_language()
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"
    _current = gettext.translation(
        "select_to_speech",
        localedir=str(_LOCALE_DIR),
        languages=[lang],
        fallback=True,
    )


def _(message: str) -> str:
    """Translate *message* using the active language."""
    return _current.gettext(message)


def get_translate_func() -> Callable[[str], str]:
    """Return the current ``_()`` callable (useful for deferred lookups)."""
    return _


# Initialise with the system language on first import
set_language("auto")
