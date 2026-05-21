import pytest
from unittest.mock import MagicMock, patch
from pynput import keyboard

import sys
sys.path.insert(0, '/home/francescov/develop/select-to-speach/src')

from select_to_speech.keyboard_handler import KeyboardHandler

def test_keyboard_handler_initialization():
    on_play = MagicMock()
    on_pause = MagicMock()
    on_stop = MagicMock()
    
    handler = KeyboardHandler(
        on_play=on_play,
        on_pause=on_pause,
        on_stop=on_stop,
        modifier="alt",
        trigger_key="esc",
        pause_key="w",
        stop_key="s"
    )
    
    assert handler.hotkeys["<alt>+<esc>"] == on_play
    assert handler.hotkeys["<alt>+w"] == on_pause
    assert handler.hotkeys["<alt>+s"] == on_stop

def test_keyboard_handler_format_hotkey():
    assert KeyboardHandler.format_hotkey("alt", "esc") == "<alt>+<esc>"
    assert KeyboardHandler.format_hotkey("ctrl+alt", "a") == "<ctrl>+<alt>+a"
    assert KeyboardHandler.format_hotkey("shift", "f1") == "<shift>+<f1>"
    assert KeyboardHandler.format_hotkey("", "space") == "<space>"

@patch('select_to_speech.keyboard_handler.keyboard.GlobalHotKeys')
def test_keyboard_handler_start_stop(mock_hotkeys_class):
    mock_listener = MagicMock()
    mock_hotkeys_class.return_value = mock_listener
    
    on_play = MagicMock()
    handler = KeyboardHandler(on_play=on_play, modifier="alt", trigger_key="esc")
    
    # Test start
    handler.start()
    mock_hotkeys_class.assert_called_once_with(handler.hotkeys)
    mock_listener.start.assert_called_once()
    assert handler.listener == mock_listener
    
    # Test stop
    handler.stop()
    mock_listener.stop.assert_called_once()
    assert handler.listener is None
