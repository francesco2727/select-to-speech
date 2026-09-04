"""Unit tests for OcrEngine on Linux and Windows."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from select_to_speech.ocr_engine import OcrEngine, _find_windows_tesseract


def test_ocr_engine_init_and_custom_cmd():
    engine = OcrEngine(default_languages="ita+eng", tesseract_cmd="/custom/tesseract")
    assert engine.default_languages == "ita+eng"
    assert engine.get_tesseract_cmd() == "/custom/tesseract"
    assert engine.is_available() is True


def test_find_windows_tesseract_on_path():
    with patch("select_to_speech.ocr_engine.shutil.which", return_value="C:\\tools\\tesseract.exe"):
        assert _find_windows_tesseract() == "C:\\tools\\tesseract.exe"


def test_find_windows_tesseract_in_program_files():
    with patch("select_to_speech.ocr_engine.shutil.which", return_value=None), \
         patch.dict("os.environ", {"ProgramFiles": "C:\\Program Files"}), \
         patch("pathlib.Path.is_file", autospec=True) as mock_is_file, \
         patch("os.access", return_value=True):
        
        mock_is_file.side_effect = lambda self: "Program Files/Tesseract-OCR/tesseract.exe" in str(self).replace("\\", "/")
        res = _find_windows_tesseract()
        assert res is not None
        assert "tesseract.exe" in res.lower()


def test_find_windows_tesseract_not_found():
    with patch("select_to_speech.ocr_engine.shutil.which", return_value=None), \
         patch.dict("os.environ", {}, clear=True), \
         patch("pathlib.Path.is_file", return_value=False):
        assert _find_windows_tesseract() is None


def test_ocr_engine_is_available_linux():
    engine = OcrEngine()
    with patch.object(sys, "platform", "linux"), \
         patch("select_to_speech.ocr_engine.shutil.which", return_value="/usr/bin/tesseract"):
        assert engine.get_tesseract_cmd() == "/usr/bin/tesseract"
        assert engine.is_available() is True

    with patch.object(sys, "platform", "linux"), \
         patch("select_to_speech.ocr_engine.shutil.which", return_value=None):
        assert engine.get_tesseract_cmd() is None
        assert engine.is_available() is False


def test_ocr_engine_is_available_windows():
    engine = OcrEngine()
    with patch.object(sys, "platform", "win32"), \
         patch("select_to_speech.ocr_engine._find_windows_tesseract", return_value="C:\\Program Files\\Tesseract-OCR\\tesseract.exe"):
        assert engine.get_tesseract_cmd() == "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        assert engine.is_available() is True


def test_get_available_languages_success():
    engine = OcrEngine(tesseract_cmd="/usr/bin/tesseract")
    with patch("select_to_speech.ocr_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="List of available languages (3):\neng\nita\nosd\n",
        )
        langs = engine.get_available_languages()
        assert langs == {"eng", "ita"}
        mock_run.assert_called_once_with(
            ["/usr/bin/tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=3,
        )


def test_get_available_languages_unavailable():
    engine = OcrEngine()
    with patch.object(engine, "get_tesseract_cmd", return_value=None):
        assert engine.get_available_languages() == set()


def test_resolve_lang_flag():
    engine = OcrEngine(tesseract_cmd="/usr/bin/tesseract")
    with patch.object(engine, "get_available_languages", return_value={"eng", "ita", "fra"}):
        assert engine._resolve_lang_flag("ita+eng") == "ita+eng"
        assert engine._resolve_lang_flag("deu") == "eng"  # fallback to eng
    with patch.object(engine, "get_available_languages", return_value={"ita"}):
        assert engine._resolve_lang_flag("deu") == "ita"  # fallback to ita
    with patch.object(engine, "get_available_languages", return_value={"jpn"}):
        assert engine._resolve_lang_flag("deu") == "jpn"  # fallback to first available
    with patch.object(engine, "get_available_languages", return_value=set()):
        assert engine._resolve_lang_flag("ita+eng") is None


def test_extract_text_not_available():
    engine = OcrEngine()
    with patch.object(engine, "get_tesseract_cmd", return_value=None):
        assert engine.extract_text("non_existent.png") == ""


def test_extract_text_file_not_found(tmp_path):
    engine = OcrEngine(tesseract_cmd="/usr/bin/tesseract")
    missing_file = tmp_path / "missing.png"
    assert engine.extract_text(missing_file) == ""


def test_extract_text_success(tmp_path):
    img_file = tmp_path / "test.png"
    img_file.write_bytes(b"dummy")

    engine = OcrEngine(tesseract_cmd="/usr/bin/tesseract")
    with patch.object(engine, "get_available_languages", return_value={"eng", "ita"}), \
         patch("select_to_speech.ocr_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="  Recognized sample text  \n")
        res = engine.extract_text(img_file, languages="ita+eng")
        assert res == "Recognized sample text"
        mock_run.assert_called_once_with(
            ["/usr/bin/tesseract", str(img_file), "stdout", "-l", "ita+eng"],
            capture_output=True,
            text=True,
            timeout=15,
        )


def test_extract_text_timeout_and_error(tmp_path):
    img_file = tmp_path / "test.png"
    img_file.write_bytes(b"dummy")

    engine = OcrEngine(tesseract_cmd="/usr/bin/tesseract")
    with patch.object(engine, "get_available_languages", return_value={"eng"}), \
         patch("select_to_speech.ocr_engine.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="tesseract", timeout=15)):
        assert engine.extract_text(img_file) == ""

    with patch.object(engine, "get_available_languages", return_value={"eng"}), \
         patch("select_to_speech.ocr_engine.subprocess.run", side_effect=RuntimeError("Subprocess failed")):
        assert engine.extract_text(img_file) == ""
