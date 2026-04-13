"""Settings window for select-to-speech configuration."""

import threading
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal, QMetaObject, Qt as QtConst, Q_ARG
from PySide6.QtGui import QIcon, QKeyEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from KWidgetsAddons import KPageDialog, KPageWidgetItem

from ..config import AppConfig, AudioConfig, KeyboardConfig, OllamaConfig, VoiceConfig, load_config, save_config
from .. import ollama_client
from ..i18n import _, set_language
from ..system_check import get_audio_devices
from ..tts_engine import get_available_models, get_voices_for_language

# Available languages & their sample sentences for test voice
SAMPLE_SENTENCES = {
    "ar": "هذا اختبار لإعدادات الصوت.",
    "de": "Dies ist ein Test der Spracheinstellungen.",
    "en": "This is a test of the voice settings.",
    "es": "Esta es una prueba de la configuración de voz.",
    "fr": "Ceci est un test des paramètres vocaux.",
    "hi": "यह आवाज़ सेटिंग्स का परीक्षण है।",
    "it": "Questa è una prova delle impostazioni vocali.",
    "ja": "これは音声設定のテストです。",
    "ko": "이것은 음성 설정 테스트입니다.",
    "nl": "Dit is een test van de steminstellingen.",
    "pl": "To jest test ustawień głosu.",
    "pt": "Este é um teste das configurações de voz.",
    "ru": "Это тест настроек голоса.",
    "tr": "Bu bir ses ayarları testidir.",
    "zh": "这是语音设置的测试。",
}

MODIFIER_KEYS = ["alt", "ctrl", "shift"]

_LANGUAGE_DISPLAY: dict[str, str] = {
    "ar": "العربية",
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "hi": "हिन्दी",
    "it": "Italiano",
    "ja": "日本語",
    "ko": "한국어",
    "nl": "Nederlands",
    "pl": "Polski",
    "pt": "Português",
    "ru": "Русский",
    "tr": "Türkçe",
    "zh": "中文",
}

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

    keyChanged = Signal(str)

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

    modifiersChanged = Signal(str)

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


class SettingsWindow(KPageDialog):
    """Configuration dialog with pages for voice, audio, keyboard, and general."""

    # Signal emitted from background thread to reset play button on the GUI thread
    _reset_play_btn = Signal(str)
    # Signal to update Ollama model combos from background thread (carries model list)
    _ollama_models_ready = Signal(list)

    def __init__(self, config: Optional[AppConfig] = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config or load_config()
        self._original_config = self.config.model_copy(deep=True)
        self._test_thread: Optional[threading.Thread] = None
        self._test_stop = threading.Event()
        self._page_items: list[KPageWidgetItem] = []

        # Apply the configured GUI language before building UI
        set_language(self.config.gui_language)

        self.setWindowTitle(_("Select-to-Speech — Settings"))
        self.setMinimumSize(QSize(800, 600))
        self.setFaceType(KPageDialog.FaceType.List)

        # Hide the auto-added sidebar search bar injected by KPageDialog
        from PySide6.QtWidgets import QLineEdit
        search = self.findChild(QLineEdit)
        if search:
            search.hide()
            search.setMaximumHeight(0)

        self._configure_buttons()
        self._add_pages()
        self._load_config_into_ui()

        # Connect the thread-safe signal for resetting play buttons
        self._reset_play_btn.connect(self._do_reset_play_btn)
        # Connect Ollama model list signal
        self._ollama_models_ready.connect(self._do_populate_ollama_combos)

        # Auto-fetch Ollama models in background on startup
        self._auto_fetch_ollama_models()

    # ──────────────────────── UI Construction ────────────────────────

    def _configure_buttons(self):
        btn_box = self.buttonBox()
        btn_box.setStandardButtons(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText(_("Save"))
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setIcon(QIcon.fromTheme("document-save"))
        btn_box.button(QDialogButtonBox.StandardButton.Apply).setText(_("Apply"))
        btn_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancel"))

    def _add_pages(self):
        """Add the four settings pages to the KPageDialog."""
        pages = [
            (_("Engine"),        "applications-engineering", self._scrollable_page(self._build_voice_tab())),
            (_("Audio"),         "audio-headphones",          self._scrollable_page(self._build_audio_tab())),
            (_("Shortcuts"),     "configure-shortcuts",       self._scrollable_page(self._build_keyboard_tab())),
            (_("Screen Reader"), "view-preview",              self._scrollable_page(self._build_screen_reader_tab())),
            (_("General"),       "configure",                 self._scrollable_page(self._build_general_tab())),
        ]
        # Keep Python-side references so Shiboken doesn't GC the C++ objects
        # before KPageDialog has a chance to take ownership of them.
        self._page_widgets: list[QWidget] = []
        for name, icon_name, widget in pages:
            self._page_widgets.append(widget)
            item = KPageWidgetItem(widget, name)
            item.setIcon(QIcon.fromTheme(icon_name))
            item.setHeader(name)
            self.addPage(item)
            self._page_items.append(item)

    @staticmethod
    def _scrollable_page(content: QWidget, max_width: int = 600) -> QScrollArea:
        """Wrap *content* in a scroll area with a centred, max-width container."""
        content.setMaximumWidth(max_width)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        wrapper = QWidget()
        h = QHBoxLayout(wrapper)
        h.setContentsMargins(0, 0, 0, 0)
        h.addStretch()
        h.addWidget(content)
        h.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(wrapper)

        # Ensure the scroll area triggers vertical scrollbars instead of
        # compressing content when the viewport is too short.
        def _enforce_min_height():
            wrapper.setMinimumHeight(content.sizeHint().height())
        wrapper.resizeEvent = lambda e: _enforce_min_height()

        return scroll

    # ── Voice Tab ────────────────────────────────────────────────────

    def _build_voice_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Top form: engine ──
        top_form = QFormLayout()

        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["kokoro", "piper"])
        self.engine_combo.currentTextChanged.connect(self._on_engine_changed)
        top_form.addRow(_("Engine:"), self.engine_combo)

        outer.addLayout(top_form)
        outer.addSpacing(12)

        # ── Per-language model overrides ──
        self.lang_model_combos: dict[str, QComboBox] = {}
        self._lang_model_group = QGroupBox(_("Model per language"))
        self._lang_model_form = QFormLayout(self._lang_model_group)
        self._lang_model_form.setVerticalSpacing(10)
        outer.addWidget(self._lang_model_group)
        outer.addStretch()

        # Populate will be driven by _load_config_into_ui; prime it now
        # so the tab is not empty before config is applied.
        self._populate_model_combos(self.engine_combo.currentText(), reset=False)

        return tab

    def _on_engine_changed(self, engine: str) -> None:
        """Called when the user selects a different engine — resets all model combos."""
        self._populate_model_combos(engine, reset=True)

    def _populate_model_combos(self, engine: str, reset: bool) -> None:
        """Repopulate all per-language model combos.

        When *reset* is True (engine switch) all combos reset to the first
        available voice.  When False, existing selections are preserved
        where possible (initial UI load path).
        """
        for lang, combo in self.lang_model_combos.items():
            prev = combo.currentText()
            voices = get_voices_for_language(engine, lang)
            combo.clear()
            if voices:
                combo.addItems(voices)
            else:
                combo.addItem("")
            # Enable/disable play button based on voice availability
            btn = self._lang_play_btns.get(lang)
            if btn:
                btn.setEnabled(bool(voices))
            if reset or not prev:
                combo.setCurrentIndex(0)
            else:
                idx = combo.findText(prev)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setCurrentIndex(0)

    def _rebuild_lang_model_rows(self, language_models: dict[str, str]) -> None:
        """Clear and recreate per-language rows for all supported languages."""
        # Remove all existing rows
        while self._lang_model_form.rowCount():
            self._lang_model_form.removeRow(0)
        self.lang_model_combos.clear()
        self._lang_play_btns: dict[str, QPushButton] = {}

        engine = self.engine_combo.currentText()

        # Use _LANGUAGE_DISPLAY as the canonical set, merged with any extras from config
        all_langs = sorted(set(_LANGUAGE_DISPLAY.keys()) | set(language_models.keys()))

        for lang in all_langs:
            display = _LANGUAGE_DISPLAY.get(lang, lang)
            label = f"{display} ({lang}):"

            voices = get_voices_for_language(engine, lang)

            combo = QComboBox()
            if voices:
                combo.addItems(voices)
            else:
                combo.addItem("")

            # Restore saved model for this language
            saved = language_models.get(lang, "")
            if saved:
                idx = combo.findText(saved)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.addItem(saved)
                    combo.setCurrentIndex(combo.count() - 1)

            # Play button to preview the selected voice
            play_btn = QPushButton("\u25b6")
            play_btn.setFixedSize(32, 32)
            play_btn.setToolTip(_("Play"))
            play_btn.setEnabled(bool(voices))
            play_btn.clicked.connect(lambda checked, l=lang: self._on_play_voice(l))
            self._lang_play_btns[lang] = play_btn

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            row_layout.addWidget(combo, stretch=1)
            row_layout.addWidget(play_btn)

            self._lang_model_form.addRow(label, row_widget)
            self.lang_model_combos[lang] = combo

    # ── Audio Tab ────────────────────────────────────────────────────

    def _build_audio_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.speed_spin, self.speed_slider = self._make_slider_pair(0.5, 2.0, 0.1, 1.0)
        form.addRow(_("Speed:"), self._h_pair(self.speed_slider, self.speed_spin))

        self.pitch_spin, self.pitch_slider = self._make_slider_pair(0.5, 2.0, 0.1, 1.0)
        form.addRow(_("Pitch:"), self._h_pair(self.pitch_slider, self.pitch_spin))

        self.volume_spin, self.volume_slider = self._make_slider_pair(0.0, 2.0, 0.1, 1.0)
        form.addRow(_("Volume:"), self._h_pair(self.volume_slider, self.volume_spin))

        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.device_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._populate_audio_devices()
        self.device_combo.currentIndexChanged.connect(
            lambda: self.device_combo.setToolTip(self.device_combo.currentText())
        )
        self.device_combo.setToolTip(self.device_combo.currentText())
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

        # Live preview label — use PlaceholderText color for a subtle, theme-aware look
        self.shortcut_preview = QLabel()
        self.shortcut_preview.setStyleSheet("font-style: italic;")
        placeholder_color = QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
        p = self.shortcut_preview.palette()
        p.setColor(QPalette.ColorRole.WindowText, placeholder_color)
        self.shortcut_preview.setPalette(p)
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

    # ── Screen Reader Tab ─────────────────────────────────────────────

    def _build_screen_reader_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Ollama Server section ──
        server_group = QGroupBox(_("Ollama Server"))
        server_form = QFormLayout(server_group)

        self.ollama_url_edit = QLineEdit()
        self.ollama_url_edit.setPlaceholderText("http://localhost:11434")
        server_form.addRow(_("Server URL:"), self.ollama_url_edit)

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.ollama_status_label = QLabel("")
        self.ollama_test_btn = QPushButton(_("Test Connection"))
        self.ollama_test_btn.clicked.connect(self._on_test_ollama)
        status_layout.addWidget(self.ollama_status_label, stretch=1)
        status_layout.addWidget(self.ollama_test_btn)
        server_form.addRow("", status_row)

        outer.addWidget(server_group)

        # ── Models section ──
        models_group = QGroupBox(_("Models"))
        models_form = QFormLayout(models_group)

        read_model_row = QWidget()
        read_layout = QHBoxLayout(read_model_row)
        read_layout.setContentsMargins(0, 0, 0, 0)
        self.read_model_combo = QComboBox()
        self.read_model_combo.setEditable(True)
        self.read_model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        read_layout.addWidget(self.read_model_combo, stretch=1)
        models_form.addRow(_("Read Screen model:"), read_model_row)

        describe_model_row = QWidget()
        describe_layout = QHBoxLayout(describe_model_row)
        describe_layout.setContentsMargins(0, 0, 0, 0)
        self.describe_model_combo = QComboBox()
        self.describe_model_combo.setEditable(True)
        self.describe_model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        describe_layout.addWidget(self.describe_model_combo, stretch=1)
        models_form.addRow(_("Describe Screen model:"), describe_model_row)

        refresh_btn = QPushButton(_("Refresh model list"))
        refresh_btn.setIcon(QIcon.fromTheme("view-refresh"))
        refresh_btn.clicked.connect(self._on_refresh_ollama_models)
        models_form.addRow("", refresh_btn)

        note_label = QLabel(_("To add new models, use the Ollama CLI: ollama pull <model-name>"))
        note_label.setWordWrap(True)
        note_label.setStyleSheet("font-style: italic; color: palette(mid);")
        models_form.addRow("", note_label)

        outer.addWidget(models_group)

        # ── Shortcuts section ──
        shortcuts_group = QGroupBox(_("Shortcuts"))
        shortcuts_form = QFormLayout(shortcuts_group)

        self.read_screen_mod = ModifierKeySelector()
        self.read_screen_mod.modifiersChanged.connect(lambda _: self._update_screen_shortcut_preview())
        shortcuts_form.addRow(_("Read Screen modifier:"), self.read_screen_mod)

        self.read_screen_key_capture = KeyCaptureWidget()
        self.read_screen_key_capture.keyChanged.connect(lambda _: self._update_screen_shortcut_preview())
        shortcuts_form.addRow(_("Read Screen key:"), self.read_screen_key_capture)

        self.describe_screen_mod = ModifierKeySelector()
        self.describe_screen_mod.modifiersChanged.connect(lambda _: self._update_screen_shortcut_preview())
        shortcuts_form.addRow(_("Describe Screen modifier:"), self.describe_screen_mod)

        self.describe_screen_key_capture = KeyCaptureWidget()
        self.describe_screen_key_capture.keyChanged.connect(lambda _: self._update_screen_shortcut_preview())
        shortcuts_form.addRow(_("Describe Screen key:"), self.describe_screen_key_capture)

        self.screen_shortcut_preview = QLabel()
        self.screen_shortcut_preview.setStyleSheet("font-style: italic;")
        placeholder_color = QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
        p = self.screen_shortcut_preview.palette()
        p.setColor(QPalette.ColorRole.WindowText, placeholder_color)
        self.screen_shortcut_preview.setPalette(p)
        shortcuts_form.addRow("", self.screen_shortcut_preview)

        outer.addWidget(shortcuts_group)
        outer.addStretch()

        return tab

    def _update_screen_shortcut_preview(self):
        read_mod = self.read_screen_mod.modifiers()
        read_mod_display = "+".join(m.capitalize() for m in read_mod.split("+") if m)
        read_key = _display_key(self.read_screen_key_capture.key_name()) if self.read_screen_key_capture.key_name() else "\u2014"
        desc_mod = self.describe_screen_mod.modifiers()
        desc_mod_display = "+".join(m.capitalize() for m in desc_mod.split("+") if m)
        desc_key = _display_key(self.describe_screen_key_capture.key_name()) if self.describe_screen_key_capture.key_name() else "\u2014"

        parts = []
        if read_mod_display:
            parts.append(f"{_('Read Screen:')} {read_mod_display}+{read_key}")
        else:
            parts.append(f"{_('Read Screen:')} {read_key}")
        if desc_mod_display:
            parts.append(f"{_('Describe Screen:')} {desc_mod_display}+{desc_key}")
        else:
            parts.append(f"{_('Describe Screen:')} {desc_key}")
        self.screen_shortcut_preview.setText("   |   ".join(parts))

    def _auto_fetch_ollama_models(self):
        """Fetch Ollama models in a background thread on settings open."""
        url = self.ollama_url_edit.text().strip() or "http://localhost:11434"

        def _run():
            models = ollama_client.list_models(url)
            if models:
                self._ollama_models_ready.emit(models)

        threading.Thread(target=_run, daemon=True).start()

    def _do_populate_ollama_combos(self, models: list):
        """Populate model combo boxes on the GUI thread (called via signal)."""
        for combo in (self.read_model_combo, self.describe_model_combo):
            prev = combo.currentText()
            combo.clear()
            combo.addItems(models)
            if prev:
                idx = combo.findText(prev)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

    def _on_test_ollama(self):
        url = self.ollama_url_edit.text().strip() or "http://localhost:11434"
        self.ollama_test_btn.setEnabled(False)
        self.ollama_status_label.setText(_("Connecting..."))

        def _run():
            ok = ollama_client.check_server(url)
            models = ollama_client.list_models(url) if ok else []
            count = len(models)
            QMetaObject.invokeMethod(
                self.ollama_status_label,
                "setText",
                QtConst.ConnectionType.QueuedConnection,
                Q_ARG(str, _("Connected") + f" ({count} " + _("models") + ")" if ok else _("Not connected")),
            )
            QMetaObject.invokeMethod(
                self.ollama_test_btn,
                "setEnabled",
                QtConst.ConnectionType.QueuedConnection,
                Q_ARG(bool, True),
            )
            if models:
                self._ollama_models_ready.emit(models)

        threading.Thread(target=_run, daemon=True).start()

    def _on_refresh_ollama_models(self):
        url = self.ollama_url_edit.text().strip() or "http://localhost:11434"

        def _run():
            models = ollama_client.list_models(url)
            if models:
                self._ollama_models_ready.emit(models)

        threading.Thread(target=_run, daemon=True).start()

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

        # Block engine signal so _on_engine_changed doesn't fire during load
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentText(v.engine)
        self.engine_combo.blockSignals(False)

        # Build per-language rows first (needs language_models keys)
        self._rebuild_lang_model_rows(v.language_models)

        # Populate model lists without resetting (preserve saved selections)
        self._populate_model_combos(v.engine, reset=False)

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

        # Ollama / Screen Reader
        o = self.config.ollama
        self.ollama_url_edit.setText(o.server_url)
        self.read_model_combo.setCurrentText(o.read_screen_model)
        self.describe_model_combo.setCurrentText(o.describe_screen_model)
        self.read_screen_mod.set_modifiers(o.read_screen_modifier)
        self.read_screen_key_capture.set_key(o.read_screen_key)
        self.describe_screen_mod.set_modifiers(o.describe_screen_modifier)
        self.describe_screen_key_capture.set_key(o.describe_screen_key)
        self._update_screen_shortcut_preview()

        self.debug_check.setChecked(self.config.debug)

        lang_idx = self.lang_combo.findData(self.config.gui_language)
        if lang_idx >= 0:
            self.lang_combo.setCurrentIndex(lang_idx)

    def _read_config_from_ui(self) -> AppConfig:
        # Keep existing default model as internal fallback
        model_text = self.config.voice.model

        # Collect per-language voice selections (always persist all languages)
        lang_models: dict[str, str] = {}
        for lang, combo in self.lang_model_combos.items():
            selected = combo.currentText().strip()
            lang_models[lang] = selected

        return AppConfig(
            voice=VoiceConfig(
                engine=self.engine_combo.currentText(),
                model=model_text,
                language=self.config.voice.language,
                language_models=lang_models,
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
            ollama=OllamaConfig(
                server_url=self.ollama_url_edit.text().strip() or "http://localhost:11434",
                read_screen_model=self.read_model_combo.currentText().strip() or "llava",
                describe_screen_model=self.describe_model_combo.currentText().strip() or "llava",
                read_screen_key=self.read_screen_key_capture.key_name(),
                describe_screen_key=self.describe_screen_key_capture.key_name(),
                read_screen_modifier=self.read_screen_mod.modifiers(),
                describe_screen_modifier=self.describe_screen_mod.modifiers(),
            ),
            debug=self.debug_check.isChecked(),
            gui_language=self.lang_combo.currentData() or "auto",
        )

    # ──────────────────────── Actions ────────────────────────────────

    def accept(self):
        """Save settings then close (mapped to the OK/Save button)."""
        self._on_apply()
        super().accept()

    def reject(self):
        """Revert to the config that was active when the dialog opened."""
        save_config(self._original_config)
        set_language(self._original_config.gui_language)
        super().reject()

    def _on_apply(self):
        self.config = self._read_config_from_ui()
        save_config(self.config)
        set_language(self.config.gui_language)
        # Rebuild the entire UI so translations take effect
        self._rebuild_ui()

    def _rebuild_ui(self):
        """Remove and re-add all pages so translated labels refresh."""
        self.setWindowTitle(_("Select-to-Speech — Settings"))

        # Remove existing pages
        for item in self._page_items:
            self.removePage(item)
        self._page_items = []

        # Update button labels for the new language
        btn_box = self.buttonBox()
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText(_("Save"))
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setIcon(QIcon.fromTheme("document-save"))
        btn_box.button(QDialogButtonBox.StandardButton.Apply).setText(_("Apply"))
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancel"))

        # Re-add pages with fresh translations
        self._add_pages()
        self._load_config_into_ui()

        # Reconnect signals after rebuild
        for sig, slot in (
            (self._reset_play_btn, self._do_reset_play_btn),
            (self._ollama_models_ready, self._do_populate_ollama_combos),
        ):
            try:
                sig.disconnect()
            except TypeError:
                pass
            sig.connect(slot)

        # Re-fetch Ollama models for the new combo widgets
        self._auto_fetch_ollama_models()

    def _on_play_voice(self, language: str):
        """Synthesise and play a short sample for the selected voice in *language*."""
        # Stop any running test
        if self._test_thread and self._test_thread.is_alive():
            self._test_stop.set()
            self._test_thread.join(timeout=2)

        self._test_stop.clear()
        cfg = self._read_config_from_ui()
        sample = SAMPLE_SENTENCES.get(language, SAMPLE_SENTENCES["en"])

        # Switch play button to stop icon
        btn = self._lang_play_btns.get(language)
        if btn:
            btn.setText("\u25a0")
            try:
                btn.clicked.disconnect()
            except TypeError:
                pass
            btn.clicked.connect(lambda: self._stop_test_voice(language))

        def _run():
            try:
                from ..tts_engine import get_tts_engine
                from ..audio_player import AudioPlayer

                engine = get_tts_engine(cfg.voice)
                result = engine.synthesize(sample, language=language, speed=cfg.audio.speed, volume=cfg.audio.volume)
                if result is None or self._test_stop.is_set():
                    return
                audio_bytes, sample_rate = result
                player = AudioPlayer(cfg.audio.device_id)
                player.play(audio_bytes, sample_rate, pitch=cfg.audio.pitch)
            except Exception:
                pass
            finally:
                # Emit signal to reset button on the GUI thread
                self._reset_play_btn.emit(language)

        self._test_thread = threading.Thread(target=_run, daemon=True)
        self._test_thread.start()

    def _do_reset_play_btn(self, language: str):
        """Reset the play button back to ▶ — runs on the GUI thread via signal."""
        btn = self._lang_play_btns.get(language)
        if btn:
            btn.setText("\u25b6")
            try:
                btn.clicked.disconnect()
            except TypeError:
                pass
            btn.clicked.connect(lambda checked, l=language: self._on_play_voice(l))

    def _stop_test_voice(self, language: str = ""):
        self._test_stop.set()
