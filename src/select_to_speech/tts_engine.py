"""Text-to-Speech engine implementations"""

import io
import logging
import re
import time
import wave
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Dict, Iterator
import threading

import soundfile as sf
import numpy as np

from .config import get_data_dir, VoiceConfig

logger = logging.getLogger(__name__)


def _retry_synthesis(func, max_retries: int = 3, base_delay: float = 0.5):
    """Call func() up to max_retries times with exponential backoff. Re-raises on final failure."""
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), 4.0)
                logger.warning(
                    f"TTS synthesis attempt {attempt + 1}/{max_retries} failed, "
                    f"retrying in {delay:.1f}s: {exc}"
                )
                time.sleep(delay)
    raise last_exc


# Kokoro voice-name prefixes by language
_KOKORO_LANG_PREFIXES: dict[str, list[str]] = {
    "en": ["af_", "am_", "bf_", "bm_"],
    "es": ["ef_", "em_"],
    "fr": ["ff_", "fm_"],
    "hi": ["hf_", "hm_"],
    "it": ["if_", "im_"],
    "ja": ["jf_", "jm_"],
    "ko": ["kf_"],
    "pt": ["pf_", "pm_"],
    "zh": ["zf_", "zm_"],
}

# Kokoro lang_code used by kokoro.create(lang=...)
_KOKORO_LANG_CODES: dict[str, str] = {
    "en": "en-us",
    "es": "es",
    "fr": "fr",
    "hi": "hi",
    "it": "it",
    "ja": "ja",
    "ko": "ko",
    "pt": "pt-br",
    "zh": "zh",
}

# Word mappings for mathematical symbols and punctuation by language
_SYMBOL_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "percent": "percent",
        "plus": "plus",
        "minus": "minus",
        "times": "times",
        "divide": "divided by",
        "equals": "equals",
        "less": "less than",
        "greater": "greater than",
        "dot": "dot",
    },
    "it": {
        "percent": "percento",
        "plus": "più",
        "minus": "meno",
        "times": "per",
        "divide": "diviso",
        "equals": "uguale",
        "less": "minore di",
        "greater": "maggiore di",
        "dot": "punto",
    },
    "es": {
        "percent": "por ciento",
        "plus": "más",
        "minus": "menos",
        "times": "por",
        "divide": "dividido por",
        "equals": "igual a",
        "less": "menor que",
        "greater": "mayor que",
        "dot": "punto",
    },
    "fr": {
        "percent": "pour cent",
        "plus": "plus",
        "minus": "moins",
        "times": "fois",
        "divide": "divisé par",
        "equals": "égal",
        "less": "inférieur à",
        "greater": "supérieur à",
        "dot": "point",
    },
    "de": {
        "percent": "Prozent",
        "plus": "plus",
        "minus": "minus",
        "times": "mal",
        "divide": "geteilt durch",
        "equals": "gleich",
        "less": "kleiner als",
        "greater": "größer als",
        "dot": "Punkt",
    },
    "pt": {
        "percent": "por cento",
        "plus": "mais",
        "minus": "menos",
        "times": "vezes",
        "divide": "dividido por",
        "equals": "igual a",
        "less": "menor que",
        "greater": "maior que",
        "dot": "ponto",
    },
}


class BaseTTSEngine(ABC):
    """Abstract base class for TTS engines"""

    def __init__(self, voice_config: VoiceConfig):
        self.voice_config = voice_config
        self.voices_dir = get_data_dir() / "voices"
        self.voices_dir.mkdir(parents=True, exist_ok=True)

    def preprocess_text(self, text: str, language: Optional[str] = None) -> str:
        """Preprocess text to replace mathematical symbols and dots in domains/filenames with words."""
        if not text:
            return text

        # Normalize language code (e.g. "en-us" -> "en", "it_IT" -> "it")
        lang_key = (language or "").split("-")[0].split("_")[0].lower()
        if lang_key not in _SYMBOL_WORDS:
            lang_key = "en"
        words = _SYMBOL_WORDS[lang_key]

        # 1. Replace dots in domains/filenames
        # Matches dots preceded by a letter/hyphen/underscore and followed by alphanumeric/hyphen/underscore,
        # or preceded by alphanumeric/hyphen/underscore and followed by a letter/hyphen/underscore.
        # This excludes decimal numbers like 3.14 or versions like 1.0.
        dot_pattern = r'(?<=[a-zA-Z_-])\.(?=[a-zA-Z0-9_-])|(?<=[a-zA-Z0-9_-])\.(?=[a-zA-Z_-])'
        text = re.sub(dot_pattern, f" {words['dot']} ", text)

        # 2. Replace percent symbol (%)
        text = text.replace('%', f" {words['percent']} ")

        # 3. Replace plus symbol (+)
        text = text.replace('+', f" {words['plus']} ")

        # 4. Replace minus symbol (-) when used mathematically
        # Surrounded by spaces: " - "
        text = re.sub(r'\s+-\s+', f" {words['minus']} ", text)
        # Negative sign before a digit: "-5" (must be preceded by whitespace or start of string)
        text = re.sub(r'(^|\s)-(?=\d)', rf'\1{words["minus"]} ', text)

        # 5. Replace times symbol (*) when used mathematically (between digits or surrounded by spaces)
        text = re.sub(r'(?<=\d)\s*\*\s*(?=\d)', f" {words['times']} ", text)
        text = re.sub(r'\s+\*\s+', f" {words['times']} ", text)

        # 6. Replace division symbol (/) when used mathematically (between digits or surrounded by spaces)
        text = re.sub(r'(?<=\d)\s*/\s*(?=\d)', f" {words['divide']} ", text)
        text = re.sub(r'\s+/\s+', f" {words['divide']} ", text)

        # 7. Replace equals symbol (=)
        text = text.replace('=', f" {words['equals']} ")

        # 8. Replace less than (<) and greater than (>)
        text = text.replace('<', f" {words['less']} ")
        text = text.replace('>', f" {words['greater']} ")

        return text

    def _sanitize_text(self, text: str, language: Optional[str] = None) -> str:
        """Sanitize text for TTS processing."""
        text = self.preprocess_text(text, language)
        text = text.replace('"""', '"')
        text = text.replace("'''", "'")
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s.,!?;:\'\"-]', '', text)
        text = text.strip()
        logger.debug(f"Sanitized: '{text[:100]}{'...' if len(text) > 100 else ''}'")
        return text

    def _chunk_text(self, text: str, max_chars: int = 180, language: Optional[str] = None) -> list[str]:
        """Split text into logical, speakable chunks for streaming TTS."""
        # Normalize newlines to sentence boundaries before sanitization so that
        # paragraph/line breaks produce natural TTS pauses.
        # Lines not ending with sentence punctuation get a period appended.
        text = re.sub(r'([^.!?])\n+', r'\1. ', text)
        text = re.sub(r'([.!?])\n+', r'\1 ', text)

        text = self._sanitize_text(text, language=language)
        
        # 1. Split by strong sentence boundaries (. ! ?) keeping the punctuation attached
        raw_sentences = re.split(r'(?<=[.!?])\s+', text)
        
        chunks = []
        current_chunk = ""
        
        for sentence in raw_sentences:
            sentence = sentence.strip()
            if not sentence: continue
                
            # 2. If a sentence is still too long, break it by weak boundaries (, ; : —)
            if len(sentence) > max_chars:
                weak_parts = re.split(r'(?<=[,;:—])\s+', sentence)
                for part in weak_parts:
                    part = part.strip()
                    if not part: continue
                    
                    if len(current_chunk) + len(part) < max_chars:
                        current_chunk += (" " + part) if current_chunk else part
                    else:
                        if current_chunk: chunks.append(current_chunk)
                        current_chunk = part
            else:
                if len(current_chunk) + len(sentence) < max_chars:
                    current_chunk += (" " + sentence) if current_chunk else sentence
                else:
                    if current_chunk: chunks.append(current_chunk)
                    current_chunk = sentence
                    
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    def get_model_for_language(self, language: str) -> str:
        """Get model name for a specific language."""
        model = self.voice_config.language_models.get(language)
        if model:
            return model
        logger.warning(f"No voice model configured for language '{language}', using default: {self.voice_config.model}")
        return self.voice_config.model

    @abstractmethod
    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Optional[Tuple[bytes, int]]:
        """Synthesize text to speech.

        Args:
            phoneme_lang: If set, overrides the phonemization language without
                changing the voice (e.g. use Italian voice with English
                phonemization for loanwords).
        """
        pass

    @abstractmethod
    def synthesize_stream(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Iterator[Tuple[bytes, int]]:
        """Synthesize text to speech as a stream.

        Args:
            phoneme_lang: If set, overrides the phonemization language without
                changing the voice.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the TTS engine and cleanup"""
        pass


class PiperEngine(BaseTTSEngine):
    """Text-to-Speech engine wrapper for Piper TTS"""

    def __init__(self, voice_config: VoiceConfig):
        super().__init__(voice_config)
        self.voices: Dict[str, "PiperVoice"] = {}
        try:
            from piper.voice import PiperVoice
            self.PiperVoice = PiperVoice
        except ImportError:
            logger.error("piper-tts is not installed. PiperEngine cannot be used.")
            self.PiperVoice = None

    def _get_voice_path(self, model_name: str) -> Path:
        return self.voices_dir / f"{model_name}.onnx"

    def ensure_voice_loaded(self, model_name: str) -> bool:
        if not self.PiperVoice:
            return False

        if model_name in self.voices:
            return True

        try:
            voice_path = self._get_voice_path(model_name)

            if not voice_path.exists():
                logger.error(
                    f"Voice model not found: {voice_path}\n"
                    f"Download voice models from: https://huggingface.co/rhasspy/piper-voices\n"
                    f"Note: Both .onnx and .onnx.json files are required for each voice."
                )
                return False

            logger.info(f"Loading voice model: {model_name}")
            voice = self.PiperVoice.load(str(voice_path))
            self.voices[model_name] = voice
            return True

        except Exception as e:
            logger.error(f"Failed to load voice model {model_name}: {e}")
            return False

    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Optional[Tuple[bytes, int]]:
        if not text:
            return None

        from piper.config import SynthesisConfig

        target_model = self.voice_config.model
        if language:
            target_model = self.get_model_for_language(language)

        if not self.ensure_voice_loaded(target_model):
            if target_model != self.voice_config.model:
                logger.warning(f"Failed to load {target_model}, falling back to default {self.voice_config.model}")
                target_model = self.voice_config.model
                if not self.ensure_voice_loaded(target_model):
                    return None
            else:
                return None
        
        voice = self.voices[target_model]

        try:
            if not text.strip():
                logger.warning("Empty text provided for synthesis")
                return None

            text = self._sanitize_text(text, language=language)
            
            if not text:
                return None

            logger.debug(f"Synthesizing text with model {target_model}: '{text[:100]}{'...' if len(text) > 100 else ''}'")
            
            syn_config = SynthesisConfig(
                length_scale=1.0 / speed if speed > 0 else 1.0,
                volume=volume
            )
            
            with io.BytesIO() as output:
                with wave.open(output, "wb") as wav_file:
                    voice.synthesize_wav(text, wav_file, syn_config=syn_config)
                
                audio_bytes = output.getvalue()
                
            sample_rate = voice.config.sample_rate

            logger.info(f"Synthesized {len(text)} chars to {len(audio_bytes)} bytes at {sample_rate}Hz using {target_model}")
            
            return audio_bytes, sample_rate

        except Exception as e:
            logger.error(f"TTS Engine failed to synthesize text. Error: {e}", exc_info=True)
            return None

    def synthesize_stream(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Iterator[Tuple[bytes, int]]:
        if not text:
            return

        from piper.config import SynthesisConfig

        target_model = self.voice_config.model
        if language:
            target_model = self.get_model_for_language(language)

        if not self.ensure_voice_loaded(target_model):
            if target_model != self.voice_config.model:
                logger.warning(f"Failed to load {target_model}, falling back to default {self.voice_config.model}")
                target_model = self.voice_config.model
                if not self.ensure_voice_loaded(target_model):
                    return
            else:
                return
        
        voice = self.voices[target_model]

        syn_config = SynthesisConfig(
            length_scale=1.0 / speed if speed > 0 else 1.0,
            volume=volume
        )
        
        for chunk in self._chunk_text(text, language=language):
            if not chunk.strip():
                continue
            try:
                def _synth(c=chunk):
                    with io.BytesIO() as output:
                        with wave.open(output, "wb") as wav_file:
                            voice.synthesize_wav(c, wav_file, syn_config=syn_config)
                        return output.getvalue(), voice.config.sample_rate

                audio_bytes, sample_rate = _retry_synthesis(_synth)
                logger.debug(f"Synthesized streaming chunk: {len(chunk)} chars")
                yield audio_bytes, sample_rate

            except Exception as e:
                logger.error(f"Failed synthesising chunk after retries. Error: {e}", exc_info=True)

    def stop(self) -> None:
        self.voices.clear()
        logger.info("Piper TTS engine stopped")


class KokoroEngine(BaseTTSEngine):
    """Text-to-Speech engine wrapper for Kokoro ONNX"""

    def __init__(self, voice_config: VoiceConfig):
        super().__init__(voice_config)
        self.model_path = self.voices_dir / "kokoro-v1.0.onnx"
        self.voices_bin_path = self.voices_dir / "voices-v1.0.bin"
        
        self.kokoro = None
        self._lock = threading.Lock()
        
    def ensure_model_downloaded(self) -> bool:
        """Download kokoro model and voices.bin if they don't exist."""
        from . import voice_manager
        if voice_manager.is_kokoro_installed():
            return True
        logger.info("Kokoro models missing — downloading (~350 MB)…")
        return voice_manager.download_kokoro()

    def _init_kokoro(self) -> bool:
        if self.kokoro is not None:
            return True
            
        if not self.ensure_model_downloaded():
            return False
            
        try:
            from kokoro_onnx import Kokoro
            with self._lock:
                if self.kokoro is None:
                    logger.info("Initializing Kokoro ONNX model...")
                    self.kokoro = Kokoro(str(self.model_path), str(self.voices_bin_path))
                    
                    # Intercept tokenizer.phonemize to strip espeak-ng language tags.
                    # espeak-ng outputs language switch tags (e.g., '(en)', '(it)') when it
                    # automatically detects foreign words during phonemization.
                    # Because these tags' characters are in Kokoro's vocabulary, Kokoro
                    # otherwise literally tokenizes and pronounces them (e.g., saying 'it'
                    # at the end of 'team' when processing in Italian).
                    original_phonemize = self.kokoro.tokenizer.phonemize
                    
                    def patched_phonemize(text: str, lang: str = "en-us", norm: bool = True) -> str:
                        phonemes = original_phonemize(text, lang=lang, norm=norm)
                        # Remove language switch tags like (en), (it), (fr), (es), etc.
                        return re.sub(r'\([a-z]{2}\)', '', phonemes)
                        
                    self.kokoro.tokenizer.phonemize = patched_phonemize
            return True
        except ImportError:
            logger.error("kokoro-onnx is not installed. KokoroEngine cannot be used.")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Kokoro: {e}", exc_info=True)
            return False

    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Optional[Tuple[bytes, int]]:
        if not text:
            return None

        target_voice = self.voice_config.model
        if language:
            target_voice = self.get_model_for_language(language)

        if not self._init_kokoro():
            return None

        try:
            if not text.strip():
                logger.warning("Empty text provided for synthesis")
                return None

            text = self._sanitize_text(text, language=language)
            if not text:
                return None

            logger.debug(f"Synthesizing text with voice {target_voice}: '{text[:100]}{'...' if len(text) > 100 else ''}'")

            # phoneme_lang overrides the phonemization language while keeping the same voice
            effective_lang = phoneme_lang or language
            lang_code = _KOKORO_LANG_CODES.get(effective_lang, "en-us") if effective_lang else "en-us"

            with self._lock:
                # Kokoro returns samples in [-1, 1] range, and sample_rate
                samples, sample_rate = self.kokoro.create(
                    text,
                    voice=target_voice,
                    speed=speed,
                    lang=lang_code
                )
            
            # Apply volume scaling
            if volume != 1.0:
                samples = samples * volume
                # Clip to prevent overflow
                samples = np.clip(samples, -1.0, 1.0)
                
            # Convert to WAV bytes using soundfile
            with io.BytesIO() as output:
                sf.write(output, samples, sample_rate, format='WAV', subtype='PCM_16')
                audio_bytes = output.getvalue()

            logger.info(f"Synthesized {len(text)} chars to {len(audio_bytes)} bytes at {sample_rate}Hz using {target_voice}")
            
            return audio_bytes, sample_rate

        except Exception as e:
            logger.error(f"Kokoro Engine failed to synthesize text. Error: {e}", exc_info=True)
            return None

    def synthesize_stream(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Iterator[Tuple[bytes, int]]:
        if not text:
            return

        target_voice = self.voice_config.model
        if language:
            target_voice = self.get_model_for_language(language)

        if not self._init_kokoro():
            return

        # phoneme_lang overrides the phonemization language while keeping the same voice
        effective_lang = phoneme_lang or language
        lang_code = _KOKORO_LANG_CODES.get(effective_lang, "en-us") if effective_lang else "en-us"

        for chunk in self._chunk_text(text, language=language):
            if not chunk.strip():
                continue
            logger.debug(f"Synthesizing stream chunk with voice {target_voice}: '{chunk[:100]}{'...' if len(chunk) > 100 else ''}'")
            try:
                def _synth(c=chunk):
                    with self._lock:
                        # Kokoro returns samples in [-1, 1] range, and sample_rate
                        samples, sample_rate = self.kokoro.create(
                            c,
                            voice=target_voice,
                            speed=speed,
                            lang=lang_code
                        )
                    # Apply volume scaling
                    if volume != 1.0:
                        samples = np.clip(samples * volume, -1.0, 1.0)
                    # Convert to WAV bytes using soundfile
                    with io.BytesIO() as output:
                        sf.write(output, samples, sample_rate, format='WAV', subtype='PCM_16')
                        return output.getvalue(), sample_rate

                audio_bytes, sample_rate = _retry_synthesis(_synth)
                logger.debug(f"Synthesized streaming chunk: {len(chunk)} chars")
                yield audio_bytes, sample_rate

            except Exception as e:
                logger.error(f"Failed synthesising chunk after retries. Error: {e}", exc_info=True)

    def stop(self) -> None:
        self.kokoro = None
        logger.info("Kokoro engine stopped")


def get_tts_engine(config: VoiceConfig) -> BaseTTSEngine:
    """Factory function to get the configured TTS engine"""
    if config.engine == "kokoro":
        return KokoroEngine(config)
    elif config.engine == "piper":
        return PiperEngine(config)
    else:
        logger.warning(f"Unknown TTS engine '{config.engine}', falling back to Kokoro")
        return KokoroEngine(config)


def get_available_models(engine: str) -> list[str]:
    """Scan the data directory for installed models for *engine*."""
    voices_dir = get_data_dir() / "voices"
    if not voices_dir.exists():
        return []

    if engine == "kokoro":
        # Kokoro models are kokoro-*.onnx sitting directly in voices_dir
        return sorted(
            p.stem for p in voices_dir.glob("kokoro*.onnx")
        )
    elif engine == "piper":
        # Piper voice files are <name>.onnx (with companion .onnx.json)
        return sorted(
            p.stem
            for p in voices_dir.glob("*.onnx")
            if not p.stem.startswith("kokoro")
        )
    return []


def get_kokoro_voices(language: str | None = None) -> list[str]:
    """Return Kokoro voice names from the installed voices-v1.0.bin file.

    If *language* is given, only voices whose prefix matches the language are
    returned (e.g. ``"it"`` → ``if_*``, ``im_*``).
    """
    voices_bin = get_data_dir() / "voices" / "voices-v1.0.bin"
    if not voices_bin.exists():
        return []
    try:
        data = np.load(str(voices_bin), allow_pickle=False)
        all_voices: list[str] = sorted(data.files)
    except Exception:
        logger.warning("Failed to read Kokoro voices from %s", voices_bin)
        return []

    if language is None:
        return all_voices

    prefixes = _KOKORO_LANG_PREFIXES.get(language, [])
    if not prefixes:
        return []  # unsupported language → empty list
    return [v for v in all_voices if any(v.startswith(p) for p in prefixes)]


def get_voices_for_language(engine: str, language: str) -> list[str]:
    """Return the voice/model names available for *engine* + *language*.

    * **kokoro** — reads the voices binary and filters by language prefix.
    * **piper** — filters installed ``.onnx`` models by the ``{lang}_`` prefix
      (e.g. ``it_IT-paola-medium`` starts with ``it_``).
    """
    if engine == "kokoro":
        return get_kokoro_voices(language)
    elif engine == "piper":
        prefix = f"{language}_"
        return [m for m in get_available_models("piper") if m.startswith(prefix)]
    return []

