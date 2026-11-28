from unittest.mock import patch, MagicMock

from select_to_speech.ocr_engine import OcrEngine


def test_missing_tesseract_is_not_ready():
    engine = OcrEngine()
    with patch("select_to_speech.ocr_engine.shutil.which", return_value=None):
        assert engine.get_available_languages() == set()
        assert not engine.is_ready()


def test_empty_result_is_not_cached():
    engine = OcrEngine()
    with patch("select_to_speech.ocr_engine.shutil.which", return_value=None):
        engine.get_available_languages()
    listing = MagicMock(
        returncode=0, stdout="List of available languages (3):\neng\nita\nosd\n"
    )
    with (
        patch(
            "select_to_speech.ocr_engine.shutil.which",
            return_value="/usr/bin/tesseract",
        ),
        patch("select_to_speech.ocr_engine.subprocess.run", return_value=listing),
    ):
        assert engine.get_available_languages() == {"eng", "ita"}
        assert engine.is_ready()
