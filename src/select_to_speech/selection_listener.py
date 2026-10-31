"""Primary selection listener with Wayland-native and XWayland fallback support"""

import concurrent.futures
import logging
import select as _select
import subprocess
import threading
import time
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


# Sources in priority order: Wayland primary first (native selections), then
# the X11 primary (XWayland apps), then the two clipboards for apps that only
# publish text after an explicit copy.
_SOURCE_PRIORITY: tuple[str, ...] = (
    "wayland_primary",
    "x11_primary",
    "wayland_clipboard",
    "x11_clipboard",
)

_GATHER_TIMEOUT_S = 1.5
_X11_READ_TIMEOUT_S = 0.5
_WATCH_RESPAWN_S = 5.0


# ----------------------------------------------------------------------
# X11 selection access (XWayland) via python-Xlib — replaces xclip
# ----------------------------------------------------------------------

def _wait_readable(d: Any, deadline: float) -> bool:
    """Return True when the X connection has data before ``deadline``."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    try:
        ready, _, _ = _select.select([d.fileno()], [], [], remaining)
    except (OSError, ValueError):
        return False
    return bool(ready)


def _next_x11_event(d: Any, deadline: float) -> Any:
    """Return the next X event before ``deadline``, or None on timeout.

    Events already parsed into python-Xlib's internal queue are returned
    without touching the socket; otherwise we wait for new wire data.
    """
    while time.monotonic() < deadline:
        if d.pending_events():
            return d.next_event()
        if not _wait_readable(d, deadline):
            return None
    return None


def _read_x11_incr(
    d: Any,
    win: Any,
    property_atom: Any,
    deadline: float,
) -> bytes:
    """Read the remaining chunks of an INCR selection transfer."""
    from Xlib import X

    chunks: list[bytes] = []
    while time.monotonic() < deadline:
        event = _next_x11_event(d, deadline)
        if event is None:
            break
        if event.type != X.PropertyNotify or event.atom != property_atom:
            continue
        if event.state != X.PropertyNewValue:
            continue
        prop = win.get_full_property(property_atom, X.AnyPropertyType)
        win.delete_property(property_atom)
        if prop is None or not prop.value:
            break
        chunks.append(bytes(prop.value))
    return b"".join(chunks)


def _read_x11_selection(selection: str, timeout_s: float = _X11_READ_TIMEOUT_S) -> Optional[str]:
    """Read an X11 selection (``PRIMARY`` or ``CLIPBOARD``) via python-Xlib.

    Talks directly to the X server (XWayland), so no external helper such as
    ``xclip`` is needed to capture selections from XWayland applications.

    Returns the selection text, or None when the selection is empty, the
    conversion is refused, or no X server is reachable.
    """
    try:
        from Xlib import X
        from Xlib import display as xlib_display
    except (ImportError, OSError):
        return None

    try:
        d = xlib_display.Display()
    except Exception as e:
        logger.debug(f"X11 display unavailable ({selection}): {e}")
        return None

    try:
        root = d.screen().root
        win = root.create_window(0, 0, 1, 1, 0, X.CopyFromParent)
        win.change_attributes(event_mask=X.PropertyChangeMask)

        selection_atom = d.intern_atom(selection)
        incr_atom = d.intern_atom("INCR")

        for target_name in ("UTF8_STRING", "STRING"):
            target_atom = d.intern_atom(target_name)
            # A distinct property per target: the server may delete or rewrite
            # the property of a previous conversion attempt.
            property_atom = d.intern_atom(f"_SELECT_TO_SPEECH_{target_name}")

            win.convert_selection(
                selection=selection_atom,
                target=target_atom,
                property=property_atom,
                time=X.CurrentTime,
            )
            d.flush()

            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                event = _next_x11_event(d, deadline)
                if event is None:
                    break
                if event.type != X.SelectionNotify:
                    continue
                if event.selection != selection_atom or event.target != target_atom:
                    continue  # stale reply from an earlier request
                if not event.property:
                    break  # owner refused this target: try the next one
                prop = win.get_full_property(property_atom, X.AnyPropertyType)
                win.delete_property(property_atom)
                if prop is None or prop.value is None:
                    break
                if prop.property_type == incr_atom:
                    data = _read_x11_incr(d, win, property_atom, deadline)
                else:
                    data = bytes(prop.value)
                if data:
                    return data.decode("utf-8", errors="replace")
        return None
    except Exception as e:
        logger.debug(f"Error retrieving X11 {selection} selection: {e}")
        return None
    finally:
        try:
            d.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# Wayland selection change watch (wl-clipboard --watch)
# ----------------------------------------------------------------------

class _SelectionWatch:
    """Timestamps selection changes via ``wl-paste --watch``.

    wl-clipboard's watch mode runs a tiny command for every selection change;
    each run prints one line, so the reader thread can timestamp changes
    without buffering selection content (content is always pulled on demand).
    This also detects re-copies of identical text, which content comparison
    alone cannot distinguish from stale data.
    """

    def __init__(self, primary: bool):
        self._args = (
            ["wl-paste"]
            + (["--primary"] if primary else [])
            + ["--watch", "sh", "-c", "cat > /dev/null; echo"]
        )
        self._proc: Optional[subprocess.Popen] = None
        self._last_spawn = 0.0
        self._lock = threading.Lock()
        self.last_event_ts: Optional[float] = None

    def start(self) -> None:
        with self._lock:
            self._spawn()

    def _spawn(self) -> None:
        self._last_spawn = time.monotonic()
        try:
            self._proc = subprocess.Popen(
                self._args,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error(
                "wl-paste not found. This is required for Wayland clipboard access.\n"
                "Install wl-clipboard on Arch Linux: sudo pacman -S wl-clipboard\n"
                "Or run: python -m select_to_speech.system_check"
            )
            self._proc = None
            return
        except Exception as e:
            logger.debug(f"Failed to start selection watch: {e}")
            self._proc = None
            return
        threading.Thread(target=self._read_events, daemon=True).start()

    def _read_events(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for _line in proc.stdout:
                with self._lock:
                    self.last_event_ts = time.monotonic()
        except Exception as e:
            logger.debug(f"Selection watch reader stopped: {e}")

    def ensure_running(self) -> None:
        """Restart the watch process if it died (e.g. after a compositor restart)."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            if time.monotonic() - self._last_spawn < _WATCH_RESPAWN_S:
                return
            logger.debug("Selection watch process died, restarting...")
            self._spawn()

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


class WaylandSelectionListener:
    """Reads the freshest selectable text from Wayland and X11 sources.

    Native Wayland apps write to the Wayland primary selection (read via
    ``wl-paste --primary``).  Apps running under XWayland maintain a separate
    X11 PRIMARY selection that ``wl-paste`` cannot see; those are read
    directly through python-Xlib.  The two CLIPBOARD sources are used as a
    last resort for apps that only publish text after an explicit copy.

    On every trigger all sources are read and the *freshest* content wins:
    a source is considered fresh when ``wl-paste --watch`` saw it change
    (Wayland sources), or when its content differs from the previous read.
    A stale primary selection therefore never hides a newer clipboard copy.
    If nothing changed, the content of the freshest source is returned again,
    so pressing the hotkey twice still replays the same text.
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
        self._lock = threading.Lock()
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = (
            concurrent.futures.ThreadPoolExecutor(max_workers=4)
        )
        # (content, monotonic time when the content was first observed) per source.
        self._observed: dict[str, tuple[str, float]] = {}
        self._last_gather_ts = 0.0
        self._watches: dict[str, _SelectionWatch] = {
            "wayland_primary": _SelectionWatch(primary=True),
            "wayland_clipboard": _SelectionWatch(primary=False),
        }

    def _ensure_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Ensure the thread pool executor is initialized and running."""
        with self._lock:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
            return self._executor

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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

    def _get_x11_primary(self) -> Optional[str]:
        """Return the X11 PRIMARY selection via python-Xlib, or None."""
        return _read_x11_selection("PRIMARY")

    def _get_x11_clipboard(self) -> Optional[str]:
        """Return the X11 CLIPBOARD selection via python-Xlib, or None."""
        return _read_x11_selection("CLIPBOARD")

    def _gather(self) -> dict[str, Optional[str]]:
        """Read all four selection sources concurrently."""
        for watch in self._watches.values():
            if self.is_running:
                watch.ensure_running()
        try:
            executor = self._ensure_executor()
            futures = {
                name: executor.submit(getattr(self, f"_get_{name}"))
                for name in _SOURCE_PRIORITY
            }
        except RuntimeError as e:
            logger.debug(f"Selection listener executor shut down or unavailable: {e}")
            return {name: None for name in _SOURCE_PRIORITY}

        contents: dict[str, Optional[str]] = {}
        for name, future in futures.items():
            try:
                contents[name] = future.result(timeout=_GATHER_TIMEOUT_S)
            except Exception as e:
                logger.debug(f"Error/timeout reading {name}: {e}")
                contents[name] = None
        return contents

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_primary_selection(self) -> Optional[str]:
        """Get the freshest selectable text across Wayland and X11 sources.

        Priority order (used only to break freshness ties):
        1. Wayland PRIMARY (``wl-paste --primary``) – native Wayland apps.
        2. X11 PRIMARY (python-Xlib) – XWayland apps.
        3. Wayland CLIPBOARD (``wl-paste``) – native Wayland clipboard copy.
        4. X11 CLIPBOARD (python-Xlib) – XWayland clipboard copy.

        The source whose content changed most recently wins, so a stale
        primary selection never hides a fresh clipboard copy.

        Returns:
            Selected text or None if unavailable
        """
        contents = self._gather()
        now = time.monotonic()

        with self._lock:
            observed = dict(self._observed)
            last_gather_ts = self._last_gather_ts
            event_ts = {
                name: watch.last_event_ts for name, watch in self._watches.items()
            }

        # Score every source: content confirmed fresh by a watch event or a
        # content change gets the time it changed at; unchanged content keeps
        # the time it was last confirmed at.
        candidates: list[tuple[float, int, str, str]] = []
        updates: dict[str, tuple[str, float]] = {}
        for priority, name in enumerate(_SOURCE_PRIORITY):
            text = contents.get(name)
            if not text or not text.strip():
                continue
            stripped = text.strip()
            stored_content, stored_ts = observed.get(name, ("", 0.0))
            fresh_ts: Optional[float] = None
            watch_ts = event_ts.get(name)
            if watch_ts is not None and watch_ts > last_gather_ts:
                fresh_ts = watch_ts  # wl-paste --watch saw a change
            if fresh_ts is None and stripped != stored_content:
                fresh_ts = now  # content differs from the previous read
            if fresh_ts is not None:
                updates[name] = (stripped, fresh_ts)
                candidates.append((fresh_ts, priority, name, text))
            else:
                candidates.append((stored_ts, priority, name, text))

        winner: Optional[tuple[float, int, str, str]] = None
        winner_score: Optional[tuple[float, int]] = None
        for ts, priority, name, text in candidates:
            # Higher timestamp wins; on ties the lower priority index wins.
            score = (ts, -priority)
            if winner_score is None or score > winner_score:
                winner_score = score
                winner = (ts, priority, name, text)

        with self._lock:
            self._last_gather_ts = now
            for name, snapshot in updates.items():
                # Remember when this content was confirmed so it is not
                # mistaken for fresh again while it stays unchanged.
                self._observed[name] = snapshot
            for name, text in contents.items():
                if not (text and text.strip()):
                    # Selection emptied or unreadable: forget stored content so
                    # a future selection of the same text counts as fresh.
                    self._observed.pop(name, None)

        if winner is None:
            logger.debug("No text selected or clipboard is empty")
            return None

        _, _, source, text = winner
        logger.debug(f"Using selection source: {source}")
        return text

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
        for watch in self._watches.values():
            watch.start()

        # Baseline the current selections so content that predates the
        # daemon is not mistaken for a fresh selection on the first trigger.
        contents = self._gather()
        with self._lock:
            for name, text in contents.items():
                if text and text.strip():
                    # Timestamp 0 = "observed at startup, unknown freshness".
                    self._observed[name] = (text.strip(), 0.0)
            self._last_gather_ts = time.monotonic()

        self.is_running = True
        logger.info("Selection listener started")

    def stop(self) -> None:
        """Stop the selection listener and release executor resources."""
        self.is_running = False
        for watch in self._watches.values():
            watch.stop()
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
