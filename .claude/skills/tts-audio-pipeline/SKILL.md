---
name: tts-audio-pipeline
description: Load this skill when working on the speech synthesis, text preprocessing, or audio playback pipeline (tts_engine.py, voice_manager.py, audio_player.py, sound_feedback.py, text_normalizer.py, punctuation_engine.py) — including Sherpa-ONNX Kokoro models, language detection, Pedalboard pitch shifting, PyAudio streaming, or PulseAudio/PipeWire ducking.
---

# TTS Synthesis, Text Preprocessing, and Audio Playback Pipeline

Scope: Text normalization, neural punctuation restoration, language detection, Sherpa-ONNX synthesis, voice management, and streaming audio playback in `src/select_to_speech/`.

## 1. End-to-End Processing Flow

1. **Text Normalization (`text_normalizer.py`)**:
   - `normalize_text_for_tts()` runs when `config.text_normalization` is enabled:
     - `dehyphenate()`: rejoins words split across line breaks (`"inter-\nfaccia"` → `"interfaccia"`).
     - `normalize_bullets_and_lists()`: strips bullet markers and ensures list items end with sentence-ending punctuation for natural prosody pauses.
     - `unwrap_lines()`: merges soft-wrapped lines within paragraphs while preserving double-newline paragraph breaks and appending periods after unpunctuated headers.
2. **Neural Punctuation (`punctuation_engine.py`)**:
   - `NeuralPunctuationEngine` wraps `sherpa_onnx.OfflinePunctuation` (`sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8`, stored in `~/.local/share/select-to-speech/punctuation/`).
   - Supports English (`en`) and Chinese (`zh`), lazily initialized and thread-safe via `self._lock`.
3. **Language Detection & Sentence Segmentation (`main.py` & `tts_engine.py`)**:
   - Uses `lingua-language-detector` (`_LINGUA_LANGUAGES` in `main.py`) to detect the language per segment when auto-detection or multi-language voice mapping (`config.voice.language_models`) is active.
   - Expands currency symbols (`_CURRENCY_SYMBOLS`), math symbols (`_SYMBOL_WORDS`), and emojis (`emoji.demojize`) localized to the target language before synthesis.
4. **Sherpa-ONNX Kokoro Synthesis (`tts_engine.py` & `voice_manager.py`)**:
   - Models live in `~/.local/share/select-to-speech/voices/`:
     - `kokoro-multi-lang-v1_0` (FP32, `model.onnx`)
     - `kokoro-int8-multi-lang-v1_0` (INT8, `model.int8.onnx`)
   - Speaker names (`af_heart`, `if_sara`, etc.) map to integer IDs via `SPEAKER_TO_ID` / `ID_TO_SPEAKER` in `voice_manager.py` and language prefixes in `_KOKORO_LANG_PREFIXES`.
   - Language hints are passed to `sherpa_onnx.GenerationConfig(extra={"lang": _KOKORO_LANG_CODES[lang]})`.
5. **Streaming Playback, Pitch Shift & Ducking (`audio_player.py` & `sound_feedback.py`)**:
   - Synthesis runs in a producer thread pushing audio chunks to a bounded `queue.Queue`, consumed by `AudioPlayer.play_stream()`.
   - Pitch shifting uses `pedalboard` (`Pedalboard([PitchShift(...)])`) when `pitch != 1.0`.
   - `AudioDucker` lowers background application sink-inputs via `pulsectl` on a dedicated daemon worker thread (`AudioDucker-Worker`) to avoid PulseAudio/PipeWire connection leaks, skipping its own process via `_is_own_sink_input()`.

## 2. Conventions & Safeguards

- **Thread Safety & Cancellation**:
  - Synthesis and playback run on background threads coordinated by `self._stop_event` (`threading.Event`). Any new loop in `tts_engine.py` or `audio_player.py` must check `stop_event.is_set()` promptly so user stop/pause shortcuts feel instantaneous.
  - Protect lazy model initialization or reconfiguration in `tts_engine.py` and `punctuation_engine.py` with locks.
- **Graceful Native Fallbacks**:
  - Never assume audio hardware, PulseAudio/PipeWire, or downloaded ONNX models exist at import or init time. Guard `pulsectl` with `try ... except (ImportError, OSError)` and check `is_kokoro_installed()` / `is_punct_model_installed()` before loading ONNX sessions.
- **Testing (`tests/`)**:
  - Run tests via `uv run pytest` (e.g., `uv run pytest tests/test_tts_engine.py tests/test_audio_player.py tests/test_text_normalizer.py`).
  - Mock `sherpa_onnx`, `pyaudio.PyAudio`, and `pulsectl.Pulse` in unit tests so tests pass in headless CI without audio devices or 350 MB model files.
