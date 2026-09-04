"""Unit tests for ScreenCapture on Linux and Windows."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from select_to_speech.screen_capture import (
    ScreenCapture,
    _capture_region_windows_snipping_tool,
    _capture_region_windows_tk_overlay,
)


def test_is_spectacle_available():
    with patch("select_to_speech.screen_capture.shutil.which", return_value="/usr/bin/spectacle"):
        assert ScreenCapture.is_spectacle_available() is True
    with patch("select_to_speech.screen_capture.shutil.which", return_value=None):
        assert ScreenCapture.is_spectacle_available() is False


def test_is_grim_slurp_available():
    def fake_which(cmd):
        if cmd in ("grim", "slurp"):
            return f"/usr/bin/{cmd}"
        return None

    with patch("select_to_speech.screen_capture.shutil.which", side_effect=fake_which):
        assert ScreenCapture.is_grim_slurp_available() is True

    with patch("select_to_speech.screen_capture.shutil.which", return_value=None):
        assert ScreenCapture.is_grim_slurp_available() is False


def test_is_windows_capture_available():
    with patch.object(sys, "platform", "win32"):
        assert ScreenCapture.is_windows_capture_available() is True
    with patch.object(sys, "platform", "linux"):
        assert ScreenCapture.is_windows_capture_available() is False


def test_capture_region_linux_spectacle_success(tmp_path):
    out_file = tmp_path / "out.png"

    def fake_run(cmd, capture_output, text, timeout):
        # Simulate spectacle writing output
        out_file.write_bytes(b"image-data")
        return MagicMock(returncode=0)

    with patch.object(sys, "platform", "linux"), \
         patch.object(ScreenCapture, "is_spectacle_available", return_value=True), \
         patch("select_to_speech.screen_capture.subprocess.run", side_effect=fake_run):
        assert ScreenCapture.capture_region(out_file) is True
        assert out_file.exists()


def test_capture_region_linux_spectacle_failure_fallback(tmp_path):
    out_file = tmp_path / "out.png"

    with patch.object(sys, "platform", "linux"), \
         patch.object(ScreenCapture, "is_spectacle_available", return_value=True), \
         patch.object(ScreenCapture, "is_grim_slurp_available", return_value=False), \
         patch("select_to_speech.screen_capture.subprocess.run", return_value=MagicMock(returncode=1)):
        assert ScreenCapture.capture_region(out_file) is False


def test_capture_region_linux_grim_slurp_success(tmp_path):
    out_file = tmp_path / "out.png"

    def fake_run(cmd, capture_output, text, timeout):
        if cmd == ["slurp"]:
            return MagicMock(returncode=0, stdout="10,20 100x200")
        if cmd[0] == "grim":
            out_file.write_bytes(b"grim-image")
            return MagicMock(returncode=0)
        return MagicMock(returncode=1)

    with patch.object(sys, "platform", "linux"), \
         patch.object(ScreenCapture, "is_spectacle_available", return_value=False), \
         patch.object(ScreenCapture, "is_grim_slurp_available", return_value=True), \
         patch("select_to_speech.screen_capture.subprocess.run", side_effect=fake_run):
        assert ScreenCapture.capture_region(out_file) is True
        assert out_file.exists()


def test_capture_region_linux_no_tool(tmp_path):
    out_file = tmp_path / "out.png"
    with patch.object(sys, "platform", "linux"), \
         patch.object(ScreenCapture, "is_spectacle_available", return_value=False), \
         patch.object(ScreenCapture, "is_grim_slurp_available", return_value=False):
        assert ScreenCapture.capture_region(out_file) is False


def test_capture_region_windows_snipping_tool_success(tmp_path):
    out_file = tmp_path / "out.png"
    mock_image = MagicMock()
    
    def fake_save(path, fmt):
        out_file.write_bytes(b"snipped")

    mock_image.save = fake_save

    mock_pil = MagicMock()
    mock_imagegrab = MagicMock()
    mock_imagegrab.grabclipboard.side_effect = [None, mock_image]
    mock_pil.ImageGrab = mock_imagegrab
    mock_pil.Image = MagicMock()
    mock_pil.Image.Image = type(mock_image)

    with patch("select_to_speech.screen_capture.shutil.which", return_value="C:\\Windows\\System32\\SnippingTool.exe"), \
         patch("select_to_speech.screen_capture.subprocess.Popen"), \
         patch.dict("sys.modules", {"PIL": mock_pil, "PIL.ImageGrab": mock_imagegrab, "PIL.Image": mock_pil.Image}), \
         patch("select_to_speech.screen_capture.time.sleep", return_value=None):
        
        res = _capture_region_windows_snipping_tool(out_file)
        assert res is True
        assert out_file.exists()


def test_capture_region_windows_dispatch_snipping_success(tmp_path):
    out_file = tmp_path / "out.png"
    with patch.object(sys, "platform", "win32"), \
         patch("select_to_speech.screen_capture._capture_region_windows_snipping_tool", return_value=True):
        assert ScreenCapture.capture_region(out_file) is True


def test_capture_region_windows_dispatch_tk_overlay_fallback(tmp_path):
    out_file = tmp_path / "out.png"
    with patch.object(sys, "platform", "win32"), \
         patch("select_to_speech.screen_capture._capture_region_windows_snipping_tool", return_value=False), \
         patch("select_to_speech.screen_capture._capture_region_windows_tk_overlay", return_value=True):
        assert ScreenCapture.capture_region(out_file) is True


def test_capture_region_windows_dispatch_all_fail(tmp_path):
    out_file = tmp_path / "out.png"
    with patch.object(sys, "platform", "win32"), \
         patch("select_to_speech.screen_capture._capture_region_windows_snipping_tool", return_value=False), \
         patch("select_to_speech.screen_capture._capture_region_windows_tk_overlay", return_value=False):
        assert ScreenCapture.capture_region(out_file) is False
