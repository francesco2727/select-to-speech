import pytest
from select_to_speech.loanword_detector import _is_english_loanword, segment_with_loanwords

def test_is_english_loanword_curated():
    assert _is_english_loanword("python") is True
    assert _is_english_loanword("Python") is True
    assert _is_english_loanword("DOCKER") is True
    assert _is_english_loanword("kubernetes") is True

def test_is_english_loanword_camelcase():
    assert _is_english_loanword("GitHub") is True
    assert _is_english_loanword("TypeScript") is True
    assert _is_english_loanword("JavaScript") is True
    assert _is_english_loanword("WebSocket") is True
    # Should match if it's in curated, regardless of case
    assert _is_english_loanword("Github") is True
    assert _is_english_loanword("typescript") is True

    # Check a word NOT in curated but matching CamelCase
    assert _is_english_loanword("MyNewTool") is True
    assert _is_english_loanword("myNewTool") is False # Starts with lowercase

def test_is_english_loanword_acronyms():
    assert _is_english_loanword("API") is True
    assert _is_english_loanword("HTTP") is True
    assert _is_english_loanword("CPU") is True
    assert _is_english_loanword("A") is False # Single letter
    assert _is_english_loanword("AI") is True

def test_is_english_loanword_negative():
    assert _is_english_loanword("hola") is False
    assert _is_english_loanword("casa") is False
    assert _is_english_loanword("mundo") is False

def test_segment_with_loanwords_english_dominant():
    text = "This is already English."
    result = segment_with_loanwords(text, "en")
    assert result == [(text, "en", None)]

def test_segment_with_loanwords_no_loanwords():
    text = "Hola mundo, ¿cómo estás?"
    result = segment_with_loanwords(text, "es")
    assert result == [(text, "es", None)]

def test_segment_with_loanwords_single_loanword():
    text = "Uso python para programar."
    # "Uso " (None), "python" (en), " para programar." (None)
    result = segment_with_loanwords(text, "es")
    assert len(result) == 3
    assert result[0] == ("Uso ", "es", None)
    assert result[1] == ("python", "es", "en")
    assert result[2] == (" para programar.", "es", None)

def test_segment_with_loanwords_multiple_loanwords():
    text = "Uso python y docker."
    # "Uso " (None), "python" (en), " y " (None), "docker" (en), "." (None)
    result = segment_with_loanwords(text, "es")
    assert len(result) == 5
    assert result[1] == ("python", "es", "en")
    assert result[3] == ("docker", "es", "en")

def test_segment_with_loanwords_merging():
    # "python" is en, " " is None, "docker" is en.
    # Wait, the code says:
    # "Non-word characters (spaces, punctuation) before this word" -> None
    # So "python docker" -> "python" (en), " " (None), "docker" (en)
    # They won't be merged if the space is None.

    # Let's check the code:
    # for match in re.finditer(r"\b\w[\w'-]*\b", text):
    #   if start > last_end: raw.append((text[last_end:start], dominant_lang, None))
    #   phoneme = "en" if _is_english_loanword(word) else None
    #   raw.append((word, dominant_lang, phoneme))

    # So "python docker":
    # 1. "python" -> raw: [("python", "es", "en")]
    # 2. " " -> start=7, last_end=6? No, word="python" starts at 0, ends at 6.
    # Next match is "docker" at start=7, end=13.
    # start (7) > last_end (6) -> raw.append((" ", "es", None))
    # raw.append(("docker", "es", "en"))
    # raw = [("python", "es", "en"), (" ", "es", None), ("docker", "es", "en")]
    # Merging only merges consecutive segments with SAME phoneme_lang.
    # "en" != None, so they are NOT merged.

    # What about consecutive English words if they were separated by something that IS a word but ALSO English?
    # Actually, if we have "GitHub API", both are "en".
    # "GitHub" (en), " " (None), "API" (en). Still not merged because of space.

    # Wait, if I have "GitHubAPI" (not a word usually but if it matches CamelCase):
    # If the regex matches it as one word, it's one segment.

    # What if two things in a row get `phoneme = None`?
    # "Hola mundo" -> "Hola" (None), " " (None), "mundo" (None) -> Merged into one segment "Hola mundo" (None).

    text = "Hola mundo"
    result = segment_with_loanwords(text, "es")
    assert len(result) == 1
    assert result[0] == ("Hola mundo", "es", None)

def test_segment_with_loanwords_consecutive_loanwords_no_space():
    # This might be hard to achieve with word boundaries \b
    # But maybe "python-docker"? \b\w[\w'-]*\b matches "python-docker" as one word.
    # _is_english_loanword("python-docker")? "python-docker" is not in curated (unless it is).
    # It's not CamelCase.
    pass

def test_segment_with_loanwords_punctuation():
    text = "Python!"
    result = segment_with_loanwords(text, "es")
    assert len(result) == 2
    assert result[0] == ("Python", "es", "en")
    assert result[1] == ("!", "es", None)

def test_segment_with_loanwords_empty():
    assert segment_with_loanwords("", "es") == [("", "es", None)]
    assert segment_with_loanwords("   ", "es") == [("   ", "es", None)]
    assert segment_with_loanwords("!!!", "es") == [("!!!", "es", None)]
