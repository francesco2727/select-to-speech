"""Selection listener module supporting Wayland/X11 (Linux) and Ctrl+C simulation (Windows)."""

import concurrent.futures
import ctypes
from ctypes import wintypes
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

from pynput.keyboard import Controller, Key

try:
    import pyperclip
except ImportError:
    pyperclip = None

logger = logging.getLogger(__name__)

# Win32 Clipboard Constants
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _get_clipboard_sequence_number() -> Optional[int]:
    """Get the current Windows clipboard sequence number."""
    if hasattr(ctypes, "windll"):
        try:
            return ctypes.windll.user32.GetClipboardSequenceNumber()
        except Exception:
            return None
    return None


def _get_clipboard_win32() -> Optional[str]:
    """Read text from the Windows clipboard using Win32 ctypes API."""
    if not hasattr(ctypes, "windll"):
        return None

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    opened = False
    for _ in range(5):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.01)

    if not opened:
        return None

    try:
        h_clip_mem = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_clip_mem:
            return None
        kernel32.GlobalLock.restype = ctypes.c_void_p
        p_clip_mem = kernel32.GlobalLock(h_clip_mem)
        if not p_clip_mem:
            return None
        try:
            return ctypes.wstring_at(p_clip_mem)
        finally:
            kernel32.GlobalUnlock(h_clip_mem)
    except Exception as e:
        logger.debug(f"Error reading Win32 clipboard via ctypes: {e}")
        return None
    finally:
        user32.CloseClipboard()


def _set_clipboard_win32(text: str) -> bool:
    """Write text to the Windows clipboard using Win32 ctypes API."""
    if not hasattr(ctypes, "windll"):
        return False

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    opened = False
    for _ in range(5):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.01)

    if not opened:
        return False

    try:
        user32.EmptyClipboard()
        if not text:
            return True

        data_bytes = (text + "\0").encode("utf-16-le")
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data_bytes))
        if not h_mem:
            return False

        kernel32.GlobalLock.restype = ctypes.c_void_p
        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            return False

        ctypes.memmove(p_mem, data_bytes, len(data_bytes))
        kernel32.GlobalUnlock(h_mem)
        h_res = user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        if not h_res:
            kernel32.GlobalFree(h_mem)
            return False
        return True
    except Exception as e:
        logger.debug(f"Error setting Win32 clipboard via ctypes: {e}")
        return False
    finally:
        user32.CloseClipboard()


class BaseSelectionListener:
    """Base class for platform-specific selection listeners."""

    def __init__(self, on_selection_change: Callable[[str], None]):
        """
        Initialize the selection listener base.

        Args:
            on_selection_change: Callback invoked when text selection is dispatched.
        """
        self.on_selection_change = on_selection_change
        self.last_selection = ""
        self.is_running = False
        self._lock = threading.Lock()

    def get_primary_selection(self) -> Optional[str]:
        """Return the currently selected text or None."""
        raise NotImplementedError

    def get_selected_text(self) -> Optional[str]:
        """Alias for get_primary_selection."""
        return self.get_primary_selection()

    def on_trigger(self, force: bool = False) -> None:
        """
        Called when keyboard shortcut is triggered.

        Retrieves the current selection and passes it to the callback in a background thread.
        """
        threading.Thread(
            target=self._process_trigger,
            args=(force,),
            daemon=True,
        ).start()

    def _process_trigger(self, force: bool) -> None:
        """Actually retrieves and dispatches the selection."""
        selection = self.get_primary_selection()

        if selection:
            text = selection.strip()
            with self._lock:
                last_sel = self.last_selection
                should_dispatch = bool(text and (text != last_sel or force))
                if should_dispatch:
                    self.last_selection = text

            if should_dispatch:
                logger.debug(f"Selection captured: {len(text)} chars (force={force})")
                self.on_selection_change(text)
            elif text == last_sel:
                logger.debug("Selection unchanged, skipping")
            else:
                logger.warning("No text selected or clipboard is empty.")
        else:
            logger.warning("No text selected or clipboard is empty.")

    def start(self) -> None:
        """Start the selection listener."""
        self.is_running = True
        logger.info(f"{self.__class__.__name__} started")

    def stop(self) -> None:
        """Stop the selection listener."""
        self.is_running = False
        logger.info(f"{self.__class__.__name__} stopped")


class WaylandSelectionListener(BaseSelectionListener):
    """Listens for primary selection changes in Wayland and XWayland apps.

    Native Wayland apps write to the Wayland primary selection (read via
    ``wl-paste --primary``).  Apps running under XWayland maintain a separate
    X11 PRIMARY selection buffer that ``wl-paste`` cannot see.  This class
    queries both sources and returns whichever one contains new text.

    For Chromium/CEF-based XWayland apps (e.g. ONLYOFFICE) that may not
    populate the X11 PRIMARY selection on text highlight, the X11 CLIPBOARD
    is checked as a last-resort fallback.
    """

    def __init__(
        self,
        on_selection_change: Callable[[str], None],
    ):
        super().__init__(on_selection_change=on_selection_change)
        self._xclip_available: Optional[bool] = None  # lazy-checked once
        self._last_clipboard = ""  # track clipboard to detect changes
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = (
            concurrent.futures.ThreadPoolExecutor(max_workers=2)
        )

    def _ensure_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Ensure the thread pool executor is initialized and running."""
        with self._lock:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
            return self._executor

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_xclip(self) -> bool:
        """Check (once) whether ``xclip`` is on PATH and cache the result."""
        if self._xclip_available is None:
            self._xclip_available = shutil.which("xclip") is not None
            if not self._xclip_available:
                logger.warning(
                    "xclip not found – text selection in XWayland apps will "
                    "not be captured. Install with: sudo pacman -S xclip"
                )
        return self._xclip_available

    def _get_wayland_primary(self) -> Optional[str]:
        """Return the Wayland primary selection via ``wl-paste``, or None."""
        try:
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
                "Install wl-clipboard on Arch Linux: sudo pacman -S wl-clipboard\n"
                "Or run: python -m select_to_speech.system_check"
            )
        except subprocess.TimeoutExpired:
            logger.debug("Timeout retrieving Wayland primary selection")
        except Exception as e:
            logger.debug(f"Error retrieving Wayland selection: {e}")
        return None

    def _get_wayland_clipboard(self) -> Optional[str]:
        """Return the Wayland clipboard selection via ``wl-paste``, or None."""
        try:
            result = subprocess.run(
                ["wl-paste"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if result.returncode == 0:
                return result.stdout
        except FileNotFoundError:
            # Already logged in _get_wayland_primary if wl-paste is missing
            pass
        except subprocess.TimeoutExpired:
            logger.debug("Timeout retrieving Wayland clipboard selection")
        except Exception as e:
            logger.debug(f"Error retrieving Wayland clipboard: {e}")
        return None

    def _run_xclip(self, selection: str) -> Optional[str]:
        """Run ``xclip -selection <selection> -o`` and return stdout, or None."""
        if not self._check_xclip():
            return None
        try:
            result = subprocess.run(
                ["xclip", "-selection", selection, "-o"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if result.returncode == 0:
                return result.stdout
        except subprocess.TimeoutExpired:
            logger.debug(f"Timeout retrieving X11 {selection} selection")
        except Exception as e:
            logger.debug(f"Error retrieving X11 {selection} selection: {e}")
        return None

    def _get_x11_primary(self) -> Optional[str]:
        """Return the X11 PRIMARY selection via ``xclip``, or None."""
        return self._run_xclip("primary")

    def _get_x11_clipboard(self) -> Optional[str]:
        """Return the X11 CLIPBOARD selection via ``xclip``, or None."""
        return self._run_xclip("clipboard")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_primary_selection(self) -> Optional[str]:
        """
        Get the current primary selection, checking Wayland and X11 sources concurrently.

        Priority order:
        1. Wayland PRIMARY (``wl-paste --primary``) – native Wayland apps.
        2. X11 PRIMARY (``xclip -selection primary``) – XWayland apps that
           set the traditional PRIMARY buffer on text highlight.
        3. Wayland CLIPBOARD (``wl-paste``) – native Wayland apps clipboard fallback.
        4. X11 CLIPBOARD (``xclip -selection clipboard``) – XWayland apps
           (e.g. ONLYOFFICE / Chromium-based) that only populate CLIPBOARD
           after the user copies (Ctrl+C).  Only used when the clipboard
           content has changed since the last read, to avoid stale data.

        Returns:
            Selected text or None if unavailable
        """
        try:
            executor = self._ensure_executor()
            future_wayland = executor.submit(self._get_wayland_primary)
            future_x11 = executor.submit(self._get_x11_primary)
        except RuntimeError as e:
            logger.debug(f"Selection listener executor shut down or unavailable: {e}")
            return None

        try:
            wayland_text = future_wayland.result(timeout=1.5)
        except (concurrent.futures.TimeoutError, Exception) as e:
            logger.debug(f"Error/timeout awaiting Wayland primary selection: {e}")
            wayland_text = None

        try:
            x11_text = future_x11.result(timeout=1.5)
        except (concurrent.futures.TimeoutError, Exception) as e:
            logger.debug(f"Error/timeout awaiting X11 primary selection: {e}")
            x11_text = None

        with self._lock:
            last_sel = self.last_selection
            last_clip = self._last_clipboard

        wayland_new = bool(wayland_text and wayland_text.strip() != last_sel)
        x11_new = bool(x11_text and x11_text.strip() != last_sel)

        if wayland_new:
            logger.debug("Using Wayland primary selection")
            return wayland_text
        if x11_new:
            logger.debug("Using X11 primary selection (XWayland fallback)")
            return x11_text

        # Fallback 1: Wayland CLIPBOARD — only if its content changed since our
        # last check (avoids returning stale Ctrl+C data).
        wayland_clip = self._get_wayland_clipboard()
        if wayland_clip:
            clip_stripped = wayland_clip.strip()
            if clip_stripped and clip_stripped != last_clip and clip_stripped != last_sel:
                logger.debug("Using Wayland clipboard selection (Wayland clipboard fallback)")
                with self._lock:
                    self._last_clipboard = clip_stripped
                return wayland_clip
            if clip_stripped:
                with self._lock:
                    self._last_clipboard = clip_stripped

        # Fallback 2: X11 CLIPBOARD — only if its content changed since our
        # last check (avoids returning stale Ctrl+C data).
        x11_clip = self._get_x11_clipboard()
        if x11_clip:
            clip_stripped = x11_clip.strip()
            if clip_stripped and clip_stripped != last_clip and clip_stripped != last_sel:
                logger.debug("Using X11 clipboard selection (XWayland clipboard fallback)")
                with self._lock:
                    self._last_clipboard = clip_stripped
                return x11_clip
            # Always track the latest clipboard so we detect future changes.
            if clip_stripped:
                with self._lock:
                    self._last_clipboard = clip_stripped

        # All stale – return whatever is available so force-triggered
        # playback still works.
        return wayland_text or x11_text

    def start(self) -> None:
        """Start the selection listener."""
        self._ensure_executor()
        super().start()

    def stop(self) -> None:
        """Stop the selection listener and release executor resources."""
        super().stop()
        with self._lock:
            if self._executor is not None:
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    self._executor.shutdown(wait=False)
                self._executor = None

    def __del__(self) -> None:
        """Clean up executor resources on disposal."""
        try:
            self.stop()
        except Exception:
            pass


class WindowsSelectionListener(BaseSelectionListener):
    """Selection listener for Windows using Ctrl+C simulation and clipboard management.

    Windows does not have an X11-style primary selection buffer that auto-populates on text drag.
    To capture highlighted text from the active application:
    1. The current clipboard text is saved.
    2. A synthetic `Ctrl+C` key sequence is dispatched using `pynput`.
    3. We wait a configurable debounce delay (e.g. 50-80ms) for the target app to handle the copy.
    4. The newly copied text is retrieved from the clipboard.
    5. The previous clipboard content is restored so user history is not corrupted.
    """

    def __init__(
        self,
        on_selection_change: Callable[[str], None],
        copy_delay: float = 0.06,
    ):
        """
        Initialize Windows selection listener.

        Args:
            on_selection_change: Callback called when selected text is captured.
            copy_delay: Seconds to wait after Ctrl+C simulation for the app to process copy.
        """
        super().__init__(on_selection_change=on_selection_change)
        self.copy_delay = copy_delay
        self._keyboard: Optional[Controller] = None

    def _get_keyboard(self) -> Controller:
        """Lazily initialize and return the keyboard controller."""
        if self._keyboard is None:
            self._keyboard = Controller()
        return self._keyboard

    def _get_clipboard_text(self) -> Optional[str]:
        """Read text from clipboard via pyperclip with ctypes fallback."""
        if pyperclip is not None:
            try:
                return pyperclip.paste()
            except Exception as e:
                logger.debug(f"pyperclip.paste() failed: {e}, attempting Win32 fallback")

        return _get_clipboard_win32()

    def _set_clipboard_text(self, text: str) -> bool:
        """Write text to clipboard via pyperclip with ctypes fallback."""
        if pyperclip is not None:
            try:
                pyperclip.copy(text)
                return True
            except Exception as e:
                logger.debug(f"pyperclip.copy() failed: {e}, attempting Win32 fallback")

        return _set_clipboard_win32(text)

    def _empty_clipboard(self) -> bool:
        """Empty the clipboard."""
        return self._set_clipboard_text("")

    def _simulate_ctrl_c(self) -> None:
        """Simulate Ctrl+C keystroke to copy selected text to clipboard.
        
        Also releases physical modifier keys (Alt, Shift, Windows) that might
        be held down when triggering global hotkeys (e.g. Alt+Esc).
        """
        try:
            kb = self._get_keyboard()
            # Release modifier keys that might interfere with Ctrl+C
            for mod_key in (Key.alt, Key.alt_l, Key.alt_r, Key.cmd, Key.shift, Key.shift_r):
                try:
                    kb.release(mod_key)
                except Exception:
                    pass

            time.sleep(0.01)
            kb.press(Key.ctrl)
            kb.press("c")
            kb.release("c")
            kb.release(Key.ctrl)
        except Exception as e:
            logger.error(f"Failed to simulate Ctrl+C: {e}", exc_info=True)

    def get_primary_selection(self) -> Optional[str]:
        """
        Capture selected text on Windows:
        1. Save original clipboard text.
        2. Query initial clipboard sequence number if available.
        3. Simulate Ctrl+C via pynput (releasing any interfering modifiers).
        4. Wait/poll for the active app to update the clipboard.
        5. Read newly copied clipboard text.
        6. Restore original clipboard content.
        7. Return captured selection.
        """
        with self._lock:
            original_clipboard = self._get_clipboard_text()
            initial_seq = _get_clipboard_sequence_number()

            # Empty clipboard only if sequence number is not supported
            if initial_seq is None:
                self._empty_clipboard()

            self._simulate_ctrl_c()

            # Wait / poll for clipboard to populate or sequence number to increment
            captured_text: Optional[str] = None
            start_time = time.time()
            max_wait = max(self.copy_delay + 0.15, 0.25)

            while time.time() - start_time < max_wait:
                time.sleep(0.02)
                current_seq = _get_clipboard_sequence_number()
                if initial_seq is not None:
                    if current_seq != initial_seq:
                        # Clipboard updated by target app!
                        text = self._get_clipboard_text()
                        if text and text.strip() and text != original_clipboard:
                            captured_text = text
                            break
                else:
                    text = self._get_clipboard_text()
                    if text and text.strip():
                        captured_text = text
                        break

            # Fallback check if sequence number didn't change or wasn't detected
            if not captured_text:
                candidate = self._get_clipboard_text()
                if candidate and candidate.strip() and candidate != original_clipboard:
                    captured_text = candidate

            # Restore original clipboard content if we modified it or captured new text
            if original_clipboard is not None:
                try:
                    self._set_clipboard_text(original_clipboard)
                except Exception as e:
                    logger.debug(f"Error restoring original clipboard: {e}")
            elif initial_seq is None and captured_text:
                try:
                    self._empty_clipboard()
                except Exception as e:
                    logger.debug(f"Error clearing clipboard: {e}")

            return captured_text


def get_selection_listener(
    on_selection_change: Callable[[str], None],
    **kwargs,
) -> BaseSelectionListener:
    """Factory function to create the appropriate selection listener for the current platform.

    Args:
        on_selection_change: Callback invoked when text is selected/captured.
        **kwargs: Additional platform-specific keyword arguments.

    Returns:
        WindowsSelectionListener on Windows, WaylandSelectionListener on other platforms.
    """
    if sys.platform == "win32":
        return WindowsSelectionListener(on_selection_change=on_selection_change, **kwargs)
    return WaylandSelectionListener(on_selection_change=on_selection_change, **kwargs)

