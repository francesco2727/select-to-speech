"""Settings window for select-to-speech configuration."""

import threading
from typing import Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, AudioConfig, KeyboardConfig, VoiceConfig, load_config, save_config
from ..system_check import get_audio_devices

# Available languages & their sample sentences for test voice
SAMPLE_SENTENCES = {
    "it": "Questa è una prova delle impostazioni vocali.",
    "en": "This is a test of the voice settings.",
    "fr": "Ceci est un test des paramètres vocaux.",
    "es": "Esta es una prueba de la configuración de voz.",
}

MODIFIER_KEYS = ["alt", "ctrl", "shift"]

TRIGGER_KEYS = [
    "esc", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "space", "tab", "insert", "delete", "home", "end", "page_up", "page_down",
]


class SettingsWindow(QDialog):
    """Configuration dialog with tabs for voice, audio, keyboard, and general."""

    def __init__(self, config: Optional[AppConfig] = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config or load_config()
        self._test_thread: Optional[threading.Thread] = None
        self._test_stop = threading.Event()

        self.setWindowTitle("Select-to-Speech — Settings")
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
        for label in ("Engine", "Audio", "Shortcuts", "General"):
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
        self.test_btn = QPushButton("Test Voice")
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
        form.addRow("Engine:", self.engine_combo)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("e.g. kokoro-v1.0")
        form.addRow("Model:", self.model_edit)

        return tab

    # ── Audio Tab ────────────────────────────────────────────────────

    def _build_audio_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.speed_spin, self.speed_slider = self._make_slider_pair(0.5, 2.0, 0.1, 1.0)
        form.addRow("Speed:", self._h_pair(self.speed_slider, self.speed_spin))

        self.pitch_spin, self.pitch_slider = self._make_slider_pair(0.5, 2.0, 0.1, 1.0)
        form.addRow("Pitch:", self._h_pair(self.pitch_slider, self.pitch_spin))

        self.volume_spin, self.volume_slider = self._make_slider_pair(0.0, 2.0, 0.1, 1.0)
        form.addRow("Volume:", self._h_pair(self.volume_slider, self.volume_spin))

        self.device_combo = QComboBox()
        self._populate_audio_devices()
        form.addRow("Audio device:", self.device_combo)

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
        self.device_combo.addItem("System default", None)
        for dev in get_audio_devices():
            label = f"{dev['name']}  ({dev['sample_rate']} Hz, {dev['channels']}ch)"
            if dev["is_default"]:
                label += "  [DEFAULT]"
            self.device_combo.addItem(label, dev["id"])

    # ── Keyboard Tab ─────────────────────────────────────────────────

    def _build_keyboard_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.mod_combo = QComboBox()
        self.mod_combo.addItems(MODIFIER_KEYS)
        form.addRow("Modifier key:", self.mod_combo)

        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems(TRIGGER_KEYS)
        self.trigger_combo.setEditable(True)
        form.addRow("Play key:", self.trigger_combo)

        self.pause_combo = QComboBox()
        self.pause_combo.addItems(TRIGGER_KEYS)
        self.pause_combo.setEditable(True)
        form.addRow("Pause / Resume key:", self.pause_combo)

        self.stop_combo = QComboBox()
        self.stop_combo.addItems(TRIGGER_KEYS)
        self.stop_combo.setEditable(True)
        form.addRow("Stop key:", self.stop_combo)

        # Live preview label
        self.shortcut_preview = QLabel()
        self.shortcut_preview.setStyleSheet("font-style: italic; opacity: 0.7;")
        form.addRow("", self.shortcut_preview)

        # Update preview when any combo changes
        for combo in (self.mod_combo, self.trigger_combo, self.pause_combo, self.stop_combo):
            combo.currentTextChanged.connect(self._update_shortcut_preview)

        return tab

    def _update_shortcut_preview(self):
        mod = self.mod_combo.currentText().capitalize()
        play = self.trigger_combo.currentText().capitalize()
        pause = self.pause_combo.currentText().capitalize()
        stop = self.stop_combo.currentText().capitalize()
        self.shortcut_preview.setText(
            f"Play: {mod}+{play}   |   Pause: {mod}+{pause}   |   Stop: {mod}+{stop}"
        )

    # ── General Tab ──────────────────────────────────────────────────

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.debug_check = QCheckBox("Enable debug logging")
        form.addRow(self.debug_check)

        return tab

    # ──────────────────────── Config ↔ UI ────────────────────────────

    def _load_config_into_ui(self):
        v = self.config.voice
        self.engine_combo.setCurrentText(v.engine)
        self.model_edit.setText(v.model)

        a = self.config.audio
        self.speed_spin.setValue(a.speed)
        self.pitch_spin.setValue(a.pitch)
        self.volume_spin.setValue(a.volume)

        idx = self.device_combo.findData(a.device_id)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)

        k = self.config.keyboard
        self.mod_combo.setCurrentText(k.modifier_key)
        self.trigger_combo.setCurrentText(k.trigger_key)
        self.pause_combo.setCurrentText(k.pause_key)
        self.stop_combo.setCurrentText(k.stop_key)
        self._update_shortcut_preview()

        self.debug_check.setChecked(self.config.debug)

    def _read_config_from_ui(self) -> AppConfig:
        return AppConfig(
            voice=VoiceConfig(
                engine=self.engine_combo.currentText(),
                model=self.model_edit.text().strip(),
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
                modifier_key=self.mod_combo.currentText(),
                trigger_key=self.trigger_combo.currentText().strip(),
                pause_key=self.pause_combo.currentText().strip(),
                stop_key=self.stop_combo.currentText().strip(),
            ),
            debug=self.debug_check.isChecked(),
        )

    # ──────────────────────── Actions ────────────────────────────────

    def _on_apply(self):
        self.config = self._read_config_from_ui()
        save_config(self.config)

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

        self.test_btn.setText("Stop Test")
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
                self.test_btn.setText("Test Voice")
                try:
                    self.test_btn.clicked.disconnect()
                except TypeError:
                    pass
                self.test_btn.clicked.connect(self._on_test_voice)

        self._test_thread = threading.Thread(target=_run, daemon=True)
        self._test_thread.start()

    def _stop_test_voice(self):
        self._test_stop.set()
