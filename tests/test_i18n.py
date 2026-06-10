import sys
from pathlib import Path

# Add src to python path dynamically
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from select_to_speech.i18n import _, set_language


def test_translation_italian():
    # Set to Italian and check if translation is correct
    set_language("it")
    assert _("Select-to-Speech — Settings") == "Select-to-Speech — Impostazioni"
    assert _("Engine") == "Motore"


def test_translation_english():
    # Set to English and check if translation returns original English string
    set_language("en")
    assert _("Select-to-Speech — Settings") == "Select-to-Speech — Settings"
    assert _("Engine") == "Engine"
