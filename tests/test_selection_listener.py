import pytest
from unittest.mock import MagicMock, patch
import subprocess
import time


from select_to_speech.selection_listener import WaylandSelectionListener


def _make_listener(**kwargs) -> WaylandSelectionListener:
    """Create a listener with xclip assumed available (default for tests)."""
    listener = WaylandSelectionListener(on_selection_change=kwargs.get("callback", MagicMock()))
    listener._xclip_available = kwargs.get("xclip_available", True)
    return listener


def _result(text: str = "", returncode: int = 0) -> MagicMock:
    return MagicMock(returncode=returncode, stdout=text)


# ---- Basic selection ------------------------------------------------

@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_gets_text(mock_run):
    # Wayland returns new text; x11 primary stale; clipboard stale.
    mock_run.side_effect = [
        _result("hello world"),       # wl-paste --primary
        _result("older x11 text"),    # xclip -selection primary
        # clipboard not reached because wayland_new is True
    ]
    listener = _make_listener()

    selected = listener.get_primary_selection()
    assert selected == "hello world"
    mock_run.assert_any_call(["wl-paste", "--primary"], capture_output=True, text=True, timeout=1)


@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_triggers_callback(mock_run):
    # Wayland has new text; xclip returns nothing.
    mock_run.side_effect = [
        _result("new selection"),    # wl-paste
        _result("", returncode=1),   # xclip primary (nothing)
        # clipboard not reached
    ]
    callback = MagicMock()
    listener = _make_listener(callback=callback)

    listener.on_trigger(force=False)
    time.sleep(0.1)

    callback.assert_called_once_with("new selection")


@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_ignores_unchanged(mock_run):
    # All sources return text identical to last_selection.
    mock_run.return_value = _result("same text")

    callback = MagicMock()
    listener = _make_listener(callback=callback)
    listener.last_selection = "same text"
    listener._last_clipboard = "same text"

    listener.on_trigger(force=False)
    time.sleep(0.1)
    callback.assert_not_called()

    # But it should be called if force=True
    listener.on_trigger(force=True)
    time.sleep(0.1)
    callback.assert_called_once_with("same text")


# ---- Timeout / error handling ---------------------------------------

@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(["wl-paste"], 1)

    listener = _make_listener()
    selected = listener.get_primary_selection()
    assert selected is None


# ---- XWayland PRIMARY fallback --------------------------------------

@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_xwayland_primary_fallback(mock_run):
    """When wl-paste returns nothing, xclip primary is used."""
    mock_run.side_effect = [
        _result("", returncode=1),           # wl-paste: no Wayland selection
        _result("xwayland text"),             # xclip primary: XWayland app
        # clipboard not reached
    ]
    listener = _make_listener()

    selected = listener.get_primary_selection()
    assert selected == "xwayland text"


# ---- Wayland/XWayland CLIPBOARD fallbacks ---------------------------

@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_wayland_clipboard_fallback(mock_run):
    """When both PRIMARY sources are stale, a new Wayland CLIPBOARD value is returned."""
    mock_run.side_effect = [
        _result("stale wayland"),    # wl-paste --primary
        _result("stale wayland"),    # xclip -selection primary
        _result("copied in wayland"),# wl-paste (clipboard) (new!)
    ]
    listener = _make_listener()
    listener.last_selection = "stale wayland"

    selected = listener.get_primary_selection()
    assert selected == "copied in wayland"


@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_xwayland_clipboard_fallback(mock_run):
    """When PRIMARY sources and Wayland clipboard are stale/empty, a new X11 CLIPBOARD value is returned."""
    mock_run.side_effect = [
        _result("stale wayland"),    # wl-paste --primary
        _result("stale wayland"),    # xclip -selection primary
        _result("", returncode=1),   # wl-paste (clipboard) (empty/error)
        _result("copied in cef"),    # xclip -selection clipboard (new!)
    ]
    listener = _make_listener()
    listener.last_selection = "stale wayland"

    selected = listener.get_primary_selection()
    assert selected == "copied in cef"


@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_clipboard_ignored_when_stale(mock_run):
    """Clipboard is ignored if its content hasn't changed since last read."""
    mock_run.side_effect = [
        _result("stale wayland"),    # wl-paste
        _result("stale wayland"),    # xclip primary
        _result("old clipboard"),    # wl-paste (clipboard) (already seen)
        _result("old clipboard"),    # xclip clipboard (already seen)
    ]
    listener = _make_listener()
    listener.last_selection = "stale wayland"
    listener._last_clipboard = "old clipboard"   # already tracked

    selected = listener.get_primary_selection()
    # Should fall through to the stale path (wayland_text or x11_text)
    assert selected == "stale wayland"


# ---- xclip not installed -------------------------------------------

@patch('select_to_speech.selection_listener.shutil.which', return_value=None)
@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_xclip_not_installed(mock_run, mock_which):
    """Missing xclip should degrade gracefully; Wayland path still works."""
    mock_run.return_value = _result("wayland text")

    callback = MagicMock()
    listener = WaylandSelectionListener(on_selection_change=callback)

    selected = listener.get_primary_selection()
    assert selected == "wayland text"
    # Only wl-paste should have been called (xclip skipped)
    mock_run.assert_called_once_with(["wl-paste", "--primary"], capture_output=True, text=True, timeout=1)


# ---- Windows Selection Listener -----------------------------------

from select_to_speech.selection_listener import (
    WindowsSelectionListener,
    get_selection_listener,
    BaseSelectionListener,
)


def test_windows_selection_listener_captures_and_restores():
    callback = MagicMock()
    listener = WindowsSelectionListener(on_selection_change=callback, copy_delay=0.01)

    mock_kb = MagicMock()
    listener._keyboard = mock_kb

    clipboard_states = []

    # Mock clipboard operations: initial -> empty -> copied text -> restored
    # 1. get original ("original clipboard")
    # 2. set empty ("")
    # 3. get copied ("selected text")
    # 4. set restored ("original clipboard")
    with patch.object(listener, "_get_clipboard_text", side_effect=["original clipboard", "selected text"]), \
         patch.object(listener, "_set_clipboard_text") as mock_set_clip:

        selected = listener.get_primary_selection()

        assert selected == "selected text"
        # Verify Ctrl+C was simulated (press ctrl, press c)
        assert mock_kb.press.call_count == 2
        # Verify release calls include released modifier keys plus c and ctrl
        assert mock_kb.release.call_count >= 2
        # Verify original clipboard was restored
        mock_set_clip.assert_called_with("original clipboard")


def test_windows_selection_listener_on_trigger():
    callback = MagicMock()
    listener = WindowsSelectionListener(on_selection_change=callback, copy_delay=0.01)

    with patch.object(listener, "get_primary_selection", return_value="hello from windows"):
        listener.on_trigger(force=False)
        time.sleep(0.1)

        callback.assert_called_once_with("hello from windows")
        assert listener.last_selection == "hello from windows"


def test_windows_selection_listener_empty_selection():
    callback = MagicMock()
    listener = WindowsSelectionListener(on_selection_change=callback, copy_delay=0.01)
    mock_kb = MagicMock()
    listener._keyboard = mock_kb

    with patch.object(listener, "_get_clipboard_text", return_value=None), \
         patch.object(listener, "_set_clipboard_text") as mock_set_clip:

        selected = listener.get_primary_selection()
        assert selected is None


def test_windows_selection_listener_lifecycle():
    callback = MagicMock()
    listener = WindowsSelectionListener(on_selection_change=callback)

    assert not listener.is_running
    listener.start()
    assert listener.is_running
    listener.stop()
    assert not listener.is_running


def test_get_selection_listener_factory():
    callback = MagicMock()

    with patch("sys.platform", "win32"):
        win_listener = get_selection_listener(on_selection_change=callback)
        assert isinstance(win_listener, WindowsSelectionListener)

    with patch("sys.platform", "linux"):
        linux_listener = get_selection_listener(on_selection_change=callback)
        assert isinstance(linux_listener, WaylandSelectionListener)

