"""Wayland primary selection listener for text capture"""

import logging
import subprocess
import threading
from typing import Optional, Callable


logger = logging.getLogger(__name__)


class WaylandSelectionListener:
    """Listens for primary selection changes in Wayland"""

    def __init__(self, on_selection_change: Callable[[str], None]):
        """
        Initialize the Wayland selection listener.

        Args:
            on_selection_change: Callback function called with selected text
        """
        self.on_selection_change = on_selection_change
        self.last_selection = ""
        self.is_running = False

    def get_primary_selection(self) -> Optional[str]:
        """
        Get the current primary selection from Wayland clipboard.

        Uses wl-paste to retrieve the primary selection without modifying it.

        Returns:
            Selected text or None if unavailable
        """
        try:
            # wl-paste with --primary gets the primary selection (not clipboard)
            result = subprocess.run(
                ["wl-paste", "--primary"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if result.returncode == 0:
                return result.stdout
        except FileNotFoundError:
            logger.error(
                "wl-paste not found. This is required for Wayland clipboard access.\n"
                "Install wl-clipboard on CachyOS/Arch: sudo pacman -S wl-clipboard\n"
                "Or run: python -m select_to_speech.system_check"
            )
        except subprocess.TimeoutExpired:
            logger.debug("Timeout retrieving primary selection")
        except Exception as e:
            logger.debug(f"Error retrieving selection: {e}")

        return None

    def on_trigger(self, force: bool = False) -> None:
        """
        Called when keyboard shortcut is triggered.

        Retrieves the current primary selection and passes it to the callback in a background thread.
        
        Args:
            force: If True, triggers the callback even if the selection hasn't changed.
        """
        threading.Thread(
            target=self._process_trigger, 
            args=(force,), 
            daemon=True
        ).start()

    def _process_trigger(self, force: bool) -> None:
        """Actually retrieves and dispatches the selection."""
        selection = self.get_primary_selection()

        if selection:
            # Only process if selection is not empty
            text = selection.strip()
            if text and (text != self.last_selection or force):
                logger.debug(f"Selection captured: {len(text)} chars (force={force})")
                self.on_selection_change(text)
                self.last_selection = text
            elif text == self.last_selection:
                logger.debug("Selection unchanged, skipping")
            else:
                logger.warning("No text selected or clipboard is empty.")
        else:
            logger.warning("No text selected or clipboard is empty.")

    def start(self) -> None:
        """Start the selection listener"""
        self.is_running = True
        logger.info("Selection listener started")

    def stop(self) -> None:
        """Stop the selection listener"""
        self.is_running = False
        logger.info("Selection listener stopped")
