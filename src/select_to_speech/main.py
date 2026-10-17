"""Main application entry point"""

import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
import threading
import queue
import time
from pathlib import Path
from typing import Optional

from lingua import Language, LanguageDetectorBuilder

from .config import load_config, AppConfig
from .keyboard_handler import KeyboardHandler
from .selection_listener import WaylandSelectionListener
from .tts_engine import get_tts_engine
from .audio_player import AudioPlayer
from .ocr_engine import OcrEngine
from .screen_capture import ScreenCapture
from .sound_feedback import SoundFeedback



# ISO 639-1 code → lingua Language enum
_LINGUA_LANGUAGES: dict[str, Language] = {
    "en": Language.ENGLISH,
    "it": Language.ITALIAN,
    "es": Language.SPANISH,
    "fr": Language.FRENCH,
    "de": Language.GERMAN,
    "pt": Language.PORTUGUESE,
    "hi": Language.HINDI,
    "ja": Language.JAPANESE,
    "ko": Language.KOREAN,
    "zh": Language.CHINESE,
}

logger = logging.getLogger(__name__)


class SelectToSpeechApp:
    """Main application class"""

    def __init__(self, config: Optional[AppConfig] = None):
        """
        Initialize the application.

        Args:
            config: Application configuration (loaded from file if not provided)
        """
        self.config = config or load_config()
        self._setup_logging()

        logger.info("Initializing Select-to-Speech application")

        # Initialize components
        self.tts_engine = get_tts_engine(self.config.voice)
        self.audio_player = AudioPlayer(self.config.audio.device_id)
        self.audio_player.ducker.enabled = self.config.audio.ducking
        self.ocr_engine = OcrEngine()
        from .punctuation_engine import NeuralPunctuationEngine
        threads = getattr(self.config.voice, "num_threads", 0) or 2
        provider = getattr(self.config.voice, "provider", "cpu") or "cpu"
        self.punctuation_engine = NeuralPunctuationEngine(num_threads=threads, provider=provider)
        self._lingua_detector = self._build_lingua_detector()
        self.selection_listener = WaylandSelectionListener(
            on_selection_change=self._on_text_selected,
        )
        self.keyboard_handler = KeyboardHandler(
            on_play=self._on_shortcut_pressed,
            on_pause=self._on_pause_pressed,
            on_stop=self._on_stop_pressed,
            on_ocr=self._on_ocr_pressed,
            modifier=self.config.keyboard.modifier_key,
            trigger_key=self.config.keyboard.trigger_key,
            pause_key=self.config.keyboard.pause_key,
            stop_key=self.config.keyboard.stop_key,
            ocr_key=self.config.keyboard.ocr_key,
        )

        self.should_exit = False
        self._process_thread: Optional[threading.Thread] = None
        self._ocr_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._shortcut_lock = threading.Lock()
        self._last_shortcut_time: float = 0.0
        self._last_stop_time: float = 0.0

        # Pre-warm TTS engine in background daemon thread
        threading.Thread(target=self.tts_engine.warmup, daemon=True, name="TTS-Warmup").start()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _setup_logging(self) -> None:
        """Setup logging configuration"""
        level = logging.DEBUG if self.config.debug else logging.INFO
        
        # Setup file logging with rotation (5MB max per file, 2 backups)
        log_dir = Path.home() / ".local" / "state" / "select-to-speech"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
        
        handlers: list[logging.Handler] = [
            RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
        ]

        # Add stdout logging for terminal sessions or debugging
        handlers.append(logging.StreamHandler(sys.stdout))

        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
            force=True,
        )

    def _signal_handler(self, signum, frame) -> None:
        """Handle system signals for graceful shutdown"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.should_exit = True

    def reload_config(self, config: AppConfig) -> None:
        """Reload configuration and update running handlers/components"""
        logger.info("Reloading configuration...")
        self.config = config

        # 1. Update TTS engine config
        self.tts_engine.update_config(config.voice)
        threads = getattr(config.voice, "num_threads", 0) or 2
        provider = getattr(config.voice, "provider", "cpu") or "cpu"
        self.punctuation_engine.update_config(num_threads=threads, provider=provider)

        # 2. Update Audio player device_id (recreate if changed) and ducking
        if self.audio_player.device_id != config.audio.device_id:
            logger.info(f"Updating audio device ID to {config.audio.device_id}")
            self.audio_player.stop()
            self.audio_player = AudioPlayer(config.audio.device_id)
        self.audio_player.ducker.enabled = config.audio.ducking

        # 3. Update keyboard shortcuts (restart listener with new keys)
        logger.info("Recreating keyboard handler with new shortcuts...")
        self.keyboard_handler.stop()
        self.keyboard_handler = KeyboardHandler(
            on_play=self._on_shortcut_pressed,
            on_pause=self._on_pause_pressed,
            on_stop=self._on_stop_pressed,
            on_ocr=self._on_ocr_pressed,
            modifier=config.keyboard.modifier_key,
            trigger_key=config.keyboard.trigger_key,
            pause_key=config.keyboard.pause_key,
            stop_key=config.keyboard.stop_key,
            ocr_key=config.keyboard.ocr_key,
        )
        self.keyboard_handler.start()

        # 4. Rebuild the lingua detector in case language_models config changed
        self._lingua_detector = self._build_lingua_detector()
        
        logger.info("Configuration successfully reloaded")

    def _build_lingua_detector(self):
        """Build a lingua detector only for languages with a configured voice model."""
        configured_langs = [
            _LINGUA_LANGUAGES[code]
            for code, model in self.config.voice.language_models.items()
            if model and code in _LINGUA_LANGUAGES
        ]
        default_lang = getattr(self.config.voice, "language", "en")
        if default_lang in _LINGUA_LANGUAGES and _LINGUA_LANGUAGES[default_lang] not in configured_langs:
            configured_langs.append(_LINGUA_LANGUAGES[default_lang])
        if len(configured_langs) < 2:
            # Ensure at least English + Italian (or all supported if neither) so detection works
            for fallback_code in ("en", "it"):
                if fallback_code in _LINGUA_LANGUAGES and _LINGUA_LANGUAGES[fallback_code] not in configured_langs:
                    configured_langs.append(_LINGUA_LANGUAGES[fallback_code])
        return LanguageDetectorBuilder.from_languages(*configured_langs).build()

    def _detect_language(self, text: str) -> Optional[str]:
        """Detect language of the whole text. Returns None if text is too short."""
        if len(text.strip()) < 10:
            return None
        try:
            lang = self._lingua_detector.detect_language_of(text)
            if lang is not None:
                code = lang.iso_code_639_1.name.lower()
                logger.debug(f"Detected language '{code}'")
                return code
        except Exception as e:
            logger.warning(f"Language detection failed: {e}")
        return None

    def _on_text_selected(self, text: str, play_feedback: bool = True) -> None:
        """
        Callback when user triggers playback (hotkey press or force-replay).

        Args:
            text: Selected text to read
            play_feedback: Whether to play start feedback tone
        """
        logger.debug(f"Text selected: {text[:50]}...")

        # Stop any existing processing
        self._stop_event.set()
        self.audio_player.stop()

        if (
            self._process_thread
            and self._process_thread.is_alive()
            and self._process_thread is not threading.current_thread()
        ):
            self._process_thread.join(timeout=0.2)

        self._stop_event = threading.Event()
        if play_feedback and getattr(self.config.audio, "sound_feedback", True):
            SoundFeedback.play_start()
        self._process_thread = threading.Thread(
            target=self.process_text,
            args=(text, self._stop_event),
            daemon=True,
        )
        self._process_thread.start()

    def _on_shortcut_pressed(self) -> None:
        """Callback when keyboard shortcut is pressed"""
        now = time.monotonic()
        if now - self._last_shortcut_time < 0.35:
            logger.debug("Ignoring duplicate shortcut trigger (debounced)")
            return
        self._last_shortcut_time = now

        logger.info("Shortcut pressed, delegating to background thread...")
        threading.Thread(target=self._process_shortcut, daemon=True).start()

    def _process_shortcut(self) -> None:
        """Process the shortcut press in a background thread"""
        with self._shortcut_lock:
            is_playing = self.audio_player.is_playing or (self._process_thread and self._process_thread.is_alive())

            current_selection = self.selection_listener.get_primary_selection()
            current_text = current_selection.strip() if current_selection else ""

            # If currently playing and the selection hasn't changed, do nothing
            if is_playing and current_text == self.selection_listener.last_selection:
                logger.info("Playing and selection unchanged. Ignoring trigger (use stop shortcut to stop).")
                return

            # Stop current playback if needed
            if is_playing:
                logger.info("Stopping current playback for new selection...")
                self._stop_event.set()
                self.audio_player.stop()
                if self._process_thread and self._process_thread.is_alive():
                    self._process_thread.join(timeout=0.5)

            if current_text:
                # Reuse the already-fetched text — no second subprocess call needed
                self.selection_listener.last_selection = current_text
                self._on_text_selected(current_text, play_feedback=True)
            elif not is_playing:
                logger.debug("No text currently selected in clipboard/primary")

    def _on_pause_pressed(self) -> None:
        """Callback when pause shortcut is pressed"""
        if self.audio_player.is_playing:
            if self.audio_player.is_paused:
                logger.info("Resuming playback...")
                self.audio_player.resume()
            else:
                logger.info("Pausing playback...")
                self.audio_player.pause()

    def _on_stop_pressed(self) -> None:
        """Callback when stop shortcut is pressed"""
        now = time.monotonic()
        if now - self._last_stop_time < 0.25:
            return
        self._last_stop_time = now

        if self.audio_player.is_playing or (self._process_thread and self._process_thread.is_alive()):
            logger.info("Explicit stop requested...")
            self._stop_event.set()
            self.audio_player.stop()
            # Clear last_selection so subsequent text selections aren't treated as identical
            # if user re-selects or clears selection.
            self.selection_listener.last_selection = ""

    def _on_ocr_pressed(self) -> None:
        """Callback when OCR screen capture shortcut is pressed"""
        if self._ocr_thread and self._ocr_thread.is_alive():
            logger.info("OCR screen capture already in progress, ignoring extra shortcut press.")
            return

        logger.info("OCR screen capture shortcut triggered...")
        if getattr(self.config.audio, "sound_feedback", True):
            SoundFeedback.play_ocr_start()

        def _capture_and_read():
            try:
                out_path = Path("/tmp/select_to_speech_ocr.png")
                success = ScreenCapture.capture_region(out_path)
                if success:
                    text = self.ocr_engine.extract_text(
                        out_path, languages=getattr(self.config, "ocr", None) and self.config.ocr.language
                    )
                    if text and text.strip():
                        logger.info(f"OCR extracted text ({len(text)} chars), starting playback...")
                        if getattr(self.config.audio, "sound_feedback", True):
                            SoundFeedback.play_ocr_success()
                        self._on_text_selected(text, play_feedback=False)
                    else:
                        logger.warning("No text extracted from screen capture")
                        if getattr(self.config.audio, "sound_feedback", True):
                            SoundFeedback.play_error()
                else:
                    if getattr(self.config.audio, "sound_feedback", True):
                        SoundFeedback.play_error()
            except Exception as e:
                logger.error(f"Error during OCR capture/read: {e}", exc_info=True)
                if getattr(self.config.audio, "sound_feedback", True):
                    SoundFeedback.play_error()

        self._ocr_thread = threading.Thread(target=_capture_and_read, daemon=True)
        self._ocr_thread.start()


    def _run_synthesis(
        self,
        text: str,
        segments: list,
        language: str,
        audio_queue: queue.Queue,
        stop_event: threading.Event,
        error_holder: list,
    ) -> None:
        """
        Thread target: synthesize all segments into audio_queue, then put None (EOF).

        Args:
            text: Original full text (unused here, kept for logging context)
            segments: List of (segment_text, voice_lang, phoneme_lang) tuples
            language: Dominant language code (used for fallback retry)
            audio_queue: Queue to put audio chunks into
            stop_event: Event signalling synthesis should stop
            error_holder: Single-element list; error_holder[0] is set on exception
        """
        def _enqueue(chunk_data: bytes) -> bool:
            while not stop_event.is_set():
                try:
                    audio_queue.put(chunk_data, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        try:
            for seg_text, seg_lang, seg_phoneme_lang in segments:
                if stop_event.is_set():
                    break
                produced = False
                for chunk_data in self.tts_engine.synthesize_stream(
                    seg_text,
                    language=seg_lang,
                    speed=self.config.audio.speed,
                    volume=self.config.audio.volume,
                    phoneme_lang=seg_phoneme_lang,
                    stop_event=stop_event,
                ):
                    produced = True
                    if not _enqueue(chunk_data):
                        return
                # If synthesis failed, retry without the phoneme override
                if not produced and seg_phoneme_lang is not None:
                    logger.warning(
                        f"Synthesis failed with phoneme_lang='{seg_phoneme_lang}', retrying without override"
                    )
                    for chunk_data in self.tts_engine.synthesize_stream(
                        seg_text,
                        language=language,
                        speed=self.config.audio.speed,
                        volume=self.config.audio.volume,
                        stop_event=stop_event,
                    ):
                        if not _enqueue(chunk_data):
                            return
        except Exception as e:
            logger.error(f"Stream generation error: {e}", exc_info=True)
            error_holder[0] = e
        finally:
            audio_queue.put(None)  # EOF — always emitted

    def _prepare_synthesis(self, text: str, stop_event: threading.Event):
        """
        Detect language and segment text. Returns (language, segments) or None if stopped.
        """
        detected = self._detect_language(text)
        if detected and self.config.voice.language_models.get(detected):
            language = detected
            logger.info(f"Detected language: {language}")
        else:
            if detected:
                logger.warning(
                    f"No voice configured for detected language '{detected}', using default."
                )
            language = self.config.voice.language
            logger.debug(f"Using default language: {language}")

        if stop_event.is_set():
            return None

        # 1. Apply heuristic text normalization (unwrap lines, de-hyphenate, list pauses)
        if getattr(self.config, "text_normalization", True):
            from .text_normalizer import normalize_text_for_tts
            text = normalize_text_for_tts(text)

        # 2. Apply neural punctuation restoration if enabled (CT-Transformer for EN/ZH)
        if getattr(self.config, "neural_punctuation", False) and hasattr(self, "punctuation_engine"):
            text = self.punctuation_engine.add_punctuation(text, language=language)

        # 3. Preprocess text to expand math symbols, emojis, and domain/filename dots
        text = self.tts_engine.preprocess_text(text, language)

        segments = [(text, language, None)]
        return language, segments

    def process_text(self, text: str, stop_event: threading.Event) -> bool:
        """
        Process text through TTS and play audio.

        Args:
            text: Text to process
            stop_event: Event to signal interruption

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Processing text: {len(text)} characters")

        if stop_event.is_set():
            return False

        result = self._prepare_synthesis(text, stop_event)
        if result is None:
            return False
        language, segments = result

        audio_queue = queue.Queue(maxsize=10)
        error_holder: list = [None]

        threading.Thread(
            target=self._run_synthesis,
            args=(text, segments, language, audio_queue, stop_event, error_holder),
            daemon=True,
        ).start()

        success = self.audio_player.play_stream(audio_queue, pitch=self.config.audio.pitch)

        if error_holder[0] is not None:
            logger.error(f"TTS generation failed: {error_holder[0]}")
            if getattr(self.config.audio, "sound_feedback", True) and not stop_event.is_set():
                SoundFeedback.play_error()
            return False

        if stop_event.is_set():
            logger.info("Playback stopped by user")
            return False

        if not success:
            logger.error("Stream playback failed")
            if getattr(self.config.audio, "sound_feedback", True) and not stop_event.is_set():
                SoundFeedback.play_error()
            return False

        logger.info("Successfully read text")
        return True

    def run(self) -> None:
        """Run the application"""
        try:
            logger.info("Starting Select-to-Speech application")

            # Start listeners
            self.selection_listener.start()
            self.keyboard_handler.start()

            logger.info("Application running. Press Alt+Esc to read selected text")
            logger.info("Press Ctrl+C to exit")

            # Keep the application running
            while not self.should_exit:
                signal.pause()

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Application error: {e}", exc_info=True)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Shutdown the application gracefully"""
        logger.info("Shutting down...")

        try:
            self.keyboard_handler.stop()
            self.selection_listener.stop()
            self.audio_player.stop()
            self.tts_engine.stop()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        logger.info("Application stopped")


def main() -> int:
    """Main entry point for the application (supports multi-call binary dispatch)."""
    prog_name = Path(sys.argv[0]).name if sys.argv else "select-to-speech"

    # Multi-call symlink dispatch or explicit subcommand flags
    if prog_name == "select-to-speech-check" or "--check" in sys.argv:
        if "--check" in sys.argv:
            sys.argv.remove("--check")
        from select_to_speech.system_check import main_check
        return main_check()

    if prog_name == "select-to-speech-audio" or "--audio-devices" in sys.argv:
        if "--audio-devices" in sys.argv:
            sys.argv.remove("--audio-devices")
        from select_to_speech.system_check import main_audio_devices
        return main_audio_devices()

    if prog_name == "select-to-speech-download" or "--download" in sys.argv:
        if "--download" in sys.argv:
            sys.argv.remove("--download")
        from select_to_speech.voice_manager import download_kokoro_cli
        download_kokoro_cli()
        return 0

    if len(sys.argv) > 1 and any(arg in sys.argv for arg in ("-h", "--help")):
        print("Select-to-Speech daemon & backend server")
        print("Usage: select-to-speech [options]")
        print("\nOptions:")
        print("  -h, --help         Show this help message and exit")
        print("  --check            Run system dependency check")
        print("  --audio-devices    List available audio output devices")
        print("  --download         Download Kokoro TTS model files")
        return 0

    from select_to_speech.api.server import run_server
    try:
        res = run_server()
        return res if isinstance(res, int) else 0
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
