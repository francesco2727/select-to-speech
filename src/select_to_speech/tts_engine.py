"""Text-to-Speech engine using Piper TTS"""

import io
import logging
import re
import wave
from pathlib import Path
from typing import Optional, Tuple, Dict

from piper.voice import PiperVoice
from piper.config import SynthesisConfig

from .config import get_data_dir, VoiceConfig


logger = logging.getLogger(__name__)


class TTSEngine:
    """Text-to-Speech engine wrapper for Piper TTS"""

    def __init__(self, voice_config: VoiceConfig):
        """
        Initialize the TTS engine.

        Args:
            voice_config: Voice configuration with model name
        """
        self.voice_config = voice_config
        self.voices: Dict[str, PiperVoice] = {}
        self.current_model: str = self.voice_config.model
        self.voices_dir = get_data_dir() / "voices"
        self.voices_dir.mkdir(parents=True, exist_ok=True)

    def _get_voice_path(self, model_name: str) -> Path:
        """Get the path to the voice model file"""
        return self.voices_dir / f"{model_name}.onnx"

    def _sanitize_text(self, text: str) -> str:
        """
        Sanitize text for TTS processing.
        
        Args:
            text: Raw text
            
        Returns:
            Sanitized text safe for TTS
        """
        # Replace triple quotes with single quotes
        text = text.replace('"""', '"')
        text = text.replace("'''", "'")
        
        # Normalize whitespace (collapse multiple spaces/newlines)
        text = re.sub(r'\s+', ' ', text)
        
        # Remove non-printable characters except basic punctuation
        # Keep: letters, numbers, spaces, and common punctuation
        text = re.sub(r'[^\w\s.,!?;:\'\"-]', '', text)
        
        # Strip leading/trailing whitespace
        text = text.strip()
        
        logger.debug(f"Sanitized: '{text[:100]}{'...' if len(text) > 100 else ''}'")
        return text

    def get_model_for_language(self, language: str) -> str:
        """
        Get model name for a specific language.
        Falls back to default model if language not configured.
        """
        model = self.voice_config.language_models.get(language)
        if model:
            return model
        
        logger.warning(f"No voice model configured for language '{language}', using default: {self.voice_config.model}")
        return self.voice_config.model

    def ensure_voice_loaded(self, model_name: str) -> bool:
        """
        Ensure a specific voice model is loaded.

        Args:
            model_name: Name of the model to load

        Returns:
            True if successful, False otherwise
        """
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
            voice = PiperVoice.load(str(voice_path))
            self.voices[model_name] = voice
            return True

        except Exception as e:
            logger.error(f"Failed to load voice model {model_name}: {e}")
            return False

    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0) -> Optional[Tuple[bytes, int]]:
        """
        Synthesize text to speech.

        Args:
            text: Text to synthesize
            language: Optional language code to select voice
            speed: Speech speed multiplier
            volume: Audio volume multiplier

        Returns:
            Tuple of (audio_bytes, sample_rate) or None if failed
        """
        if not text:
            return None

        # Determine model based on language
        target_model = self.voice_config.model
        if language:
            target_model = self.get_model_for_language(language)

        if not self.ensure_voice_loaded(target_model):
            # Fallback to default if target failed to load and was different
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

            # Sanitize text for TTS processing
            original_text = text
            text = self._sanitize_text(text)
            
            if not text:
                logger.warning(f"Text became empty after sanitization. Original: '{original_text[:100]}'")
                return None

            logger.debug(f"Synthesizing text with model {target_model}: '{text[:100]}{'...' if len(text) > 100 else ''}'")
            
            # Create synthesis config for speed and volume
            syn_config = SynthesisConfig(
                length_scale=1.0 / speed if speed > 0 else 1.0,
                volume=volume
            )
            
            # Synthesize to WAV using synthesize_wav which properly writes WAV data
            with io.BytesIO() as output:
                with wave.open(output, "wb") as wav_file:
                    voice.synthesize_wav(text, wav_file, syn_config=syn_config)
                
                audio_bytes = output.getvalue()
                
            # Get sample rate from voice
            sample_rate = voice.config.sample_rate

            logger.info(f"Synthesized {len(text)} chars to {len(audio_bytes)} bytes at {sample_rate}Hz using {target_model}")
            
            return audio_bytes, sample_rate

        except Exception as e:
            logger.error(f"TTS Engine failed to synthesize text. Check if the voice model is corrupted or missing. Error: {e}", exc_info=True)
            return None

    def stop(self) -> None:
        """Stop the TTS engine and cleanup"""
        self.voices.clear()
        logger.info("TTS engine stopped")
