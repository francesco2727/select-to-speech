"""Keyboard shortcut handler using pynput GlobalHotKeys"""

import logging
from typing import Any, Callable, Optional

try:
    from pynput import keyboard
except Exception:  # Headless environments without X11/Wayland (e.g. CI runners)
    keyboard = None


logger = logging.getLogger(__name__)


class KeyboardHandler:
    """Handles keyboard shortcuts using GlobalHotKeys"""

    def __init__(
        self,
        on_play: Callable[[], None],
        on_pause: Callable[[], None] = None,
        on_stop: Callable[[], None] = None,
        on_ocr: Callable[[], None] = None,
        modifier: str = "alt",
        trigger_key: str = "esc",
        pause_key: str = "w",
        stop_key: str = "s",
        ocr_key: str = "r",
        extra_hotkeys: Optional[dict[str, Callable[[], None]]] = None,
    ):
        """
        Initialize keyboard handler.

        Args:
            on_play: Callback function when play shortcut is triggered
            on_pause: Callback function when pause shortcut is triggered
            on_stop: Callback function when stop shortcut is triggered
            on_ocr: Callback function when OCR screen capture shortcut is triggered
            modifier: Modifier key ('alt', 'ctrl', 'shift')
            trigger_key: Trigger key name for play (e.g., 'esc', 'f1')
            pause_key: Trigger key name for pause/resume
            stop_key: Trigger key name for explicit stop
            ocr_key: Trigger key name for OCR screen capture
            extra_hotkeys: Additional pre-formatted hotkey->callback mappings
        """
        self.listener: Any = None

        play_hotkey = self.format_hotkey(modifier, trigger_key)
        self.hotkeys = {
            play_hotkey: on_play,
        }

        if on_pause:
            pause_hotkey = self.format_hotkey(modifier, pause_key)
            self.hotkeys[pause_hotkey] = on_pause

        if on_stop:
            stop_hotkey = self.format_hotkey(modifier, stop_key)
            self.hotkeys[stop_hotkey] = on_stop

        if on_ocr:
            ocr_hotkey = self.format_hotkey(modifier, ocr_key)
            self.hotkeys[ocr_hotkey] = on_ocr

        if extra_hotkeys:
            self.hotkeys.update(extra_hotkeys)

    @staticmethod
    def format_hotkey(modifier: str, key: str) -> str:
        """Converts config strings into pynput GlobalHotKey format.

        *modifier* may contain one or two modifiers joined by ``"+"``,
        e.g. ``"alt"`` or ``"alt+ctrl"``.
        """
        parts: list[str] = []
        if modifier:
            for m in modifier.split("+"):
                m = m.strip().lower()
                if m == "super":
                    m = "cmd"
                if m:
                    parts.append(f"<{m}>")

        key = key.lower()
        key_str = f"<{key}>" if len(key) > 1 else key
        parts.append(key_str)

        return "+".join(parts)

    def start(self) -> None:
        """Start listening for keyboard shortcuts"""
        if self.listener is not None:
            logger.warning("Keyboard listener already running")
            return

        if keyboard is None:
            logger.error("Cannot start keyboard listener: pynput keyboard backend is not available (no display server found)")
            return

        self.listener = keyboard.GlobalHotKeys(self.hotkeys)
        self.listener.start()
        logger.info(f"Keyboard listener started with hotkeys: {list(self.hotkeys.keys())}")

    def stop(self) -> None:
        """Stop listening for keyboard shortcuts"""
        if self.listener is None:
            logger.warning("Keyboard listener not running")
            return

        self.listener.stop()
        self.listener = None
        logger.info("Keyboard listener stopped")
