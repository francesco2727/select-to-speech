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

    # Test typographical apostrophes, quotes, and newlines
    typo_text = "l’app funziona con un’ora di ritardo, c’è chi dice: «bravo»!\nAltra riga di prova"
    sanitized = engine._sanitize_text(typo_text)
    assert "l'app" in sanitized
    assert "un'ora" in sanitized
    assert "c'è" in sanitized
    assert '"bravo"' in sanitized
    assert "«" not in sanitized
    assert "»" not in sanitized
    # Unpunctuated newline should receive a period
    assert "bravo\"! Altra riga di prova" in sanitized

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


def test_kokoro_synthesize_chunking():
    from select_to_speech.tts_engine import KokoroEngine
    import numpy as np
    config = MagicMock()
    config.model = "af_heart"
    engine = KokoroEngine(config)
    
    mock_audio = MagicMock()
    mock_audio.samples = np.ones(100, dtype=np.float32) * 0.5
    mock_audio.sample_rate = 24000
    
    with patch.object(engine, '_init_tts', return_value=True):
        engine.tts = MagicMock()
        engine.tts.generate.return_value = mock_audio
        
        with patch.object(engine, '_chunk_text', return_value=["Chunk one.", "Chunk two."]):
            res = engine.synthesize("Chunk one. Chunk two.")
            assert res is not None
            audio_bytes, sr = res
            assert sr == 24000
            assert engine.tts.generate.call_count == 2


def test_base_tts_engine_update_config():
    config1 = VoiceConfig(model="af_heart")
    engine = DummyEngine(config1)
    assert engine.voice_config.model == "af_heart"
    
    config2 = VoiceConfig(model="am_adam")
    engine.update_config(config2)
    assert engine.voice_config.model == "am_adam"


def test_kokoro_engine_update_config_same_model():
    from select_to_speech.tts_engine import KokoroEngine
    config1 = VoiceConfig(model="kokoro-multi-lang-v1_0", language="it")
    engine = KokoroEngine(config1)
    engine.tts = MagicMock()
    
    config2 = VoiceConfig(model="kokoro-multi-lang-v1_0", language="en")
    engine.update_config(config2)
    
    assert engine.model_id == "kokoro-multi-lang-v1_0"
    assert engine.voice_config.language == "en"
    assert engine.tts is not None


def test_kokoro_engine_update_config_model_change():
    from select_to_speech.tts_engine import KokoroEngine
    config1 = VoiceConfig(model="kokoro-multi-lang-v1_0")
    engine = KokoroEngine(config1)
    engine.tts = MagicMock()
    
    config2 = VoiceConfig(model="kokoro-int8-multi-lang-v1_0")
    engine.update_config(config2)
    
    assert engine.model_id == "kokoro-int8-multi-lang-v1_0"
    assert engine.model_dir.name == "kokoro-int8-multi-lang-v1_0"
    assert engine.tts is None


def test_kokoro_synthesize_stream_native_callback():
    from select_to_speech.tts_engine import KokoroEngine
    import numpy as np

    config = MagicMock()
    config.model = "af_heart"
    engine = KokoroEngine(config)

    def fake_generate(text, gen_config, callback=None):
        if callback:
            # Simulate 2 batch callbacks
            s1 = np.ones(500, dtype=np.float32) * 0.1
            cont = callback(s1, 0.5)
            if cont:
                s2 = np.ones(500, dtype=np.float32) * 0.2
                callback(s2, 1.0)
        ret = MagicMock()
        ret.samples = np.ones(1000, dtype=np.float32)
        ret.sample_rate = 24000
        return ret

    with patch.object(engine, '_init_tts', return_value=True):
        engine.tts = MagicMock()
        engine.tts.sample_rate = 24000
        engine.tts.generate.side_effect = fake_generate

        chunks = list(engine.synthesize_stream("Questa è una frase lunga di test per lo streaming."))
        assert len(chunks) == 2
        for data, sr in chunks:
            assert sr == 24000
            assert len(data) > 0


def test_kokoro_synthesize_stream_early_stop():
    from select_to_speech.tts_engine import KokoroEngine
    import numpy as np
    import threading

    config = MagicMock()
    config.model = "af_heart"
    engine = KokoroEngine(config)
    stop_event = threading.Event()

    calls = []
    def fake_generate(text, gen_config, callback=None):
        if callback:
            s1 = np.ones(500, dtype=np.float32) * 0.1
            calls.append(1)
            stop_event.set()  # Stop triggered after 1st batch
            cont = callback(s1, 0.5)
            if cont:
                s2 = np.ones(500, dtype=np.float32) * 0.2
                calls.append(2)
                callback(s2, 1.0)
        ret = MagicMock()
        return ret

    with patch.object(engine, '_init_tts', return_value=True):
        engine.tts = MagicMock()
        engine.tts.sample_rate = 24000
        engine.tts.generate.side_effect = fake_generate

        chunks = list(engine.synthesize_stream("Testo con stop anticipato.", stop_event=stop_event))
        assert len(chunks) <= 1
        assert len(calls) == 1

