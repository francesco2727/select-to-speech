"""Keyboard shortcut handler for Alt+Esc trigger"""

import logging
from typing import Callable, Optional

from pynput import keyboard


logger = logging.getLogger(__name__)


class KeyboardHandler:
    """Handles keyboard shortcuts and triggers callbacks"""

    def __init__(
        self,
        on_shortcut: Callable[[], None],
        modifier: str = "alt",
        trigger_key: str = "esc",
    ):
        """
        Initialize keyboard handler.

        Args:
            on_shortcut: Callback function when shortcut is triggered
            modifier: Modifier key ('alt', 'ctrl', 'shift')
            trigger_key: Trigger key name (e.g., 'esc', 'f1')
        """
        self.on_shortcut = on_shortcut
        self.modifier = modifier.lower()
        self.trigger_key = trigger_key.lower()
        self.listener: Optional[keyboard.Listener] = None
        self.keys_pressed = set()

        # Map modifier names to pynput Key enum
        self.modifier_map = {
            "alt": keyboard.Key.alt,
            "ctrl": keyboard.Key.ctrl,
            "control": keyboard.Key.ctrl,
            "shift": keyboard.Key.shift,
        }

        # Map trigger key names to pynput Key enum
        self.trigger_key_map = {
            "esc": keyboard.Key.esc,
            "escape": keyboard.Key.esc,
            "f1": keyboard.Key.f1,
            "f2": keyboard.Key.f2,
            "f3": keyboard.Key.f3,
            "f4": keyboard.Key.f4,
            "f5": keyboard.Key.f5,
            "f6": keyboard.Key.f6,
            "f7": keyboard.Key.f7,
            "f8": keyboard.Key.f8,
            "f9": keyboard.Key.f9,
            "f10": keyboard.Key.f10,
            "f11": keyboard.Key.f11,
            "f12": keyboard.Key.f12,
        }

    def _on_press(self, key: Optional[keyboard.Key]) -> None:
        """Handle key press event"""
        try:
            if key in self.modifier_map.values():
                self.keys_pressed.add(key)
            elif key == self.trigger_key_map.get(self.trigger_key):
                # Check if modifier is pressed
                if self.modifier_map.get(self.modifier) in self.keys_pressed:
                    logger.debug(f"Shortcut triggered: {self.modifier}+{self.trigger_key}")
                    self.on_shortcut()
        except AttributeError:
            # Ignore special key handling for character keys
            pass

    def _on_release(self, key: Optional[keyboard.Key]) -> None:
        """Handle key release event"""
        try:
            if key in self.modifier_map.values():
                self.keys_pressed.discard(key)
        except AttributeError:
            pass

    def start(self) -> None:
        """Start listening for keyboard shortcuts"""
        if self.listener is not None:
            logger.warning("Keyboard listener already running")
            return

        self.listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self.listener.start()
        logger.info(
            f"Keyboard listener started: {self.modifier.upper()}+{self.trigger_key.upper()}"
        )

    def stop(self) -> None:
        """Stop listening for keyboard shortcuts"""
        if self.listener is None:
            logger.warning("Keyboard listener not running")
            return

        self.listener.stop()
        self.listener = None
        logger.info("Keyboard listener stopped")
