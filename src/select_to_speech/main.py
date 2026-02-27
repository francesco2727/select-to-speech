"""Main application entry point"""

import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

from langdetect import detect, DetectorFactory

from .config import load_config, AppConfig
from .keyboard_handler import KeyboardHandler
from .selection_listener import WaylandSelectionListener
from .tts_engine import TTSEngine
from .audio_player import AudioPlayer


# Ensure deterministic language detection results
DetectorFactory.seed = 0

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
        self.tts_engine = TTSEngine(self.config.voice)
        self.audio_player = AudioPlayer(self.config.audio.device_id)
        self.selection_listener = WaylandSelectionListener(
            on_selection_change=self._on_text_selected
        )
        self.keyboard_handler = KeyboardHandler(
            on_shortcut=self._on_shortcut_pressed,
            modifier=self.config.keyboard.modifier_key,
            trigger_key=self.config.keyboard.trigger_key,
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

    def _on_text_selected(self, text: str) -> None:
        """
        Callback when text is selected.

        Args:
            text: Selected text to read
        """
        logger.debug(f"Text selected: {text[:50]}...")
        
        # Stop any existing processing
        self._stop_event.set()
        self.audio_player.stop()
        
        if self._process_thread and self._process_thread.is_alive():
            self._process_thread.join(timeout=1.0)
            
        # Start new processing thread
        self._stop_event.clear()
        self._process_thread = threading.Thread(
            target=self.process_text,
            args=(text, self._stop_event),
            daemon=True
        )
        self._process_thread.start()

    def _on_shortcut_pressed(self) -> None:
        """Callback when keyboard shortcut is pressed"""
        logger.info("Shortcut pressed, processing selection...")

        # If currently playing or processing, stop it
        was_playing = False
        if self.audio_player.is_playing or (self._process_thread and self._process_thread.is_alive()):
            was_playing = True
            logger.info("Stopping current playback...")
            self._stop_event.set()
            self.audio_player.stop()
            
            # Wait briefly for thread to stop
            if self._process_thread and self._process_thread.is_alive():
                self._process_thread.join(timeout=0.5)
                
            # If we just stopped playback, we don't want to immediately restart
            # unless the user has selected new text.
            # We check if the selection has changed. If it hasn't, we just return
            # (which completes the "stop" action).
            current_selection = self.selection_listener.get_primary_selection()
            if current_selection:
                current_text = current_selection.strip()
                if current_text == self.selection_listener.last_selection:
                    logger.info("Selection unchanged, stopping only.")
                    return

        # Get current selection (this will trigger _on_text_selected if there's text)
        # If we weren't playing, we force the trigger even if the selection hasn't changed
        # so the user can replay the same text.
        self.selection_listener.on_trigger(force=not was_playing)

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

        # Detect language
        language = None
        try:
            language = detect(text)
            logger.info(f"Detected language: {language}")
            
            # Check if language is supported
            if language not in self.config.voice.language_models:
                logger.warning(f"Language '{language}' not supported. Switching to English.")
                text = "Sorry, this language is not supported"
                language = "en"
                
        except Exception as e:
            logger.warning(f"Language detection failed: {e}")

        # Synthesize text
        if stop_event.is_set():
            return False
            
        result = self.tts_engine.synthesize(
            text, 
            language=language,
            speed=self.config.audio.speed,
            volume=self.config.audio.volume
        )
        if not result:
            logger.error("Synthesis failed - TTS returned None")
            return False

        if stop_event.is_set():
            return False

        audio_data, sample_rate = result
        logger.debug(f"Received from TTS: {len(audio_data) if audio_data else 0} bytes, {sample_rate}Hz")

        # Play audio
        if stop_event.is_set():
            return False
            
        if not self.audio_player.play(audio_data, sample_rate, pitch=self.config.audio.pitch):
            logger.error(f"Playback failed - audio_data was {'empty' if not audio_data else f'{len(audio_data)} bytes'}")
            return False

        if stop_event.is_set():
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
