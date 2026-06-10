import pytest
from unittest.mock import MagicMock, patch
import threading
import queue

import sys
sys.path.insert(0, '/home/francescov/develop/select-to-speach/src')

from select_to_speech.main import SelectToSpeechApp
from select_to_speech.config import AppConfig, VoiceConfig, AudioConfig, KeyboardConfig

@pytest.fixture
def mock_app():
    config = AppConfig(
        voice=VoiceConfig(engine="kokoro"),
        audio=AudioConfig(),
        keyboard=KeyboardConfig()
    )
    
    with patch('select_to_speech.main.WaylandSelectionListener'), \
         patch('select_to_speech.main.KeyboardHandler'), \
         patch('select_to_speech.main.get_tts_engine'), \
         patch('select_to_speech.main.AudioPlayer'):
        
        app = SelectToSpeechApp(config)
        return app

def test_app_initialization(mock_app):
    assert mock_app.tts_engine is not None
    assert mock_app.audio_player is not None
    assert mock_app.selection_listener is not None
    assert mock_app.keyboard_handler is not None

def test_on_text_selected(mock_app):
    mock_app._process_thread = MagicMock()
    mock_app._process_thread.is_alive.return_value = False
    
    with patch('threading.Thread') as mock_thread:
        mock_app._on_text_selected("Read this text")
        
        mock_app.audio_player.stop.assert_called_once()
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        
        # Stop event should be cleared before processing
        assert not mock_app._stop_event.is_set()

def test_process_text(mock_app):
    stop_event = threading.Event()
    
    mock_app.tts_engine.synthesize_stream.return_value = iter([(b"audio", 22050)])
    mock_app.audio_player.play_stream.return_value = True
    
    with patch.object(mock_app, '_detect_language', return_value="en"):
        # Process text runs background threads, since we mock play_stream and synthesize_stream, it should work
        result = mock_app.process_text("Hello there", stop_event)
        
        assert result is True
        # Verify the language fallback and playback
        mock_app.audio_player.play_stream.assert_called_once()
