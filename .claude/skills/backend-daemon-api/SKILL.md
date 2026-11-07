---
name: backend-daemon-api
description: Load this skill when modifying the FastAPI IPC daemon (api/server.py), application configuration schema (config.py), core orchestration (SelectToSpeechApp in main.py), desktop integration (selection_listener.py, keyboard_handler.py, screen_capture.py, ocr_engine.py), or system diagnostics (system_check.py).
---

# Backend Daemon, FastAPI IPC, Configuration, and Desktop Integration

Scope: FastAPI server over Unix Domain Socket (`src/select_to_speech/api/server.py`), Pydantic configuration (`src/select_to_speech/config.py`), core lifecycle (`SelectToSpeechApp` in `src/select_to_speech/main.py`), Wayland/X11 selection & hotkeys (`selection_listener.py`, `keyboard_handler.py`), OCR capture (`screen_capture.py`, `ocr_engine.py`), and diagnostics (`system_check.py`).

## 1. FastAPI Daemon & Unix Domain Socket IPC (`api/server.py`)

- **Socket Path**: `~/.local/state/select-to-speech/ipc.sock`.
- **Single-Instance Guard**: `run_server()` probes `is_server_running(socket_path)` (`GET /status`) before binding; if an instance is already responsive, it exits cleanly (`return 0`), otherwise it unlinks any stale socket file.
- **Core Endpoints**:
  - `GET /status`: health & playback state (`{"status": "ok", "playing": bool}`).
  - `POST /speak`, `POST /stop`, `POST /pause`, `POST /ocr_capture`: playback and OCR actions.
  - `GET /config`, `POST /config`: read/write `AppConfig` and trigger live hot-reload via `sts_app.reload_config(config)`.
  - `GET /audio_devices`, `GET /hardware`, `GET /voices`, `GET /ocr_languages`, `GET /available_models`, `GET /model_installed`.
  - `POST /download_model`, `GET /download_status`, `POST /download_punctuation`, `GET /punctuation_status`: background model download state machines.
- **UI Contract**: Whenever you change or add an endpoint or payload field in `api/server.py`, check if `src/ui/lib/main.dart` consumes it (load the `flutter-material3` skill if modifying `src/ui/`).

## 2. Adding or Modifying Configuration Options (`config.py`)

Configuration is persisted at `~/.config/select-to-speech/config.yaml` and validated via Pydantic (`AppConfig`, `VoiceConfig`, `AudioConfig`, `KeyboardConfig`, `OcrConfig`).

When introducing or renaming a setting, follow this checklist:
1. **Schema**: Add the field with sensible defaults and validation constraints (`Field(...)`) in `src/select_to_speech/config.py`.
2. **Migration**: If renaming or replacing legacy values, update `_migrate_config_dict()` in `config.py` so existing user `config.yaml` files load cleanly.
3. **Hot-Reload**: Ensure `SelectToSpeechApp.reload_config()` in `src/select_to_speech/main.py` applies the updated setting to live components (`tts_engine`, `audio_player`, `ducker`, `punctuation_engine`, `keyboard_handler`) without requiring a daemon restart.
4. **Tests**: Add or update tests in `tests/test_config.py` and `tests/test_server.py`, then run `uv run pytest`.

## 3. Desktop Integration & System Diagnostics

- **Selection & Clipboard (`selection_listener.py`)**:
  - Uses `wl-paste` on Wayland (with X11/primary selection fallbacks) to monitor text selection without stealing focus.
- **Global Shortcuts (`keyboard_handler.py`)**:
  - Combines a modifier (`alt`, `ctrl`, `shift`) with action keys (`trigger_key`, `pause_key`, `stop_key`, `ocr_key`). Debounced in `main.py` via `_shortcut_lock`.
- **Screen Capture & OCR (`screen_capture.py`, `ocr_engine.py`)**:
  - Captures screen regions via desktop portals / Wayland screenshot utilities and extracts text using Tesseract (`ocr.language`, e.g., `ita+eng`).
- **System Check (`system_check.py`)**:
  - Provides `main_check()`, `main_audio_devices()`, `get_audio_devices()`, and `get_hardware_info()`. If you add a new external binary requirement (e.g., a Wayland tool or library), register it in `system_check.py` and update `README.md`.
