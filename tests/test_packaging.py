"""Consistency checks between the app code and the packaging scripts."""

import re
from pathlib import Path

from select_to_speech.main import _LINGUA_LANGUAGES

ROOT = Path(__file__).resolve().parent.parent


def test_slim_lingua_build_covers_all_detectable_languages():
    """packaging/build-lingua.sh must embed a model for every language main.py can detect.

    A language missing from the slim build would not exist in the lingua.Language enum,
    so main.py would fail at import time in the packaged binary.
    """
    script = (ROOT / "packaging" / "build-lingua.sh").read_text()
    match = re.search(r"^LANGUAGES=\(([^)]*)\)", script, re.MULTILINE)
    assert match, "LANGUAGES=(...) not found in build-lingua.sh"
    built = set(match.group(1).split())
    needed = {lang.name.lower() for lang in _LINGUA_LANGUAGES.values()}
    assert built == needed
