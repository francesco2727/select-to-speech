"""Unit tests for text normalization and neural punctuation restoration."""

import pytest
from select_to_speech.text_normalizer import (
    dehyphenate,
    normalize_bullets_and_lists,
    unwrap_lines,
    normalize_text_for_tts,
)


def test_dehyphenate():
    # Regular hyphenation across linebreaks
    raw = "Questa è una parola spez-\nzata in due parti."
    expected = "Questa è una parola spezzata in due parti."
    assert dehyphenate(raw) == expected

    # With trailing spaces and carriage return
    raw2 = "Il com-  \r\n puter funziona bene."
    expected2 = "Il computer funziona bene."
    assert dehyphenate(raw2) == expected2

    # Words with hyphenated compounds should not break if not on newline
    raw3 = "Un approccio state-of-the-art"
    assert dehyphenate(raw3) == raw3


def test_normalize_bullets_and_lists():
    raw = """Ecco la lista:
• Primo elemento
* Secondo elemento
- Terzo elemento
1. Quarto elemento con punto."""
    res = normalize_bullets_and_lists(raw)
    lines = res.splitlines()
    assert lines[0] == "Ecco la lista:"
    assert lines[1] == "Primo elemento."
    assert lines[2] == "Secondo elemento."
    assert lines[3] == "Terzo elemento."
    assert lines[4] == "Quarto elemento con punto."


def test_unwrap_lines():
    # Soft wrap terminal text
    raw = """Questo è un paragrafo che va
a capo su più righe
perché la finestra è stretta

Questo è il secondo paragrafo."""
    res = unwrap_lines(raw)
    paragraphs = res.split("\n\n")
    assert len(paragraphs) == 2
    assert paragraphs[0] == "Questo è un paragrafo che va a capo su più righe perché la finestra è stretta."
    assert paragraphs[1] == "Questo è il secondo paragrafo."


def test_normalize_text_for_tts_pipeline():
    raw = """Capitolo 1: Intro-
duzione

Questo testo proviene da un docu-
mento PDF a colonne.
• Punto A
• Punto B"""

    res = normalize_text_for_tts(raw)
    assert "Introduzione." in res
    assert "documento PDF a colonne." in res
    assert "Punto A." in res
    assert "Punto B." in res
