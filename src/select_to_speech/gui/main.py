"""GUI entry points — system-tray mode and standalone settings."""

import logging
import os
import signal
import sys
from typing import Optional

# Use native KDE/Plasma theme when available
os.environ.setdefault("QT_QPA_PLATFORMTHEME", "kde")

import KCoreAddons
import KNotifications

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ..config import load_config
from ..i18n import _, set_language
from ..main import SelectToSpeechApp
from .settings_window import SettingsWindow
from .tray_icon import AppBridge, AppState, SystemTrayIcon

logger = logging.getLogger(__name__)


class GUIApp:
    """Wraps SelectToSpeechApp with a Qt event loop and system tray."""

    def __init__(self, qt_app: QApplication):
        self.qt_app = qt_app
        self.config = load_config()
        set_language(self.config.gui_language)
        self.bridge = AppBridge()

        # Build the core app — but we won't call its .run() (that blocks with signal.pause)
        self.app = SelectToSpeechApp(self.config)

        # Monkey-patch callbacks so the bridge knows about state changes
        self._patch_app_callbacks()

        # System tray
        self.tray = SystemTrayIcon(self.bridge)
        self.tray.pause_action.triggered.connect(self._on_tray_pause)
        self.tray.stop_action.triggered.connect(self._on_tray_stop)
        self.tray.open_settings_requested.connect(self._open_settings)
        self.tray.show()

        self._settings_window: Optional[SettingsWindow] = None

        # Start the background listeners the same way the CLI app does
        self.app.selection_listener.start()
        self.app.keyboard_handler.start()

        # Periodic state poll — lightweight, once per 500 ms
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_state)
        self._poll_timer.start(500)

    # ── App callback patching ────────────────────────────────────────

    def _patch_app_callbacks(self):
        """Wrap _on_text_selected / _on_stop_pressed / screen reader to emit state."""
        original_on_text = self.app._on_text_selected
        original_on_stop = self.app._on_stop_pressed
        original_describe_screen = self.app._on_describe_screen_pressed

        def wrapped_on_text(text: str):
            self.bridge.set_state(AppState.SPEAKING)
            self._notify_speaking(text)
            original_on_text(text)

        def wrapped_on_stop():
            original_on_stop()
            self.bridge.set_state(AppState.IDLE)

        def wrapped_describe_screen():
            self.bridge.set_state(AppState.SPEAKING)
            self._notify_speaking(_("Describing screen..."))
            original_describe_screen()

        self.app._on_text_selected = wrapped_on_text
        self.app._on_stop_pressed = wrapped_on_stop
        self.app._on_describe_screen_pressed = wrapped_describe_screen

    def _poll_state(self):
        """Sync tray state with audio_player (handles natural end-of-playback)."""
        player = self.app.audio_player
        if player.is_playing:
            if player.is_paused:
                self.bridge.set_state(AppState.PAUSED)
            else:
                self.bridge.set_state(AppState.SPEAKING)
        else:
            self.bridge.set_state(AppState.IDLE)

    # ── Notifications ────────────────────────────────────────────────

    def _notify_speaking(self, text: str):
        """Send a native KDE desktop notification when TTS starts."""
        notif = KNotifications.KNotification(
            "speaking-started",
            KNotifications.KNotification.NotificationFlag.CloseOnTimeout,
        )
        notif.setTitle(_("Speaking"))
        notif.setText(text[:80] + ("…" if len(text) > 80 else ""))
        notif.setIconName("media-playback-start")
        notif.sendEvent()

    # ── Tray actions ─────────────────────────────────────────────────

    def _on_tray_pause(self):
        player = self.app.audio_player
        if player.is_playing:
            if player.is_paused:
                player.resume()
            else:
                player.pause()

    def _on_tray_stop(self):
        self.app._on_stop_pressed()

    def _open_settings(self):
        if self._settings_window and self._settings_window.isVisible():
            self._settings_window.activateWindow()
            return
        self._settings_window = SettingsWindow(self.config)
        if self._settings_window.exec():
            # User clicked Save — reload live
            self.config = load_config()
            self._hot_reload()

    # ── Hot-reload ───────────────────────────────────────────────────

    def _hot_reload(self):
        """Reinitialise components that depend on config."""
        # Keyboard shortcuts
        try:
            self.app.keyboard_handler.stop()
        except Exception:
            pass

        from ..keyboard_handler import KeyboardHandler

        self.app.config = self.config
        extra_hotkeys = self.app._build_ollama_hotkeys()
        self.app.keyboard_handler = KeyboardHandler(
            on_play=self.app._on_shortcut_pressed,
            on_pause=self.app._on_pause_pressed,
            on_stop=self.app._on_stop_pressed,
            modifier=self.config.keyboard.modifier_key,
            trigger_key=self.config.keyboard.trigger_key,
            pause_key=self.config.keyboard.pause_key,
            stop_key=self.config.keyboard.stop_key,
            extra_hotkeys=extra_hotkeys,
        )
        self.app.keyboard_handler.start()

        # TTS engine — recreate if engine type changed
        from ..tts_engine import get_tts_engine

        self.app.tts_engine.stop()
        self.app.tts_engine = get_tts_engine(self.config.voice)

        # Audio settings apply on next playback automatically (stored in config)
        self.app.audio_player.device_id = self.config.audio.device_id

        logger.info("Settings hot-reloaded")
        set_language(self.config.gui_language)

    # ── Shutdown ─────────────────────────────────────────────────────

    def shutdown(self):
        self._poll_timer.stop()
        self.app.shutdown()


# ── CLI entry points ─────────────────────────────────────────────────

def _setup_about_data():
    about = KCoreAddons.KAboutData(
        "select-to-speech",
        _("Select to Speech"),
        "1.0.0",
        _("Text-to-speech for selected text"),
        KCoreAddons.KAboutLicense.GPL_V3,
    )
    about.addAuthor(_("Francesco"), _("Author"), "francescov@example.com")
    KCoreAddons.KAboutData.setApplicationData(about)


def main():
    """System-tray mode: background app + tray icon."""
    _setup_about_data()

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Select-to-Speech")
    qt_app.setQuitOnLastWindowClosed(False)

    gui = GUIApp(qt_app)

    # Let Ctrl-C work in terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    exit_code = qt_app.exec()
    gui.shutdown()
    sys.exit(exit_code)


def open_settings():
    """Standalone settings window — no tray, no background app."""
    _setup_about_data()

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Select-to-Speech Settings")

    config = load_config()
    set_language(config.gui_language)
    dialog = SettingsWindow(config)
    dialog.show()

    sys.exit(qt_app.exec())
