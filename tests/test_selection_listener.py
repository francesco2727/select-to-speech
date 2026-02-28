import pytest
from unittest.mock import MagicMock, patch
import subprocess
import time

import sys
sys.path.insert(0, '/home/francescov/develop/select-to-speach/src')

from select_to_speech.selection_listener import WaylandSelectionListener

@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_gets_text(mock_run):
    # Setup mock
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "hello world"
    mock_run.return_value = mock_result
    
    callback = MagicMock()
    listener = WaylandSelectionListener(on_selection_change=callback)
    
    selected = listener.get_primary_selection()
    assert selected == "hello world"
    mock_run.assert_called_once_with(["wl-paste", "--primary"], capture_output=True, text=True, timeout=1)

@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_triggers_callback(mock_run):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "new selection"
    mock_run.return_value = mock_result
    
    callback = MagicMock()
    listener = WaylandSelectionListener(on_selection_change=callback)
    
    listener.on_trigger(force=False)
    # Give the thread time to execute
    time.sleep(0.1)
    
    callback.assert_called_once_with("new selection")

@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_ignores_unchanged(mock_run):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "same text"
    mock_run.return_value = mock_result
    
    callback = MagicMock()
    listener = WaylandSelectionListener(on_selection_change=callback)
    listener.last_selection = "same text"
    
    listener.on_trigger(force=False)
    time.sleep(0.1)
    
    # Callback shouldn't be called if text hasn't changed and force=False
    callback.assert_not_called()
    
    # But it should be called if force=True
    listener.on_trigger(force=True)
    time.sleep(0.1)
    callback.assert_called_once_with("same text")

@patch('select_to_speech.selection_listener.subprocess.run')
def test_selection_listener_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(["wl-paste"], 1)
    
    callback = MagicMock()
    listener = WaylandSelectionListener(on_selection_change=callback)
    
    selected = listener.get_primary_selection()
    assert selected is None
