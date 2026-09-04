import pytest
from unittest.mock import patch, MagicMock
from select_to_speech.system_check import (
    check_system_dependencies,
    get_audio_devices,
    main_audio_devices,
)


def test_check_system_dependencies_all_present():
    """Test when all required, optional, and OCR packages are present"""
    def fake_which(cmd):
        return f"/usr/bin/{cmd}"
    
    with patch("select_to_speech.system_check.shutil.which", side_effect=fake_which), \
         patch("select_to_speech.system_check.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="List of available languages (2):\neng\nita\n")
        assert check_system_dependencies() is True


def test_check_system_dependencies_missing_ocr_warns():
    """Test when OCR dependencies are missing (should still return True if required wl-paste is found)"""
    def fake_which(cmd):
        if cmd == "wl-paste":
            return "/usr/bin/wl-paste"
        return None
        
    with patch("select_to_speech.system_check.shutil.which", side_effect=fake_which):
        assert check_system_dependencies() is True


def test_check_system_dependencies_missing_required_fails():
    """Test when required wl-paste is missing (should return False)"""
    def fake_which(cmd):
        return None
        
    with patch("select_to_speech.system_check.shutil.which", side_effect=fake_which):
        assert check_system_dependencies() is False


def test_check_system_dependencies_windows():
    """On Windows, core dependencies should pass natively and check tesseract/Snipping Tool."""
    import sys
    with patch.object(sys, "platform", "win32"), \
         patch("select_to_speech.system_check._find_tesseract_cmd", return_value="C:\\Program Files\\Tesseract-OCR\\tesseract.exe"), \
         patch("select_to_speech.system_check.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="List of available languages (2):\neng\nita\n")
        assert check_system_dependencies() is True


def test_detect_language_and_multilingual_check():
    """Test language detection and explicit overrides (`en`, `it`, `fr`, `es`, default fallback)."""
    from select_to_speech.system_check import _detect_language
    assert _detect_language("it") == "it"
    assert _detect_language("fr_FR.UTF-8") == "fr"
    assert _detect_language("es_ES") == "es"
    assert _detect_language("de_DE") == "en"

    def fake_which(cmd):
        return f"/usr/bin/{cmd}"

    with patch("select_to_speech.system_check.shutil.which", side_effect=fake_which), \
         patch("select_to_speech.system_check.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="List of available languages (2):\neng\nita\n")
        assert check_system_dependencies(lang="fr") is True
        assert check_system_dependencies(lang="es") is True


def test_get_audio_devices_without_default_output_device():
    """Audio listing should still work when the system has no default output device."""
    mock_pyaudio = MagicMock()
    mock_pyaudio.get_default_output_device_info.side_effect = OSError("No Default Output Device Available")
    mock_pyaudio.get_device_count.return_value = 2
    mock_pyaudio.get_device_info_by_index.side_effect = [
        {
            "name": "Input only",
            "maxOutputChannels": 0,
            "defaultSampleRate": 44100,
        },
        {
            "name": "USB speakers",
            "maxOutputChannels": 2,
            "defaultSampleRate": 48000,
        },
    ]

    with patch("select_to_speech.system_check.pyaudio") as mock_pyaudio_module:
        mock_pyaudio_module.PyAudio.return_value = mock_pyaudio

        assert get_audio_devices() == [
            {
                "id": 1,
                "name": "USB speakers",
                "channels": 2,
                "sample_rate": 48000,
                "is_default": False,
            }
        ]

    mock_pyaudio.terminate.assert_called_once()


def test_get_audio_devices_when_pyaudio_cannot_initialize():
    """Headless CI runners may have no usable ALSA/PulseAudio backend."""
    with patch("select_to_speech.system_check.pyaudio") as mock_pyaudio_module:
        mock_pyaudio_module.PyAudio.side_effect = OSError("No audio backend")

        assert get_audio_devices() == []


def test_main_audio_devices_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main_audio_devices(["--help"])

    assert exc_info.value.code == 0
    assert "List Select-to-Speech audio output devices" in capsys.readouterr().out
