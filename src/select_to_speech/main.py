"""Main application entry point"""

import logging
import os
import signal
import sys
import threading
import queue
from pathlib import Path
from typing import Optional

from lingua import Language, LanguageDetectorBuilder

from .config import load_config, AppConfig
from .keyboard_handler import KeyboardHandler
from .ollama_client import (
    PROMPT_DESCRIBE_SCREEN,
    PROMPT_READ_SCREEN,
    generate_with_image,
)
from .screenshot import capture_fullscreen
from .selection_listener import WaylandSelectionListener
from .tts_engine import get_tts_engine
from .audio_player import AudioPlayer


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
        self._lingua_detector = self._build_lingua_detector()
        self.selection_listener = WaylandSelectionListener(
            on_selection_change=self._on_text_selected,
        )
        extra_hotkeys = self._build_ollama_hotkeys()
        self.keyboard_handler = KeyboardHandler(
            on_play=self._on_shortcut_pressed,
            on_pause=self._on_pause_pressed,
            on_stop=self._on_stop_pressed,
            modifier=self.config.keyboard.modifier_key,
            trigger_key=self.config.keyboard.trigger_key,
            pause_key=self.config.keyboard.pause_key,
            stop_key=self.config.keyboard.stop_key,
            extra_hotkeys=extra_hotkeys,
        )

        self.should_exit = False
        self._process_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _setup_logging(self) -> None:
        """Setup logging configuration"""
        level = logging.DEBUG if self.config.debug else logging.INFO
        
        # Setup file logging
        log_dir = Path.home() / ".local" / "state" / "select-to-speech"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
        
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def _signal_handler(self, signum, frame) -> None:
        """Handle system signals for graceful shutdown"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.should_exit = True

    def _build_lingua_detector(self):
        """Build a lingua detector for all configured languages."""
        configured_langs = [
            _LINGUA_LANGUAGES[code]
            for code in self.config.voice.language_models
            if code in _LINGUA_LANGUAGES
        ]
        if not configured_langs:
            configured_langs = list(_LINGUA_LANGUAGES.values())
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

    def _segment_by_language(self, text: str, dominant_lang: str) -> list[tuple[str, str]]:
        """
        Split text into (segment, lang_code) pairs using per-span language detection.
        Segments whose detected language has no configured voice fall back to dominant_lang.
        """
        try:
            results = self._lingua_detector.detect_multiple_languages_of(text)
        except Exception as e:
            logger.warning(f"Multi-language segmentation failed: {e}")
            return [(text, dominant_lang)]

        if not results:
            return [(text, dominant_lang)]

        segments: list[tuple[str, str]] = []
        for result in results:
            segment_text = text[result.start_index:result.end_index]
            if not segment_text.strip():
                continue
            lang_code = result.language.iso_code_639_1.name.lower()
            # Fall back to dominant if no voice is configured for this language
            if not self.config.voice.language_models.get(lang_code):
                lang_code = dominant_lang
            segments.append((segment_text, lang_code))

        if not segments:
            return [(text, dominant_lang)]

        # Merge consecutive segments with the same language
        merged: list[tuple[str, str]] = [segments[0]]
        for seg_text, seg_lang in segments[1:]:
            if seg_lang == merged[-1][1]:
                merged[-1] = (merged[-1][0] + seg_text, seg_lang)
            else:
                merged.append((seg_text, seg_lang))

        if len(merged) > 1:
            langs = ", ".join(f"'{l}'" for _, l in merged)
            logger.debug(f"Mixed-language text split into {len(merged)} segments: {langs}")

        return merged

    def _build_ollama_hotkeys(self) -> dict:
        """Build extra hotkey mappings for the Ollama screen reader features."""
        ollama = self.config.ollama
        hotkeys = {}
        if ollama.read_screen_key:
            hk = KeyboardHandler.format_hotkey(ollama.read_screen_modifier, ollama.read_screen_key)
            hotkeys[hk] = self._on_read_screen_pressed
        if ollama.describe_screen_key:
            hk = KeyboardHandler.format_hotkey(ollama.describe_screen_modifier, ollama.describe_screen_key)
            hotkeys[hk] = self._on_describe_screen_pressed
        return hotkeys

    def _ollama_screen_pipeline(self, prompt: str, feature_name: str) -> None:
        """Common pipeline: screenshot -> Ollama vision -> TTS."""
        logger.info("%s: capturing screen...", feature_name)
        image_bytes = capture_fullscreen()
        if not image_bytes:
            logger.error("%s: screenshot capture failed", feature_name)
            return

        ollama = self.config.ollama
        model = (
            ollama.read_screen_model
            if "read" in feature_name.lower()
            else ollama.describe_screen_model
        )
        logger.info("%s: sending to Ollama model '%s'...", feature_name, model)
        text = generate_with_image(
            ollama.server_url, model, prompt, image_bytes,
        )
        if not text or not text.strip():
            logger.warning("%s: Ollama returned empty response", feature_name)
            return

        logger.info("%s: got %d chars, sending to TTS", feature_name, len(text))
        self._on_text_selected(text.strip())

    def _on_read_screen_pressed(self) -> None:
        """Callback: screenshot -> Ollama text extraction -> TTS."""
        logger.info("Read Screen shortcut pressed")
        self._stop_event.set()
        self.audio_player.stop()
        if self._process_thread and self._process_thread.is_alive():
            self._process_thread.join(timeout=0.2)

        self._stop_event = threading.Event()
        self._process_thread = threading.Thread(
            target=self._ollama_screen_pipeline,
            args=(PROMPT_READ_SCREEN, "Read Screen"),
            daemon=True,
        )
        self._process_thread.start()

    def _on_describe_screen_pressed(self) -> None:
        """Callback: screenshot -> Ollama screen description -> TTS."""
        logger.info("Describe Screen shortcut pressed")
        self._stop_event.set()
        self.audio_player.stop()
        if self._process_thread and self._process_thread.is_alive():
            self._process_thread.join(timeout=0.2)

        self._stop_event = threading.Event()
        self._process_thread = threading.Thread(
            target=self._ollama_screen_pipeline,
            args=(PROMPT_DESCRIBE_SCREEN, "Describe Screen"),
            daemon=True,
        )
        self._process_thread.start()

    def _on_text_selected(self, text: str) -> None:
        """
        Callback when user triggers playback (hotkey press or force-replay).

        Args:
            text: Selected text to read
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
        self._process_thread = threading.Thread(
            target=self.process_text,
            args=(text, self._stop_event),
            daemon=True,
        )
        self._process_thread.start()

    def _on_shortcut_pressed(self) -> None:
        """Callback when keyboard shortcut is pressed"""
        logger.info("Shortcut pressed, processing selection...")

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
                self._process_thread.join(timeout=0.2)

        if current_text:
            # Reuse the already-fetched text — no second subprocess call needed
            self.selection_listener.last_selection = current_text
            self._on_text_selected(current_text)
        elif not is_playing:
            # Nothing selected and not playing: force re-read of last selection
            self.selection_listener.on_trigger(force=True)

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
        if self.audio_player.is_playing or (self._process_thread and self._process_thread.is_alive()):
            logger.info("Explicit stop requested...")
            self._stop_event.set()
            self.audio_player.stop()

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
            segments: List of (segment_text, lang_code) pairs
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
            for seg_text, seg_lang in segments:
                if stop_event.is_set():
                    break
                produced = False
                for chunk_data in self.tts_engine.synthesize_stream(
                    seg_text,
                    language=seg_lang,
                    speed=self.config.audio.speed,
                    volume=self.config.audio.volume,
                ):
                    produced = True
                    if not _enqueue(chunk_data):
                        return
                # If synthesis failed (no chunks) and we used a non-dominant language,
                # retry with the dominant language (e.g. espeak data not installed)
                if not produced and seg_lang != language:
                    logger.warning(
                        f"Synthesis failed for language '{seg_lang}', retrying with '{language}'"
                    )
                    for chunk_data in self.tts_engine.synthesize_stream(
                        seg_text,
                        language=language,
                        speed=self.config.audio.speed,
                        volume=self.config.audio.volume,
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

        segments = self._segment_by_language(text, language)
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
            return False

        if stop_event.is_set():
            logger.info("Playback stopped by user")
            return False

        if not success:
            logger.error("Stream playback failed")
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
    """Main entry point for the application"""
    try:
        app = SelectToSpeechApp()
        app.run()
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
