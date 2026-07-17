import pytest
from unittest.mock import patch, MagicMock
from select_to_speech.system_check import check_system_dependencies


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
