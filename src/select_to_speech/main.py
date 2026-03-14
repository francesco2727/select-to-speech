"""Main application entry point"""

import logging
import os
import signal
import sys
import threading
import queue
from pathlib import Path
from typing import Optional

from langdetect import detect, DetectorFactory

from .config import load_config, AppConfig
from .keyboard_handler import KeyboardHandler
from .selection_listener import WaylandSelectionListener
from .tts_engine import get_tts_engine
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
        self.tts_engine = get_tts_engine(self.config.voice)
        self.audio_player = AudioPlayer(self.config.audio.device_id)
        self.selection_listener = WaylandSelectionListener(
            on_selection_change=self._on_text_selected
        )
        self.keyboard_handler = KeyboardHandler(
            on_play=self._on_shortcut_pressed,
            on_pause=self._on_pause_pressed,
            on_stop=self._on_stop_pressed,
            modifier=self.config.keyboard.modifier_key,
            trigger_key=self.config.keyboard.trigger_key,
            pause_key=self.config.keyboard.pause_key,
            stop_key=self.config.keyboard.stop_key,
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
        
        is_playing = self.audio_player.is_playing or (self._process_thread and self._process_thread.is_alive())
        
        current_selection = self.selection_listener.get_primary_selection()
        current_text = current_selection.strip() if current_selection else ""
        
        # If currently playing and the selection hasn't changed, do nothing
        if is_playing and current_text == self.selection_listener.last_selection:
            logger.info("Playing and selection unchanged. Ignoring trigger (use stop shortcut to stop).")
            return

        # If currently playing and we have new text selected, stop old playback
        if is_playing:
            logger.info("Stopping current playback for new selection...")
            self._stop_event.set()
            self.audio_player.stop()
            
            # Wait briefly for thread to stop
            if self._process_thread and self._process_thread.is_alive():
                self._process_thread.join(timeout=0.5)

        # Get current selection (this will trigger _on_text_selected if there's text)
        self.selection_listener.on_trigger(force=not is_playing)

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
            
            # Check if language is supported and has a voice configured
            if language not in self.config.voice.language_models:
                logger.warning(f"Language '{language}' not in language_models, falling back to default.")
                language = self.config.voice.language
            elif not self.config.voice.language_models.get(language):
                logger.warning(f"No voice configured for '{language}', falling back to default.")
                language = self.config.voice.language
                
        except Exception as e:
            logger.warning(f"Language detection failed: {e}")

        if stop_event.is_set():
            return False
            
        audio_queue = queue.Queue(maxsize=10)
        
        # Background worker generating TTS chunks
        def generator():
            try:
                for chunk_data in self.tts_engine.synthesize_stream(
                    text, 
                    language=language,
                    speed=self.config.audio.speed,
                    volume=self.config.audio.volume
                ):
                    if stop_event.is_set():
                        break
                    
                    # Instead of blocking indefinitely, we use loop with timeout 
                    # so we can check the stop_event frequently while waiting to enqueue
                    while not stop_event.is_set():
                        try:
                            audio_queue.put(chunk_data, timeout=0.1)
                            break
                        except queue.Full:
                            continue
            except Exception as e:
                logger.error(f"Stream generation error: {e}")
            finally:
                audio_queue.put(None)  # EOF

        threading.Thread(target=generator, daemon=True).start()

        # Play audio stream
        success = self.audio_player.play_stream(audio_queue, pitch=self.config.audio.pitch)

        if stop_event.is_set():
            logger.info("Playback stopped by user")
            return False

        if not success:
            logger.error("Stream playback failed")
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
