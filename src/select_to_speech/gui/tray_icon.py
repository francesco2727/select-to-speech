"""System tray icon for select-to-speech."""

from enum import Enum

from PyQt6.QtCore import Qt, QObject, QSize, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..i18n import _


class AppState(Enum):
    IDLE = "Idle"
    SPEAKING = "Speaking"
    PAUSED = "Paused"


# Colours for each state (works on both light & dark backgrounds)
_STATE_COLORS: dict[AppState, QColor] = {
    AppState.IDLE: QColor(76, 175, 80),      # green
    AppState.SPEAKING: QColor(66, 133, 244),  # blue
    AppState.PAUSED: QColor(255, 152, 0),     # orange
}


def _make_circle_icon(color: QColor, size: int = 64) -> QIcon:
    """Generate a simple filled-circle icon with antialiasing."""
    pix = QPixmap(QSize(size, size))
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    margin = size // 8
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.end()
    return QIcon(pix)


class AppBridge(QObject):
    """Thin bridge that emits Qt signals from app callbacks."""

    state_changed = pyqtSignal(AppState)

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


class SystemTrayIcon(QSystemTrayIcon):
    """Tray icon with context menu and state-aware icon colour."""

    open_settings_requested = pyqtSignal()

    def __init__(self, bridge: AppBridge, parent: QWidget | None = None):
        super().__init__(parent)
        self.bridge = bridge

        # Pre-generate icons for each state
        self._icons = {state: _make_circle_icon(color) for state, color in _STATE_COLORS.items()}

        self._build_menu()
        self._apply_state(AppState.IDLE)

        bridge.state_changed.connect(self._apply_state)
        self.activated.connect(self._on_activated)

    # ── Menu ─────────────────────────────────────────────────────────

    def _build_menu(self):
        self._menu = QMenu()

        self.status_action = QAction(_("Status: Idle"), self._menu)
        self.status_action.setEnabled(False)
        self._menu.addAction(self.status_action)
        self._menu.addSeparator()

        self.pause_action = QAction(_("Pause"), self._menu)
        self.pause_action.setEnabled(False)
        self._menu.addAction(self.pause_action)

        self.stop_action = QAction(_("Stop"), self._menu)
        self.stop_action.setEnabled(False)
        self._menu.addAction(self.stop_action)

        self._menu.addSeparator()

        self.settings_action = QAction(_("Settings"), self._menu)
        self.settings_action.triggered.connect(self.open_settings_requested.emit)
        self._menu.addAction(self.settings_action)

        self._menu.addSeparator()

        self.quit_action = QAction(_("Quit"), self._menu)
        self.quit_action.triggered.connect(self._on_quit)
        self._menu.addAction(self.quit_action)

        self.setContextMenu(self._menu)

    # ── State handling ───────────────────────────────────────────────

    _STATUS_MSGIDS = {
        AppState.IDLE: "Status: Idle",
        AppState.SPEAKING: "Status: Speaking",
        AppState.PAUSED: "Status: Paused",
    }
    _STATE_LABELS = {
        AppState.IDLE: "Idle",
        AppState.SPEAKING: "Speaking",
        AppState.PAUSED: "Paused",
    }

    @pyqtSlot(AppState)
    def _apply_state(self, state: AppState):
        self.setIcon(self._icons[state])
        label = _(self._STATE_LABELS[state])
        self.setToolTip(f"Select-to-Speech — {label}")
        self.status_action.setText(_(self._STATUS_MSGIDS[state]))

        is_active = state in (AppState.SPEAKING, AppState.PAUSED)
        self.pause_action.setEnabled(is_active)
        self.stop_action.setEnabled(is_active)

        if state == AppState.PAUSED:
            self.pause_action.setText(_("Resume"))
        else:
            self.pause_action.setText(_("Pause"))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings_requested.emit()

    def _on_quit(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()
