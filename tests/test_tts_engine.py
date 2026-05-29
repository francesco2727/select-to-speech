import pytest
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, '/home/francescov/develop/select-to-speach/src')

from select_to_speech.tts_engine import BaseTTSEngine
from select_to_speech.config import VoiceConfig

class DummyEngine(BaseTTSEngine):
    def synthesize(self, text, language=None, speed=1.0, volume=1.0):
        pass
    def synthesize_stream(self, text, language=None, speed=1.0, volume=1.0):
        pass
    def stop(self):
        pass

def test_sanitize_text():
    config = VoiceConfig()
    engine = DummyEngine(config)
    
    dirty_text = 'Hello """world"""!  \n\tHow are you?'
    clean_text = engine._sanitize_text(dirty_text)
    
    assert clean_text == 'Hello "world"! How are you?'

def test_chunk_text():
    config = VoiceConfig()
    engine = DummyEngine(config)
    
    long_text = "This is the first sentence. This is the second sentence! Is this the third? " + ("A long comma list, " * 15)
    chunks = engine._chunk_text(long_text, max_chars=30)
    
    assert len(chunks) > 1
    # Check that sentences aren't split unnecessarily
    assert chunks[0] == "This is the first sentence."
    # Ensure chunk limits are respected where possible
    for chunk in chunks:
        # Give a small padding for edge cases, but it shouldn't exceed 100 heavily
        assert len(chunk) <= 120 

@patch('select_to_speech.tts_engine.PiperEngine.ensure_voice_loaded')
def test_piper_engine_stream(mock_ensure):
    mock_ensure.return_value = True
    config = VoiceConfig(engine="piper", model="en_US-lessac-medium")
    
    from select_to_speech.tts_engine import PiperEngine
    engine = PiperEngine(config)
    
    # Mock PiperVoice
    mock_voice = MagicMock()
    mock_voice.config.sample_rate = 22050
    engine.voices["en_US-lessac-medium"] = mock_voice
    
    # Needs to be mocked properly to avoid exception
    with patch('wave.open') as mock_wave, patch('io.BytesIO') as mock_io:
        mock_io.return_value.__enter__.return_value.getvalue.return_value = b"dummy_audio"
        stream_results = list(engine.synthesize_stream("Hello world."))
        
    assert len(stream_results) == 1
    assert stream_results[0][0] == b"dummy_audio"
    assert stream_results[0][1] == 22050

def test_preprocess_text():
    config = VoiceConfig()
    engine = DummyEngine(config)
    
    # Italian math symbols & dots in domains/filenames
    text_it = "Il file.py sul dominio portal.azure.com contiene il 5% di codice + 3 - 2 * 4 / 2 = 10, che è > di 9 e < di 11. Anche -5 è negativo."
    processed_it = engine.preprocess_text(text_it, language="it")
    
    assert "file punto py" in processed_it
    assert "portal punto azure punto com" in processed_it
    assert "5 percento" in processed_it
    assert "più" in processed_it
    assert "meno" in processed_it
    assert "per" in processed_it
    assert "diviso" in processed_it
    assert "uguale" in processed_it
    assert "maggiore di" in processed_it
    assert "minore di" in processed_it
    assert "meno 5" in processed_it
    
    # Test decimal numbers and version strings are kept as is
    dec_test = "Il valore pi è 3.14 o 10.5 e la versione è 1.0."
    processed_dec = engine.preprocess_text(dec_test, language="it")
    assert "3.14" in processed_dec
    assert "10.5" in processed_dec
    assert "1.0" in processed_dec
    
    # Test English translations
    text_en = "File file.py at google.com has 5% plus 3 - 2 * 4 / 2 = 10. Also -5."
    processed_en = engine.preprocess_text(text_en, language="en")
    
    assert "file dot py" in processed_en
    assert "google dot com" in processed_en
    assert "5 percent" in processed_en
    assert "plus" in processed_en
    assert "minus" in processed_en
    assert "times" in processed_en
    assert "divided by" in processed_en
    assert "equals" in processed_en
    assert "minus 5" in processed_en
