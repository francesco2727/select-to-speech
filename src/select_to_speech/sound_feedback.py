"""Sound feedback generator and player using PyAudio and NumPy for UI earcons."""

import logging
import threading
from typing import Optional
import numpy as np
import pyaudio

logger = logging.getLogger(__name__)


class SoundFeedback:
    """Generates and plays short, pleasant synthetic UI sound feedback tones."""

    _lock = threading.Lock()

    @classmethod
    def _generate_tone(cls, freq: float, duration_s: float, volume: float = 0.15, sample_rate: int = 44100) -> np.ndarray:
        """Generate a smooth sine wave tone with attack and decay envelope."""
        n_samples = int(sample_rate * duration_s)
        if n_samples <= 0:
            return np.zeros(0, dtype=np.int16)

        t = np.linspace(0, duration_s, n_samples, endpoint=False)
        signal = np.sin(2 * np.pi * freq * t)

        # Attack and decay envelope to prevent clicks
        attack_samples = min(int(0.012 * sample_rate), n_samples // 4)
        decay_samples = min(int(0.025 * sample_rate), n_samples // 3)

        envelope = np.ones(n_samples)
        if attack_samples > 0:
            envelope[:attack_samples] = np.linspace(0.0, 1.0, attack_samples)
        if decay_samples > 0:
            envelope[-decay_samples:] = np.linspace(1.0, 0.0, decay_samples)

        samples = (signal * envelope * volume * 32767).astype(np.int16)
        return samples

    @classmethod
    def _play_audio_bytes(cls, audio_data: bytes, sample_rate: int = 44100) -> None:
        """Play PCM 16-bit audio bytes in a thread-safe manner."""
        def _worker():
            with cls._lock:
                pa = None
                stream = None
                try:
                    pa = pyaudio.PyAudio()
                    stream = pa.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=sample_rate,
                        output=True
                    )
                    stream.write(audio_data)
                except Exception as e:
                    logger.debug(f"Could not play sound feedback tone: {e}")
                finally:
                    if stream:
                        try:
                            stream.stop_stream()
                            stream.close()
                        except Exception:
                            pass
                    if pa:
                        try:
                            pa.terminate()
                        except Exception:
                            pass

        threading.Thread(target=_worker, daemon=True).start()

    @classmethod
    def play_start(cls, volume: float = 0.18) -> None:
        """Pleasant rising chime (C5 -> E5) when text selection reading starts."""
        try:
            tone1 = cls._generate_tone(523.25, 0.055, volume)
            tone2 = cls._generate_tone(659.25, 0.075, volume)
            combined = np.concatenate([tone1, tone2])
            cls._play_audio_bytes(combined.tobytes())
        except Exception as e:
            logger.debug(f"Error playing start tone: {e}")

    @classmethod
    def play_ocr_start(cls, volume: float = 0.18) -> None:
        """Crisp activation chime (E5 -> A5) when OCR screen capture starts."""
        try:
            tone1 = cls._generate_tone(659.25, 0.045, volume)
            tone2 = cls._generate_tone(880.00, 0.065, volume)
            combined = np.concatenate([tone1, tone2])
            cls._play_audio_bytes(combined.tobytes())
        except Exception as e:
            logger.debug(f"Error playing OCR start tone: {e}")

    @classmethod
    def play_ocr_success(cls, volume: float = 0.18) -> None:
        """Cheerful major triad (C5 -> E5 -> G5) when OCR extraction succeeds."""
        try:
            tone1 = cls._generate_tone(523.25, 0.045, volume)
            tone2 = cls._generate_tone(659.25, 0.045, volume)
            tone3 = cls._generate_tone(783.99, 0.080, volume)
            combined = np.concatenate([tone1, tone2, tone3])
            cls._play_audio_bytes(combined.tobytes())
        except Exception as e:
            logger.debug(f"Error playing OCR success tone: {e}")

    @classmethod
    def play_error(cls, volume: float = 0.18) -> None:
        """Gentle descending alert tone (F#3 -> D3) on error / cancelled / no text."""
        try:
            tone1 = cls._generate_tone(185.0, 0.080, volume)
            tone2 = cls._generate_tone(146.83, 0.120, volume)
            combined = np.concatenate([tone1, tone2])
            cls._play_audio_bytes(combined.tobytes())
        except Exception as e:
            logger.debug(f"Error playing error tone: {e}")
