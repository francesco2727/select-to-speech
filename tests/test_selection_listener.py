import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from select_to_speech.selection_listener import (
    _SOURCE_PRIORITY,
    WaylandSelectionListener,
)


def _make_listener(**kwargs) -> WaylandSelectionListener:
    """Create a listener wired for unit tests.

    No watch processes are spawned (``start()`` is not called unless a test
    explicitly needs the baseline seeding), and X11 reads are mocked away.
    """
    return WaylandSelectionListener(on_selection_change=kwargs.get("callback", MagicMock()))


def _result(text: str = "", returncode: int = 0) -> MagicMock:
    return MagicMock(returncode=returncode, stdout=text)


def _fake_run(primary: str = "", clipboard: str = "", rc: int = 0):
    """Build a subprocess.run side effect that answers by command name."""

    def run(cmd, **kwargs):
        if cmd == ["wl-paste", "--primary"]:
            return _result(primary, rc)
        if cmd == ["wl-paste"]:
            return _result(clipboard, rc)
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    return run


def _patch_sources(primary="", clipboard="", x11_primary=None, x11_clipboard=None, rc=0):
    """Patch wl-paste subprocess calls and Xlib reads at the same time."""

    def x11_read(selection, timeout_s=0.5):
        if selection == "PRIMARY":
            return x11_primary
        if selection == "CLIPBOARD":
            return x11_clipboard
        raise AssertionError(f"unexpected X11 selection: {selection}")

    run_patch = patch(
        "select_to_speech.selection_listener.subprocess.run",
        side_effect=_fake_run(primary, clipboard, rc),
    )
    x11_patch = patch(
        "select_to_speech.selection_listener._read_x11_selection",
        side_effect=x11_read,
    )
    return run_patch, x11_patch


def _baseline(listener: WaylandSelectionListener, **sources) -> None:
    """Seed the listener as if start() baselined the given contents."""
    for name in _SOURCE_PRIORITY:
        text = sources.get(name)
        if text is not None:
            listener._observed[name] = (text.strip(), 0.0)


# ---- Freshness-based selection --------------------------------------

@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_selection_listener_gets_new_wayland_primary(mock_run, mock_x11):
    # Wayland primary changed since the baseline; everything else is stale.
    mock_run.side_effect = _fake_run(primary="new selection", clipboard="old copy")
    listener = _make_listener()
    _baseline(listener, wayland_primary="stale prompt", wayland_clipboard="old copy")

    selected = listener.get_primary_selection()
    assert selected == "new selection"


@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_fresh_clipboard_beats_stale_primary(mock_run, mock_x11):
    """Regression test: a copied text must win over a stale primary selection."""
    mock_run.side_effect = _fake_run(
        primary="stale terminal prompt", clipboard="freshly copied text"
    )
    listener = _make_listener()
    _baseline(
        listener,
        wayland_primary="stale terminal prompt",
        wayland_clipboard="old clipboard content",
    )

    selected = listener.get_primary_selection()
    assert selected == "freshly copied text"


@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_watch_event_detects_recopy_of_same_text(mock_run, mock_x11):
    """Re-copying identical text must be detected via the wl-paste watch event."""
    mock_run.side_effect = _fake_run(primary="stale prompt", clipboard="same text")
    listener = _make_listener()
    _baseline(listener, wayland_primary="stale prompt", wayland_clipboard="same text")

    now = time.monotonic()
    listener._last_gather_ts = now - 10
    listener._watches["wayland_clipboard"].last_event_ts = now - 5  # event after last gather

    selected = listener.get_primary_selection()
    assert selected == "same text"


@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_unchanged_sources_replay_freshest(mock_run, mock_x11):
    """Pressing the hotkey twice without changes replays the same text."""
    mock_run.side_effect = _fake_run(primary="selected text", clipboard="old copy")
    listener = _make_listener()
    now = time.monotonic()
    listener._observed["wayland_primary"] = ("selected text", now - 1)
    listener._observed["wayland_clipboard"] = ("old copy", now - 100)

    selected = listener.get_primary_selection()
    assert selected == "selected text"


@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_priority_breaks_timestamp_ties(mock_run, mock_x11):
    """Equal timestamps resolve to the highest-priority source (Wayland primary)."""
    mock_run.side_effect = _fake_run(primary="primary text", clipboard="clipboard text")
    listener = _make_listener()
    # Both baselined at startup (ts 0.0) and unchanged: tie -> primary wins.
    _baseline(listener, wayland_primary="primary text", wayland_clipboard="clipboard text")

    selected = listener.get_primary_selection()
    assert selected == "primary text"


# ---- X11 / XWayland support (python-Xlib, no xclip) ------------------

@patch("select_to_speech.selection_listener.subprocess.run")
def test_x11_primary_used_for_xwayland_apps(mock_run):
    """An XWayland selection is read via python-Xlib when Wayland primary is stale."""
    mock_run.side_effect = _fake_run(primary="stale wayland prompt", clipboard="")
    listener = _make_listener()
    _baseline(listener, wayland_primary="stale wayland prompt")

    with patch(
        "select_to_speech.selection_listener._read_x11_selection",
        side_effect=lambda sel, timeout_s=0.5: "xwayland selection" if sel == "PRIMARY" else None,
    ):
        selected = listener.get_primary_selection()
    assert selected == "xwayland selection"


@patch("select_to_speech.selection_listener.subprocess.run")
def test_x11_clipboard_fallback(mock_run):
    """An X11 clipboard copy is used when every other source is stale or empty."""
    mock_run.side_effect = _fake_run(primary="stale wayland prompt", clipboard="")
    listener = _make_listener()
    _baseline(listener, wayland_primary="stale wayland prompt")

    def x11_read(sel, timeout_s=0.5):
        return "copied in cef" if sel == "CLIPBOARD" else None

    with patch(
        "select_to_speech.selection_listener._read_x11_selection",
        side_effect=x11_read,
    ):
        selected = listener.get_primary_selection()
    assert selected == "copied in cef"


@patch("select_to_speech.selection_listener.subprocess.run")
def test_no_x_server_degrades_gracefully(mock_run):
    """Without any selection the listener returns None instead of raising."""
    mock_run.side_effect = _fake_run(primary="", clipboard="", rc=1)
    listener = _make_listener()

    with patch(
        "select_to_speech.selection_listener._read_x11_selection", return_value=None
    ):
        selected = listener.get_primary_selection()
    assert selected is None


# ---- Error handling ---------------------------------------------------

@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_wl_paste_timeout_returns_none(mock_run, mock_x11):
    mock_run.side_effect = subprocess.TimeoutExpired(["wl-paste"], 1)

    listener = _make_listener()
    selected = listener.get_primary_selection()
    assert selected is None


@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_wl_paste_missing_returns_none(mock_run, mock_x11):
    mock_run.side_effect = FileNotFoundError("wl-paste")

    listener = _make_listener()
    selected = listener.get_primary_selection()
    assert selected is None


# ---- on_trigger dispatch ---------------------------------------------

@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_selection_listener_triggers_callback(mock_run, mock_x11):
    mock_run.side_effect = _fake_run(primary="new selection")
    callback = MagicMock()
    listener = _make_listener(callback=callback)

    listener.on_trigger(force=False)
    for _ in range(50):
        if callback.call_count:
            break
        time.sleep(0.02)

    callback.assert_called_once_with("new selection")


@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_selection_listener_ignores_unchanged(mock_run, mock_x11):
    # All sources return text identical to last_selection.
    mock_run.side_effect = _fake_run(primary="same text")

    callback = MagicMock()
    listener = _make_listener(callback=callback)
    listener.last_selection = "same text"
    _baseline(listener, wayland_primary="same text")

    listener.on_trigger(force=False)
    time.sleep(0.2)
    callback.assert_not_called()

    # But it should be called if force=True
    listener.on_trigger(force=True)
    for _ in range(50):
        if callback.call_count:
            break
        time.sleep(0.02)
    callback.assert_called_once_with("same text")


# ---- Lifecycle --------------------------------------------------------

@patch("select_to_speech.selection_listener._read_x11_selection", return_value=None)
@patch("select_to_speech.selection_listener.subprocess.run")
def test_start_baselines_existing_selections(mock_run, mock_x11):
    """start() seeds observed contents so pre-existing text is not 'fresh'."""
    mock_run.side_effect = _fake_run(primary="pre-existing selection", clipboard="old copy")

    listener = _make_listener()
    with patch.object(listener._watches["wayland_primary"], "start") as watch_start:
        with patch.object(listener._watches["wayland_clipboard"], "start"):
            listener.start()

    watch_start.assert_called_once()
    assert listener.is_running is True
    assert listener._observed["wayland_primary"] == ("pre-existing selection", 0.0)
    assert listener._observed["wayland_clipboard"] == ("old copy", 0.0)

    listener.stop()


def test_stop_without_start_is_safe():
    listener = _make_listener()
    listener.stop()  # must not raise
    assert listener.is_running is False
