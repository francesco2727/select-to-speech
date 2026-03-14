"""Settings window for select-to-speech configuration."""

import threading
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, AudioConfig, KeyboardConfig, VoiceConfig, load_config, save_config
from ..i18n import _, set_language
from ..system_check import get_audio_devices
from ..tts_engine import get_available_models

# Available languages & their sample sentences for test voice
SAMPLE_SENTENCES = {
    "it": "Questa è una prova delle impostazioni vocali.",
    "en": "This is a test of the voice settings.",
    "fr": "Ceci est un test des paramètres vocaux.",
    "es": "Esta es una prueba de la configuración de voz.",
}

MODIFIER_KEYS = ["alt", "ctrl", "shift"]

# ── Qt key code → pynput-compatible name mapping ────────────────────

_QT_KEY_MAP: dict[int, str] = {
    Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_F1: "f1", Qt.Key.Key_F2: "f2", Qt.Key.Key_F3: "f3",
    Qt.Key.Key_F4: "f4", Qt.Key.Key_F5: "f5", Qt.Key.Key_F6: "f6",
    Qt.Key.Key_F7: "f7", Qt.Key.Key_F8: "f8", Qt.Key.Key_F9: "f9",
    Qt.Key.Key_F10: "f10", Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
    Qt.Key.Key_Space: "space", Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Insert: "insert", Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "page_up", Qt.Key.Key_PageDown: "page_down",
    Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
}

_KEY_DISPLAY: dict[str, str] = {
    "esc": "Esc", "space": "Space", "tab": "Tab",
    "insert": "Ins", "delete": "Del",
    "home": "Home", "end": "End",
    "page_up": "PgUp", "page_down": "PgDn",
    "enter": "Enter", "backspace": "Backspace",
    "up": "↑", "down": "↓", "left": "←", "right": "→",
}


def _qt_key_to_name(event: QKeyEvent) -> str | None:
    """Convert a QKeyEvent to a pynput-compatible key name, ignoring modifiers."""
    key = event.key()
    if key in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
        return None
    if key in _QT_KEY_MAP:
        return _QT_KEY_MAP[key]
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        return f"f{key - Qt.Key.Key_F1 + 1}"
    text = event.text().lower()
    if len(text) == 1 and text.isprintable():
        return text
    return None


def _display_key(name: str) -> str:
    """Return a human-friendly label for a key name."""
    if name in _KEY_DISPLAY:
        return _KEY_DISPLAY[name]
    if name.startswith("f") and name[1:].isdigit():
        return name.upper()
    return name.upper() if len(name) == 1 else name.capitalize()


# ── Chip/tag style CSS ──────────────────────────────────────────────

_CHIP_CSS = (
    "background: palette(highlight); color: palette(highlighted-text);"
    "border-radius: 4px; padding: 3px 8px; font-weight: bold; font-size: 12px;"
)

_CAPTURE_CSS = (
    "border: 2px dashed palette(highlight); border-radius: 6px;"
    "padding: 4px 10px; color: palette(text); font-style: italic;"
)

_IDLE_CSS = (
    "border: 1px solid palette(mid); border-radius: 6px;"
    "padding: 4px 10px; color: palette(text);"
)


# ═══════════════════════════════════════════════════════════════════
#  Custom Widgets
# ═══════════════════════════════════════════════════════════════════


class KeyCaptureWidget(QFrame):
    """Captures a single key press and displays it as a chip/badge."""

    keyChanged = pyqtSignal(str)

    def __init__(self, initial_key: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._key_name = initial_key
        self._capturing = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(32)
        self.setMaximumHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label, stretch=1)

        self._clear_btn = QPushButton("×")
        self._clear_btn.setFixedSize(20, 20)
        self._clear_btn.setFlat(True)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._on_clear)
        layout.addWidget(self._clear_btn)

        self._update_display()

    def key_name(self) -> str:
        return self._key_name

    def set_key(self, name: str) -> None:
        if name != self._key_name:
            self._key_name = name
            self._capturing = False
            self._update_display()
            self.keyChanged.emit(name)

    def mousePressEvent(self, event):
        self._capturing = True
        self._update_display()
        self.setFocus()

    def keyPressEvent(self, event: QKeyEvent):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        name = _qt_key_to_name(event)
        if name:
            self.set_key(name)

    def focusOutEvent(self, event):
        self._capturing = False
        self._update_display()
        super().focusOutEvent(event)

    def _on_clear(self):
        self._key_name = ""
        self._capturing = False
        self._update_display()
        self.keyChanged.emit("")

    def _update_display(self):
        if self._capturing:
            self._label.setText(_("Press a key…"))
            self.setStyleSheet(_CAPTURE_CSS)
            self._clear_btn.setVisible(False)
        elif self._key_name:
            self._label.setText(_display_key(self._key_name))
            self._label.setStyleSheet(_CHIP_CSS)
            self.setStyleSheet(_IDLE_CSS)
            self._clear_btn.setVisible(True)
        else:
            self._label.setText("")
            self._label.setStyleSheet("")
            self.setStyleSheet(_IDLE_CSS)
            self._clear_btn.setVisible(False)


class ModifierKeySelector(QFrame):
    """Row of three checkboxes (Alt, Ctrl, Shift) — stores 1–2 selected modifiers."""

    modifiersChanged = pyqtSignal(str)

    def __init__(self, initial: str = "alt", parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._checks: dict[str, QCheckBox] = {}
        for mod in MODIFIER_KEYS:
            cb = QCheckBox(mod.capitalize())
            cb.stateChanged.connect(self._on_changed)
            layout.addWidget(cb)
            self._checks[mod] = cb

        self._warn_label = QLabel()
        self._warn_label.setStyleSheet("color: red; font-size: 11px;")
        layout.addWidget(self._warn_label)
        layout.addStretch()

        self.set_modifiers(initial)

    def modifiers(self) -> str:
        selected = [m for m, cb in self._checks.items() if cb.isChecked()]
        return "+".join(selected) if selected else ""

    def set_modifiers(self, value: str) -> None:
        parts = [p.strip().lower() for p in value.split("+") if p.strip()]
        for mod, cb in self._checks.items():
            cb.blockSignals(True)
            cb.setChecked(mod in parts)
            cb.blockSignals(False)
        self._validate()

    def _on_changed(self):
        self._validate()
        self.modifiersChanged.emit(self.modifiers())

    def _validate(self):
        count = sum(1 for cb in self._checks.values() if cb.isChecked())
        if count == 0:
            self._warn_label.setText(_("Select at least one modifier key"))
        elif count > 2:
            self._warn_label.setText(_("Select at most two modifier keys"))
        else:
            self._warn_label.setText("")


# ═══════════════════════════════════════════════════════════════════

_GUI_LANGUAGES = [
    ("auto", "Auto (system)"),
    ("en", "English"),
    ("it", "Italiano"),
    ("es", "Español"),
    ("fr", "Français"),
]


class SettingsWindow(QDialog):
    """Configuration dialog with tabs for voice, audio, keyboard, and general."""

    def __init__(self, config: Optional[AppConfig] = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config or load_config()
        self._test_thread: Optional[threading.Thread] = None
        self._test_stop = threading.Event()

        # Apply the configured GUI language before building UI
        set_language(self.config.gui_language)

        self.setWindowTitle(_("Select-to-Speech — Settings"))
        self.setMinimumSize(QSize(560, 480))

        self._build_ui()
        self._load_config_into_ui()

    # ──────────────────────── UI Construction ────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # KDE Plasma-style: sidebar on the left, content on the right
        content_layout = QHBoxLayout()

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(180)
        self.sidebar.setSpacing(2)
        self.sidebar.setStyleSheet(
            "QListWidget { background: palette(window); border: none; "
            "font-size: 13px; }"
            "QListWidget::item { padding: 8px 12px; border-radius: 4px; }"
            "QListWidget::item:selected { background: palette(highlight); "
            "color: palette(highlighted-text); }"
        )
        for label in (_("Engine"), _("Audio"), _("Shortcuts"), _("General")):
            QListWidgetItem(label, self.sidebar)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_voice_tab())
        self.pages.addWidget(self._build_audio_tab())
        self.pages.addWidget(self._build_keyboard_tab())
        self.pages.addWidget(self._build_general_tab())

        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.pages, stretch=1)
        layout.addLayout(content_layout)

        # Bottom bar: Test Voice + dialog buttons
        bottom = QHBoxLayout()
        self.test_btn = QPushButton(_("Test Voice"))
        self.test_btn.clicked.connect(self._on_test_voice)
        bottom.addWidget(self.test_btn)
        bottom.addStretch()

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self._on_save)
        btn_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        bottom.addWidget(btn_box)

        layout.addLayout(bottom)

    # ── Voice Tab ────────────────────────────────────────────────────

    def _build_voice_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["kokoro", "piper"])
        self.engine_combo.currentTextChanged.connect(self._populate_model_combo)
        form.addRow(_("Engine:"), self.engine_combo)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        form.addRow(_("Model:"), self.model_combo)

        self._populate_model_combo(self.engine_combo.currentText())

        return tab

    def _populate_model_combo(self, engine: str) -> None:
        """Refresh the model combo for the selected engine."""
        current = self.model_combo.currentText()
        self.model_combo.clear()

        models = get_available_models(engine)
        if models:
            self.model_combo.addItems(models)
        else:
            self.model_combo.addItem(_("(no models found)"))

        idx = self.model_combo.findText(current)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        elif current:
            self.model_combo.setEditText(current)

    # ── Audio Tab ────────────────────────────────────────────────────

    def _build_audio_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.speed_spin, self.speed_slider = self._make_slider_pair(0.5, 2.0, 0.1, 1.0)
        form.addRow(_("Speed:"), self._h_pair(self.speed_slider, self.speed_spin))

        self.pitch_spin, self.pitch_slider = self._make_slider_pair(0.5, 2.0, 0.1, 1.0)
        form.addRow(_("Pitch:"), self._h_pair(self.pitch_slider, self.pitch_spin))

        self.volume_spin, self.volume_slider = self._make_slider_pair(0.0, 2.0, 0.1, 1.0)
        form.addRow(_("Volume:"), self._h_pair(self.volume_slider, self.volume_spin))

        self.device_combo = QComboBox()
        self._populate_audio_devices()
        form.addRow(_("Audio device:"), self.device_combo)

        return tab

    def _make_slider_pair(
        self, min_val: float, max_val: float, step: float, default: float
    ) -> tuple[QDoubleSpinBox, QSlider]:
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setSingleStep(step)
        spin.setDecimals(1)
        spin.setValue(default)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(min_val * 10), int(max_val * 10))
        slider.setValue(int(default * 10))

        # Synchronise slider ↔ spin box
        slider.valueChanged.connect(lambda v: spin.setValue(v / 10.0))
        spin.valueChanged.connect(lambda v: slider.setValue(int(v * 10)))

        return spin, slider

    @staticmethod
    def _h_pair(left: QWidget, right: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(left, stretch=1)
        h.addWidget(right)
        return w

    def _populate_audio_devices(self):
        self.device_combo.clear()
        self.device_combo.addItem(_("System default"), None)
        for dev in get_audio_devices():
            label = f"{dev['name']}  ({dev['sample_rate']} Hz, {dev['channels']}ch)"
            if dev["is_default"]:
                label += "  [DEFAULT]"
            self.device_combo.addItem(label, dev["id"])

    # ── Keyboard Tab ─────────────────────────────────────────────────

    def _build_keyboard_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.mod_selector = ModifierKeySelector()
        self.mod_selector.modifiersChanged.connect(lambda _: self._update_shortcut_preview())
        form.addRow(_("Modifier keys:"), self.mod_selector)

        self.trigger_capture = KeyCaptureWidget()
        self.trigger_capture.keyChanged.connect(lambda _: self._update_shortcut_preview())
        form.addRow(_("Play key:"), self.trigger_capture)

        self.pause_capture = KeyCaptureWidget()
        self.pause_capture.keyChanged.connect(lambda _: self._update_shortcut_preview())
        form.addRow(_("Pause / Resume key:"), self.pause_capture)

        self.stop_capture = KeyCaptureWidget()
        self.stop_capture.keyChanged.connect(lambda _: self._update_shortcut_preview())
        form.addRow(_("Stop key:"), self.stop_capture)

        # Live preview label
        self.shortcut_preview = QLabel()
        self.shortcut_preview.setStyleSheet("font-style: italic; opacity: 0.7;")
        form.addRow("", self.shortcut_preview)

        return tab

    def _update_shortcut_preview(self):
        mod = self.mod_selector.modifiers()
        mod_display = "+".join(m.capitalize() for m in mod.split("+") if m)
        play = _display_key(self.trigger_capture.key_name()) if self.trigger_capture.key_name() else "—"
        pause = _display_key(self.pause_capture.key_name()) if self.pause_capture.key_name() else "—"
        stop = _display_key(self.stop_capture.key_name()) if self.stop_capture.key_name() else "—"

        parts = []
        if mod_display:
            parts.append(f"{_('Play:')} {mod_display}+{play}")
            parts.append(f"{_('Pause:')} {mod_display}+{pause}")
            parts.append(f"{_('Stop:')} {mod_display}+{stop}")
        else:
            parts.append(f"{_('Play:')} {play}")
            parts.append(f"{_('Pause:')} {pause}")
            parts.append(f"{_('Stop:')} {stop}")
        self.shortcut_preview.setText("   |   ".join(parts))

    # ── General Tab ──────────────────────────────────────────────────

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.debug_check = QCheckBox(_("Enable debug logging"))
        form.addRow(self.debug_check)

        self.lang_combo = QComboBox()
        for code, display in _GUI_LANGUAGES:
            if code == "auto":
                self.lang_combo.addItem(_("Auto (system)"), code)
            else:
                self.lang_combo.addItem(display, code)
        form.addRow(_("Language:"), self.lang_combo)

        return tab

    # ──────────────────────── Config ↔ UI ────────────────────────────

    def _load_config_into_ui(self):
        v = self.config.voice
        self.engine_combo.setCurrentText(v.engine)
        self._populate_model_combo(v.engine)
        idx = self.model_combo.findText(v.model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.setEditText(v.model)

        a = self.config.audio
        self.speed_spin.setValue(a.speed)
        self.pitch_spin.setValue(a.pitch)
        self.volume_spin.setValue(a.volume)

        idx = self.device_combo.findData(a.device_id)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)

        k = self.config.keyboard
        self.mod_selector.set_modifiers(k.modifier_key)
        self.trigger_capture.set_key(k.trigger_key)
        self.pause_capture.set_key(k.pause_key)
        self.stop_capture.set_key(k.stop_key)
        self._update_shortcut_preview()

        self.debug_check.setChecked(self.config.debug)

        lang_idx = self.lang_combo.findData(self.config.gui_language)
        if lang_idx >= 0:
            self.lang_combo.setCurrentIndex(lang_idx)

    def _read_config_from_ui(self) -> AppConfig:
        model_text = self.model_combo.currentText().strip()
        if model_text == _("(no models found)"):
            model_text = self.config.voice.model

        return AppConfig(
            voice=VoiceConfig(
                engine=self.engine_combo.currentText(),
                model=model_text,
                language=self.config.voice.language,
                language_models=self.config.voice.language_models,
            ),
            audio=AudioConfig(
                device_id=self.device_combo.currentData(),
                speed=self.speed_spin.value(),
                pitch=self.pitch_spin.value(),
                volume=self.volume_spin.value(),
            ),
            keyboard=KeyboardConfig(
                modifier_key=self.mod_selector.modifiers(),
                trigger_key=self.trigger_capture.key_name(),
                pause_key=self.pause_capture.key_name(),
                stop_key=self.stop_capture.key_name(),
            ),
            debug=self.debug_check.isChecked(),
            gui_language=self.lang_combo.currentData() or "auto",
        )

    # ──────────────────────── Actions ────────────────────────────────

    def _on_apply(self):
        self.config = self._read_config_from_ui()
        save_config(self.config)
        set_language(self.config.gui_language)

    def _on_save(self):
        self._on_apply()
        self.accept()

    def _on_test_voice(self):
        """Synthesise and play a short sample with current (unsaved) settings."""
        # Stop any running test
        if self._test_thread and self._test_thread.is_alive():
            self._test_stop.set()
            self._test_thread.join(timeout=2)

        self._test_stop.clear()
        cfg = self._read_config_from_ui()
        lang = cfg.voice.language
        sample = SAMPLE_SENTENCES.get(lang, SAMPLE_SENTENCES["en"])

        self.test_btn.setText(_("Stop Test"))
        self.test_btn.clicked.disconnect()
        self.test_btn.clicked.connect(self._stop_test_voice)

        def _run():
            try:
                from ..tts_engine import get_tts_engine
                from ..audio_player import AudioPlayer

                engine = get_tts_engine(cfg.voice)
                result = engine.synthesize(sample, language=lang, speed=cfg.audio.speed, volume=cfg.audio.volume)
                if result is None or self._test_stop.is_set():
                    return
                audio_bytes, sample_rate = result
                player = AudioPlayer(cfg.audio.device_id)
                player.play(audio_bytes, sample_rate, pitch=cfg.audio.pitch)
            except Exception:
                pass
            finally:
                # Reset button (safe cross-thread via Qt queued connection)
                self.test_btn.setText(_("Test Voice"))
                try:
                    self.test_btn.clicked.disconnect()
                except TypeError:
                    pass
                self.test_btn.clicked.connect(self._on_test_voice)

        self._test_thread = threading.Thread(target=_run, daemon=True)
        self._test_thread.start()

    def _stop_test_voice(self):
        self._test_stop.set()
