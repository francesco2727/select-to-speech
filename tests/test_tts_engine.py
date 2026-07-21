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


def test_preprocess_currencies():
    config = VoiceConfig()
    engine = DummyEngine(config)

    # Italian currency tests ($ = dollari, € = euro, £ = sterline, ¥ = yen)
    text_it = "Costa $100 oppure 50€ con sconto di £20,50 o ¥1000. Guadagno $100 milioni. Il simbolo $ rappresenta i dollari."
    processed_it = engine.preprocess_text(text_it, language="it")
    assert "100 dollari" in processed_it
    assert "50 euro" in processed_it
    assert "20,50 sterline" in processed_it
    assert "1000 yen" in processed_it
    assert "100 milioni dollari" in processed_it
    assert "dollari" in processed_it

    # Check sanitized Italian text (normalizes multiple spaces to single spaces)
    sanitized_it = engine._sanitize_text(text_it, language="it")
    assert "Il simbolo dollari rappresenta" in sanitized_it
    assert "Costa 100 dollari oppure 50 euro" in sanitized_it

    # English currency tests
    text_en = "Price is $100 or 50€ and $100 million in total."
    processed_en = engine.preprocess_text(text_en, language="en")
    assert "100 dollars" in processed_en
    assert "50 euros" in processed_en
    assert "100 million dollars" in processed_en

    # Spanish currency tests
    text_es = "El precio es $100 o 50€."
    processed_es = engine.preprocess_text(text_es, language="es")
    assert "100 dólares" in processed_es
    assert "50 euros" in processed_es

    # French currency tests
    text_fr = "Le prix est $100 ou 50€."
    processed_fr = engine.preprocess_text(text_fr, language="fr")
    assert "100 dollars" in processed_fr
    assert "50 euros" in processed_fr

    # German currency tests
    text_de = "Der Preis beträgt $100 oder 50€."
    processed_de = engine.preprocess_text(text_de, language="de")
    assert "100 Dollar" in processed_de
    assert "50 Euro" in processed_de

    # Japanese currency tests
    text_ja = "価格は$100または50€です。"
    processed_ja = engine.preprocess_text(text_ja, language="ja")
    assert "100 ドル" in processed_ja
    assert "50 ユーロ" in processed_ja


def test_kokoro_tokenizer_truncation():
    from select_to_speech.tts_engine import KokoroEngine
    config = MagicMock()
    config.model = "af"
    engine = KokoroEngine(config)
    
    with patch.object(engine, 'ensure_model_downloaded', return_value=True), \
         patch('kokoro_onnx.Kokoro') as mock_kokoro_class:
        mock_kokoro = MagicMock()
        # Mock original tokenize returning > 509 tokens
        mock_kokoro.tokenizer.tokenize.return_value = list(range(600))
        mock_kokoro.tokenizer.phonemize.return_value = "dummy phonemes"
        mock_kokoro_class.return_value = mock_kokoro
        
        assert engine._init_kokoro() is True
        
        # Test that calling patched tokenize truncates to 509
        tokens = engine.kokoro.tokenizer.tokenize("some long text")
        assert len(tokens) == 509
        assert tokens == list(range(509))


def test_kokoro_synthesize_chunking():
    from select_to_speech.tts_engine import KokoroEngine
    import numpy as np
    config = MagicMock()
    config.model = "af"
    engine = KokoroEngine(config)
    
    with patch.object(engine, '_init_kokoro', return_value=True):
        engine.kokoro = MagicMock()
        # Return 100 samples per chunk
        engine.kokoro.create.side_effect = [
            (np.ones(100, dtype=np.float32) * 0.5, 24000),
            (np.ones(100, dtype=np.float32) * 0.5, 24000)
        ]
        
        with patch.object(engine, '_chunk_text', return_value=["Chunk one.", "Chunk two."]):
            res = engine.synthesize("Chunk one. Chunk two.")
            assert res is not None
            audio_bytes, sr = res
            assert sr == 24000
            assert engine.kokoro.create.call_count == 2
