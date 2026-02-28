"""Text-to-Speech engine implementations"""

import io
import logging
import re
import wave
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Dict, Iterator
import threading

import requests
import soundfile as sf
import numpy as np

from .config import get_data_dir, VoiceConfig

logger = logging.getLogger(__name__)


class BaseTTSEngine(ABC):
    """Abstract base class for TTS engines"""

    def __init__(self, voice_config: VoiceConfig):
        self.voice_config = voice_config
        self.voices_dir = get_data_dir() / "voices"
        self.voices_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_text(self, text: str) -> str:
        """Sanitize text for TTS processing."""
        text = text.replace('"""', '"')
        text = text.replace("'''", "'")
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s.,!?;:\'\"-]', '', text)
        text = text.strip()
        logger.debug(f"Sanitized: '{text[:100]}{'...' if len(text) > 100 else ''}'")
        return text

    def _chunk_text(self, text: str, max_chars: int = 180) -> list[str]:
        """Split text into logical, speakable chunks for streaming TTS."""
        text = self._sanitize_text(text)
        
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
    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0) -> Optional[Tuple[bytes, int]]:
        """Synthesize text to speech."""
        pass

    @abstractmethod
    def synthesize_stream(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0) -> Iterator[Tuple[bytes, int]]:
        """Synthesize text to speech as a stream."""
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

    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0) -> Optional[Tuple[bytes, int]]:
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

            text = self._sanitize_text(text)
            
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

    def synthesize_stream(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0) -> Iterator[Tuple[bytes, int]]:
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
        
        for chunk in self._chunk_text(text):
            try:
                if not chunk.strip():
                    continue

                with io.BytesIO() as output:
                    with wave.open(output, "wb") as wav_file:
                        voice.synthesize_wav(chunk, wav_file, syn_config=syn_config)
                    
                    audio_bytes = output.getvalue()
                    
                sample_rate = voice.config.sample_rate
                logger.debug(f"Synthesized streaming chunk: {len(chunk)} chars")
                yield audio_bytes, sample_rate

            except Exception as e:
                logger.error(f"Failed synthesising chunk. Error: {e}", exc_info=True)

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
        
    def _download_file(self, url: str, path: Path) -> bool:
        """Download a file with streaming to handle large files"""
        try:
            logger.info(f"Downloading {path.name} from {url}...")
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            with open(path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Successfully downloaded {path.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            if path.exists():
                path.unlink()
            return False

    def ensure_model_downloaded(self) -> bool:
        """Download kokoro model and voices.bin if they don't exist"""
        if self.model_path.exists() and self.voices_bin_path.exists():
            return True
            
        logger.info("Checking Kokoro models. They will be downloaded if missing (approx 350MB)...")
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        
        files_to_download = [
            ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx", self.model_path),
            ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin", self.voices_bin_path)
        ]
        
        for url, path in files_to_download:
            if not path.exists():
                if not self._download_file(url, path):
                    return False
        
        return True

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
            return True
        except ImportError:
            logger.error("kokoro-onnx is not installed. KokoroEngine cannot be used.")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Kokoro: {e}", exc_info=True)
            return False

    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0) -> Optional[Tuple[bytes, int]]:
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

            text = self._sanitize_text(text)
            if not text:
                return None

            logger.debug(f"Synthesizing text with voice {target_voice}: '{text[:100]}{'...' if len(text) > 100 else ''}'")
            
            lang_code = "en-us"
            if language == "it":
                lang_code = "it"
            elif language == "fr":
                lang_code = "fr"
            elif language == "es":
                lang_code = "es"

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

    def synthesize_stream(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0) -> Iterator[Tuple[bytes, int]]:
        if not text:
            return

        target_voice = self.voice_config.model
        if language:
            target_voice = self.get_model_for_language(language)

        if not self._init_kokoro():
            return

        lang_code = "en-us"
        if language == "it":
            lang_code = "it"
        elif language == "fr":
            lang_code = "fr"
        elif language == "es":
            lang_code = "es"

        for chunk in self._chunk_text(text):
            try:
                if not chunk.strip():
                    continue

                logger.debug(f"Synthesizing stream chunk with voice {target_voice}: '{chunk[:100]}{'...' if len(chunk) > 100 else ''}'")
                
                with self._lock:
                    # Kokoro returns samples in [-1, 1] range, and sample_rate
                    samples, sample_rate = self.kokoro.create(
                        chunk,
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

                logger.debug(f"Synthesized streaming chunk: {len(chunk)} chars")
                yield audio_bytes, sample_rate

            except Exception as e:
                logger.error(f"Failed synthesising chunk. Error: {e}", exc_info=True)

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

