import pytest
from unittest.mock import MagicMock
from pynput import keyboard

import sys
sys.path.insert(0, '/home/francescov/develop/select-to-speach/src')

from select_to_speech.keyboard_handler import KeyboardHandler

def test_keyboard_handler_shortcut_triggered():
    callback = MagicMock()
    handler = KeyboardHandler(on_shortcut=callback, modifier="alt", trigger_key="esc")
    
    # Simulate ALT press
    handler._on_press(keyboard.Key.alt)
    assert keyboard.Key.alt in handler.keys_pressed
    
    # Simulate ESC press
    handler._on_press(keyboard.Key.esc)
    callback.assert_called_once()
    
    # Simulate ALT release
    handler._on_release(keyboard.Key.alt)
    assert keyboard.Key.alt not in handler.keys_pressed

def test_keyboard_handler_wrong_modifier():
    callback = MagicMock()
    handler = KeyboardHandler(on_shortcut=callback, modifier="alt", trigger_key="esc")
    
    # Simulate CTRL press
    handler._on_press(keyboard.Key.ctrl)
    
    # Simulate ESC press
    handler._on_press(keyboard.Key.esc)
    callback.assert_not_called()

def test_keyboard_handler_key_error_handling():
    callback = MagicMock()
    handler = KeyboardHandler(on_shortcut=callback, modifier="alt", trigger_key="esc")
    
    # Try an unmapped type
    try:
        handler._on_press(None)
        handler._on_release(None)
    except Exception as e:
        pytest.fail(f"Handler should not raise on non-Key press: {e}")
