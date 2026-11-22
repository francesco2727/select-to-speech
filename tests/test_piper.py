"""Piper voices: catalog, voice management, engine, config, detection and API."""

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from select_to_speech import voice_manager as vm
from select_to_speech.config import AppConfig, VoiceConfig, _migrate_config_dict


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolate ~/.local/share/select-to-speech in a temporary HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _voices_dir(home: Path) -> Path:
    d = home / ".local" / "share" / "select-to-speech" / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _install_fake_piper(home: Path, key: str, precision: str = "int8", speaker_map: dict | None = None) -> Path:
    """Create the files of an extracted Piper archive."""
    model_dir = _voices_dir(home) / vm.piper_dir_name(key, precision)
    (model_dir / "espeak-ng-data").mkdir(parents=True)
    (model_dir / "tokens.txt").write_text("a 1\n")
    model_name = key + ".onnx"
    (model_dir / model_name).write_bytes(b"\0" * 10)
    meta = {"num_speakers": len(speaker_map or {}) or 1, "speaker_id_map": speaker_map or {}}
    (model_dir / (model_name + ".json")).write_text(json.dumps(meta))
    return model_dir


# ── Catalog ────────────────────────────────────────────────────────────────────


def test_catalog_lists_languages_with_voices_only():
    languages = vm.get_piper_languages()
    assert "it" in languages and "en" in languages
    assert "uz" not in languages  # no Uzbek Piper voice → no Uzbek menu in the UI
    for key, info in vm.load_piper_catalog().items():
        assert info["language"] in languages
        assert info["sizes"], key


def test_catalog_has_no_duplicate_voices():
    """The GUI labels voices by name (+ quality/locale when needed): each must be unique."""
    seen = set()
    for key, info in vm.load_piper_catalog().items():
        identity = (info["locale"], info["name"], info["quality"])
        assert identity not in seen, key
        seen.add(identity)


def test_catalog_has_multi_speaker_names():
    speakers = vm.load_piper_catalog()["en_US-libritts_r-medium"]["speakers"]
    assert len(speakers) == 904


@pytest.mark.parametrize("ref,expected", [
    ("it_IT-paola-medium", ("it_IT-paola-medium", 0)),
    ("en_US-libritts_r-medium#12", ("en_US-libritts_r-medium", 12)),
    ("en_US-libritts_r-medium#x", ("en_US-libritts_r-medium", 0)),
    ("", ("", 0)),
])
def test_parse_voice_ref(ref, expected):
    assert vm.parse_voice_ref(ref) == expected


def test_format_voice_ref_round_trip():
    assert vm.format_voice_ref("k", 0) == "k"
    assert vm.parse_voice_ref(vm.format_voice_ref("k", 7)) == ("k", 7)


def test_precision_falls_back_when_variant_missing():
    # es-glados-medium is published in fp32 only
    assert vm.resolve_piper_precision("es-glados-medium", "int8") == "fp32"
    assert vm.piper_dir_name("es-glados-medium", "int8") == "vits-piper-es-glados-medium"
    assert vm.piper_dir_name("it_IT-paola-medium", "int8") == "vits-piper-it_IT-paola-medium-int8"
    assert vm.piper_dir_name("it_IT-paola-medium", "fp32") == "vits-piper-it_IT-paola-medium"


# ── Install state ──────────────────────────────────────────────────────────────


def test_is_piper_installed_and_delete(home):
    key = "it_IT-paola-medium"
    assert not vm.is_piper_installed(key, "int8")
    _install_fake_piper(home, key)
    assert vm.is_piper_installed(key, "int8")
    assert not vm.is_piper_installed(key, "fp16")
    assert vm.delete_piper(key, "int8")
    assert not vm.is_piper_installed(key, "int8")
    assert not vm.delete_piper(key, "int8")


def test_get_piper_voices_reports_install_state(home):
    _install_fake_piper(home, "it_IT-paola-medium")
    voices = {v["id"]: v for v in vm.get_piper_voices("it", "int8")}
    assert voices["it_IT-paola-medium"]["installed"] is True
    assert voices["it_IT-riccardo-x_low"]["installed"] is False
    assert voices["it_IT-paola-medium"]["size_bytes"] > 0


def test_installed_speakers_come_from_model_metadata(home):
    _install_fake_piper(home, "en_US-libritts_r-medium", speaker_map={"b": 1, "a": 0})
    assert vm.get_piper_speakers("en_US-libritts_r-medium", "int8") == ["a", "b"]


def test_list_installed_models(home):
    _install_fake_piper(home, "it_IT-paola-medium")
    models = vm.list_installed_models()
    assert [(m["engine"], m["id"], m["precision"], m["language"]) for m in models] == [
        ("piper", "it_IT-paola-medium", "int8", "it")
    ]
    assert models[0]["size_bytes"] > 0


def test_download_piper_rejects_unknown_voice(home):
    with patch.object(vm, "_download_and_extract") as dl:
        assert vm.download_piper("xx_XX-nobody-medium") is False
        dl.assert_not_called()


def test_download_piper_uses_variant_archive(home):
    def fake_extract(archive, dir_name, progress_cb):
        assert archive == "vits-piper-it_IT-paola-medium-int8.tar.bz2"
        _install_fake_piper(home, "it_IT-paola-medium")
        return True

    with patch.object(vm, "_download_and_extract", side_effect=fake_extract):
        assert vm.download_piper("it_IT-paola-medium", "int8") is True


# ── Config ─────────────────────────────────────────────────────────────────────


def test_active_language_models_follows_engine():
    cfg = VoiceConfig(language_models={"it": "if_sara"}, piper_language_models={"it": "it_IT-paola-medium"})
    assert cfg.active_language_models() == {"it": "if_sara"}
    cfg.engine = "piper"
    assert cfg.active_language_models() == {"it": "it_IT-paola-medium"}


def test_migration_fixes_unknown_engine_and_precision():
    data = _migrate_config_dict({"voice": {"engine": "espeak", "piper_precision": "fp64"}})
    config = AppConfig(**data)
    assert config.voice.engine == "kokoro"
    assert config.voice.piper_precision == "int8"


# ── Engine ─────────────────────────────────────────────────────────────────────


def _piper_config(**kwargs) -> VoiceConfig:
    base = dict(
        engine="piper",
        language="it",
        piper_language_models={"it": "it_IT-paola-medium", "en": "en_US-libritts_r-medium#5"},
        num_threads=1,
    )
    base.update(kwargs)
    return VoiceConfig(**base)


def test_factory_picks_engine():
    from select_to_speech.tts_engine import KokoroEngine, PiperEngine, get_tts_engine
    assert isinstance(get_tts_engine(VoiceConfig()), KokoroEngine)
    assert isinstance(get_tts_engine(_piper_config()), PiperEngine)


def test_piper_prepare_generation_uses_language_voice_and_speaker():
    from select_to_speech.tts_engine import PiperEngine
    engine = PiperEngine(_piper_config())
    tts = MagicMock(num_speakers=904, sample_rate=22050)
    with patch.object(engine, "_load_voice", return_value=tts) as load:
        _tts, gen, desc = engine._prepare_generation("en", None, 1.2)
    load.assert_called_once_with("en_US-libritts_r-medium", "int8")
    assert gen.sid == 5
    assert gen.speed == pytest.approx(1.2)
    assert "en_US-libritts_r-medium" in desc


def test_piper_out_of_range_speaker_falls_back_to_zero():
    from select_to_speech.tts_engine import PiperEngine
    engine = PiperEngine(_piper_config())
    with patch.object(engine, "_load_voice", return_value=MagicMock(num_speakers=1)):
        _tts, gen, _ = engine._prepare_generation("en", None, 1.0)
    assert gen.sid == 0


def test_piper_unconfigured_language_uses_default_voice():
    from select_to_speech.tts_engine import PiperEngine
    engine = PiperEngine(_piper_config())
    with patch.object(engine, "_load_voice", return_value=MagicMock(num_speakers=1)) as load:
        engine._prepare_generation("fr", None, 1.0)
    load.assert_called_once_with("it_IT-paola-medium", "int8")


def test_piper_no_voice_configured_returns_none():
    from select_to_speech.tts_engine import PiperEngine
    engine = PiperEngine(_piper_config(piper_language_models={}))
    assert engine._prepare_generation("it", None, 1.0) is None
    assert engine.synthesize("Ciao a tutti", language="it") is None


def test_piper_voice_cache_evicts_least_recently_used(home):
    from select_to_speech.tts_engine import PiperEngine
    keys = ["it_IT-paola-medium", "it_IT-riccardo-x_low", "it_IT-miro-high", "it_IT-dii-high"]
    for key in keys:
        _install_fake_piper(home, key)

    fake_sherpa = MagicMock()
    fake_sherpa.__version__ = "1.13.8"
    fake_sherpa.OfflineTts.side_effect = lambda cfg: MagicMock()
    engine = PiperEngine(_piper_config())
    with patch("select_to_speech.tts_engine._import_sherpa_onnx", return_value=fake_sherpa):
        for key in keys[:3]:
            engine._load_voice(key, "int8")
        engine._load_voice(keys[0], "int8")  # refresh paola → riccardo is now the oldest
        engine._load_voice(keys[3], "int8")

    loaded = [k for k, _ in engine._models]
    assert loaded == [keys[2], keys[0], keys[3]]
    assert fake_sherpa.OfflineTts.call_count == 4  # the refresh hit the cache

    engine.release_model("piper", keys[0], "int8")
    assert (keys[0], "int8") not in engine._models


def test_piper_precision_change_unloads_voices():
    from select_to_speech.tts_engine import PiperEngine
    engine = PiperEngine(_piper_config())
    engine._models[("it_IT-paola-medium", "int8")] = MagicMock()
    engine.update_config(_piper_config(piper_precision="int8", language="en"))
    assert engine._models  # unrelated change keeps the voices loaded
    engine.update_config(_piper_config(piper_precision="fp16"))
    assert not engine._models


def test_piper_stream_yields_model_sample_rate():
    import numpy as np
    from select_to_speech.tts_engine import PiperEngine
    engine = PiperEngine(_piper_config())

    def fake_generate(text, gen_config, callback=None):
        callback(np.ones(100, dtype=np.float32) * 0.1, 1.0)

    tts = MagicMock(num_speakers=1, sample_rate=16000)
    tts.generate.side_effect = fake_generate
    with patch.object(engine, "_load_voice", return_value=tts):
        chunks = list(engine.synthesize_stream("Una frase di prova.", language="it", stop_event=threading.Event()))
    assert [sr for _, sr in chunks] == [16000]


def test_symbols_untouched_for_language_without_word_table():
    from select_to_speech.tts_engine import PiperEngine
    engine = PiperEngine(_piper_config())
    out = engine.preprocess_text("Cena 5€ + 10%", language="pl")
    assert "€" in out and "+" in out and "%" in out
    assert "euro" not in out and "plus" not in out


# ── Language detection & reload ────────────────────────────────────────────────


def test_lingua_map_covers_piper_languages_lingua_can_detect():
    from lingua import Language
    from select_to_speech.main import _LINGUA_LANGUAGES, _LINGUA_TO_CODE
    undetectable = {"ku", "lb", "ml", "ne"}  # not in lingua
    for code in vm.get_piper_languages():
        assert (code in _LINGUA_LANGUAGES) != (code in undetectable), code
    assert _LINGUA_TO_CODE[Language.BOKMAL] == "no"


@pytest.fixture
def app():
    from select_to_speech.main import SelectToSpeechApp
    with patch("select_to_speech.main.WaylandSelectionListener"), \
         patch("select_to_speech.main.KeyboardHandler"), \
         patch("select_to_speech.main.get_tts_engine"), \
         patch("select_to_speech.main.AudioPlayer"):
        yield SelectToSpeechApp(AppConfig())


def test_detector_uses_active_engine_languages(app):
    app.config = AppConfig(voice=_piper_config(piper_language_models={"pl": "pl_PL-gosia-medium", "it": "x"}))
    detector = app._build_lingua_detector()
    from lingua import Language
    assert detector.detect_language_of("To jest zdanie napisane po polsku, całkiem długie.") == Language.POLISH


def test_reload_switches_engine(app):
    old_engine = app.tts_engine
    new_config = AppConfig(voice=_piper_config())
    with patch("select_to_speech.main.KeyboardHandler"), \
         patch("select_to_speech.main.get_tts_engine") as factory, \
         patch("select_to_speech.main.threading.Thread"):
        app.reload_config(new_config)
    old_engine.stop.assert_called_once()
    factory.assert_called_once_with(new_config.voice)
    assert app.tts_engine is factory.return_value


# ── API ────────────────────────────────────────────────────────────────────────


def test_api_voices_per_engine(home):
    import select_to_speech.api.server as server
    with patch.object(server, "sts_app", None):
        kokoro = server.get_voices("kokoro")
        piper = server.get_voices("piper", "int8")
    assert "ko" not in kokoro  # Kokoro has no Korean voice
    assert [v["id"] for v in kokoro["it"]] == ["if_sara", "im_nicola"]
    assert set(piper) == set(vm.get_piper_languages())
    assert "uz" not in piper
    assert {"id", "name", "quality", "precision", "size_bytes", "installed", "speakers"} <= set(piper["it"][0])


def test_api_installed_models_marks_in_use_and_deletes(home):
    import select_to_speech.api.server as server
    from fastapi import HTTPException
    _install_fake_piper(home, "it_IT-paola-medium")
    fake_app = MagicMock()
    fake_app.config = AppConfig(voice=_piper_config())
    with patch.object(server, "sts_app", fake_app):
        models = server.get_installed_models()
        assert models[0]["in_use"] is True
        assert server.delete_installed_model("piper", "it_IT-paola-medium", "int8") == {"status": "deleted"}
        fake_app.tts_engine.release_model.assert_called_once_with("piper", "it_IT-paola-medium", "int8")
        with pytest.raises(HTTPException) as exc:
            server.delete_installed_model("piper", "it_IT-paola-medium", "int8")
        assert exc.value.status_code == 404
