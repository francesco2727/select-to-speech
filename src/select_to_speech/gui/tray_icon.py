"""System tray icon for select-to-speech — native KDE status notifier."""

from enum import Enum

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu

import KStatusNotifierItem as KSNI

from ..i18n import _


class AppState(Enum):
    IDLE = "Idle"
    SPEAKING = "Speaking"
    PAUSED = "Paused"


_STATE_ICONS: dict[AppState, str] = {
    AppState.IDLE: "audio-volume-high",
    AppState.SPEAKING: "media-playback-start",
    AppState.PAUSED: "media-playback-pause",
}


class AppBridge(QObject):
    """Thin bridge that emits Qt signals from app callbacks."""

    state_changed = Signal(AppState)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._state = AppState.IDLE

    @property
    def state(self) -> AppState:
        return self._state

    def set_state(self, state: AppState):
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)


class SystemTrayIcon(QObject):
    """Native KDE status notifier item with state-aware theme icons."""

    open_settings_requested = Signal()

    def __init__(self, bridge: AppBridge, parent: QObject | None = None):
        super().__init__(parent)
        self.bridge = bridge

        self._tray = KSNI.KStatusNotifierItem("select-to-speech-tray", self)
        self._tray.setTitle(_("Select to Speech"))
        self._tray.setStatus(KSNI.KStatusNotifierItem.ItemStatus.Active)
        # Suppress KDE's auto-added standard actions (Quit, etc.) to avoid
        # duplicating the Quit entry we add in our own context menu.
        self._tray.setStandardActionsEnabled(False)

        self._build_menu()
        self._apply_state(AppState.IDLE)

        bridge.state_changed.connect(self._apply_state)
        self._tray.activateRequested.connect(self._on_activate_requested)

    def show(self):
        # KStatusNotifierItem is visible once created; kept for call-site compatibility.
        pass

    # ── Menu ─────────────────────────────────────────────────────────

    def _build_menu(self):
        self._menu = QMenu()

        self.status_action = self._menu.addAction(_("Status: Idle"))
        self.status_action.setEnabled(False)
        self._menu.addSeparator()

        self.pause_action = self._menu.addAction(_("Pause"))
        self.pause_action.setEnabled(False)

        self.stop_action = self._menu.addAction(_("Stop"))
        self.stop_action.setEnabled(False)

        self._menu.addSeparator()

        self.settings_action = self._menu.addAction(_("Settings"))
        self.settings_action.triggered.connect(self.open_settings_requested.emit)

        self._menu.addSeparator()

        self.quit_action = self._menu.addAction(_("Quit"))
        self.quit_action.triggered.connect(QApplication.instance().quit)

        self._tray.setContextMenu(self._menu)

    # ── State handling ───────────────────────────────────────────────

    _STATUS_MSGIDS: dict[AppState, str] = {
        AppState.IDLE: "Status: Idle",
        AppState.SPEAKING: "Status: Speaking",
        AppState.PAUSED: "Status: Paused",
    }
    _STATE_LABELS: dict[AppState, str] = {
        AppState.IDLE: "Idle",
        AppState.SPEAKING: "Speaking",
        AppState.PAUSED: "Paused",
    }

    @Slot(AppState)
    def _apply_state(self, state: AppState):
        icon_name = _STATE_ICONS[state]
        self._tray.setIconByName(icon_name)
        label = _(self._STATE_LABELS[state])
        self._tray.setToolTip(icon_name, _("Select to Speech"), label)
        self.status_action.setText(_(self._STATUS_MSGIDS[state]))

        is_active = state in (AppState.SPEAKING, AppState.PAUSED)
        self.pause_action.setEnabled(is_active)
        self.stop_action.setEnabled(is_active)

        self.pause_action.setText(_("Resume") if state == AppState.PAUSED else _("Pause"))

    def _on_activate_requested(self, active: bool, pos):
        if active:
            self.open_settings_requested.emit()
