from unittest.mock import patch, MagicMock
import pytest
from select_to_speech import voice_manager

def test_download_kokoro_cli_already_installed():
    with patch("select_to_speech.voice_manager.is_kokoro_installed", return_value=True), \
         patch("builtins.print") as mock_print:
        voice_manager.download_kokoro_cli()
        mock_print.assert_called_with("Kokoro model files are already installed.")

def test_download_kokoro_cli_success():
    with patch("select_to_speech.voice_manager.is_kokoro_installed", return_value=False), \
         patch("select_to_speech.voice_manager.download_kokoro", return_value=True) as mock_download, \
         patch("builtins.print") as mock_print:
        voice_manager.download_kokoro_cli()
        mock_download.assert_called_once()
        mock_print.assert_any_call("✓ Kokoro model files downloaded successfully!")

def test_download_kokoro_cli_failure():
    with patch("select_to_speech.voice_manager.is_kokoro_installed", return_value=False), \
         patch("select_to_speech.voice_manager.download_kokoro", return_value=False) as mock_download, \
         patch("builtins.print") as mock_print, \
         pytest.raises(SystemExit) as excinfo:
        voice_manager.download_kokoro_cli()
    assert excinfo.value.code == 1
    mock_download.assert_called_once()
    mock_print.assert_any_call("✗ Failed to download Kokoro model files.")

def test_download_kokoro_cli_keyboard_interrupt():
    with patch("select_to_speech.voice_manager.is_kokoro_installed", return_value=False), \
         patch("select_to_speech.voice_manager.download_kokoro", side_effect=KeyboardInterrupt) as mock_download, \
         patch("builtins.print") as mock_print, \
         pytest.raises(SystemExit) as excinfo:
        voice_manager.download_kokoro_cli()
    assert excinfo.value.code == 1
    mock_download.assert_called_once()
    mock_print.assert_any_call("\n✗ Download interrupted by user.")
