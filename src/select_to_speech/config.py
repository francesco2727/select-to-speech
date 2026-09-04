"""Configuration management for select-to-speech"""

import os
from pathlib import Path
from typing import Optional

import platformdirs
import yaml
from pydantic import BaseModel, Field


class AudioConfig(BaseModel):
    """Audio playback configuration"""

    device_id: Optional[int] = Field(None, description="Audio device ID (None for default)")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    pitch: float = Field(1.0, ge=0.5, le=2.0, description="Speech pitch multiplier")
    volume: float = Field(1.0, ge=0.0, le=2.0, description="Audio volume multiplier")
    sound_feedback: bool = Field(True, description="Enable audio earcon feedback tones")
    ducking: bool = Field(True, description="Lower background audio while playing")


class VoiceConfig(BaseModel):
    """Voice configuration"""

    engine: str = Field("kokoro", description="TTS engine to use (always 'kokoro')")
    model: str = Field("kokoro-v1.0", description="Voice model name")
    language: str = Field("it", description="Language code")
    language_models: dict[str, str] = Field(
        default_factory=lambda: {
            "ar": "",
            "de": "",
            "en": "af_heart",
            "es": "",
            "fr": "",
            "hi": "",
            "it": "if_sara",
            "ja": "",
            "ko": "",
            "nl": "",
            "pl": "",
            "pt": "",
            "ru": "",
            "tr": "",
            "zh": "",
        },
        description="Map of language codes to model names"
    )


class KeyboardConfig(BaseModel):
    """Keyboard shortcut configuration"""

    modifier_key: str = Field("alt", description="Modifier key: 'alt', 'ctrl', 'shift'")
    trigger_key: str = Field("esc", description="Trigger key when combined with modifier")
    pause_key: str = Field("w", description="Pause/Resume toggle key when combined with modifier")
    stop_key: str = Field("s", description="Explicit stop key when combined with modifier")
    ocr_key: str = Field("r", description="OCR Screen Capture key when combined with modifier")


class OcrConfig(BaseModel):
    """OCR configuration"""

    language: str = Field("ita+eng", description="Language code(s) for Tesseract OCR (e.g., 'ita+eng', 'eng')")


class AppConfig(BaseModel):
    """Main application configuration"""

    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    keyboard: KeyboardConfig = Field(default_factory=KeyboardConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    debug: bool = Field(False, description="Enable debug logging")
    gui_language: str = Field("auto", description="GUI language: 'auto', 'en', 'it', 'es', 'fr'")
    theme_mode: str = Field("system", description="Theme mode: 'dark', 'light', 'system'")

    class Config:
        """Pydantic config"""

        yaml_loader = yaml.SafeLoader


def get_config_dir() -> Path:
    """Get configuration directory path"""
    config_dir = Path(platformdirs.user_config_dir("select-to-speech"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_data_dir() -> Path:
    """Get data/cache directory path"""
    data_dir = Path(platformdirs.user_data_dir("select-to-speech"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_state_dir() -> Path:
    """Get runtime state directory path (e.g. sockets, runtime flags)"""
    state_dir = Path(platformdirs.user_state_dir("select-to-speech"))
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def get_log_dir() -> Path:
    """Get log directory path"""
    log_dir = Path(platformdirs.user_log_dir("select-to-speech"))
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration from YAML file or use defaults"""
    if config_path is None:
        config_path = get_config_dir() / "config.yaml"

    if config_path.exists():
        with open(config_path) as f:
            config_dict = yaml.safe_load(f) or {}
        return AppConfig(**config_dict)

    return AppConfig()


def save_config(config: AppConfig, config_path: Optional[Path] = None) -> None:
    """Save configuration to YAML file"""
    if config_path is None:
        config_path = get_config_dir() / "config.yaml"

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False)
