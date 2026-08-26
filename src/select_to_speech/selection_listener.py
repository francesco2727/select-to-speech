"""Primary selection listener with Wayland-native and XWayland fallback support"""

import logging
import shutil
import subprocess
import threading
import concurrent.futures
from typing import Optional, Callable


logger = logging.getLogger(__name__)


class WaylandSelectionListener:
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
        """
        Initialize the selection listener.

        Args:
            on_selection_change: Callback called when user explicitly triggers playback
        """
        self.on_selection_change = on_selection_change
        self.last_selection = ""
        self.is_running = False
        self._xclip_available: Optional[bool] = None  # lazy-checked once
        self._last_clipboard = ""  # track clipboard to detect changes
        self._lock = threading.Lock()
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
        """Return the X11 CLIPBOARD selection via ``xclip``, or None.

        Used as a last-resort fallback for Chromium/CEF-based XWayland apps
        (e.g. ONLYOFFICE) that populate CLIPBOARD but not PRIMARY on text
        selection.  Only returned when the clipboard content has changed since
        the last check, to avoid reading stale copied text.
        """
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
        """Start the selection listener"""
        self._ensure_executor()
        self.is_running = True
        logger.info("Selection listener started")

    def stop(self) -> None:
        """Stop the selection listener and release executor resources."""
        self.is_running = False
        with self._lock:
            if self._executor is not None:
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    self._executor.shutdown(wait=False)
                self._executor = None
        logger.info("Selection listener stopped")

    def __del__(self) -> None:
        """Clean up executor resources on disposal."""
        try:
            self.stop()
        except Exception:
            pass
