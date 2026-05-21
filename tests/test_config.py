import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, '/home/francescov/develop/select-to-speach/src')

from select_to_speech.config import AppConfig, VoiceConfig, AudioConfig, KeyboardConfig, load_config

def test_default_config():
    config = AppConfig(
        voice=VoiceConfig(),
        audio=AudioConfig(),
        keyboard=KeyboardConfig()
    )
    
    assert config.voice.engine == "kokoro"
    assert config.audio.speed == 1.0
    assert config.keyboard.trigger_key == "esc"

@patch('select_to_speech.config.Path.exists')
@patch('builtins.open')
def test_load_config_file_not_found(mock_open, mock_exists):
    mock_exists.return_value = False
    
    config = load_config()
    
    assert isinstance(config, AppConfig)
    assert config.debug is False
    # Verify open wasn't called because file doesn't exist
    mock_open.assert_not_called()

@patch('select_to_speech.config.Path.exists')
@patch('builtins.open')
@patch('yaml.safe_load')
def test_load_config_with_file(mock_yaml_load, mock_open, mock_exists):
    mock_exists.return_value = True
    
    # Provide a dummy YAML config mapping
    mock_yaml_load.return_value = {
        "debug": True,
        "voice": {
            "engine": "piper",
            "model": "en_US-lessac-medium"
        },
        "audio": {
            "speed": 1.2
        },
        "keyboard": {
            "modifier_key": "ctrl"
        }
    }
    
    config = load_config()
    
    assert config.debug is True
    assert config.voice.engine == "piper"
    assert config.voice.model == "en_US-lessac-medium"
    assert config.audio.speed == 1.2
    assert config.keyboard.modifier_key == "ctrl"
    assert config.keyboard.trigger_key == "esc" # Default value remains
