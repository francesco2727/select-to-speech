# AI Agent Guidelines for Select-to-Speech

Welcome! If you are an AI agent working on this project, please read this guide to orient yourself and follow the established conventions.

## Project Overview

**Select-to-Speech** is a Wayland-native text-to-speech application for Linux that reads selected text aloud using a keyboard shortcut. It supports automatic language detection and uses the Kokoro ONNX offline TTS engine.

### Architecture
The project is split into two main components:
1. **Backend / Daemon (Python)**:
   - Located in the `src/select_to_speech/` directory (tests in `tests/`).
   - Built with Python 3.12+ and managed via `uv` (`uv run pytest`).
   - Uses FastAPI over a Unix Domain Socket for IPC with the GUI.
   - Responsible for hotkey listening, clipboard/OCR capture, language detection, Sherpa-ONNX (Kokoro) TTS synthesis, and audio playback.

2. **Frontend / GUI (Flutter)**:
   - Located in the `src/ui/` directory.
   - Written in Dart/Flutter (Material 3).
   - Acts as the settings interface and system tray application.

### Dependency Management
- Python dependencies are managed with `uv` (`pyproject.toml` and `uv.lock`). Never modify `.venv` manually.
- Flutter dependencies are managed with `src/ui/pubspec.yaml`.

## Mandatory Global Rules

1. **Changelog Updates**:
   Whenever you add a new feature, make significant modifications, or fix a bug, you **MUST** update `CHANGELOG.md` in the root of the project under `[Unreleased]` (or the current draft version section), categorized under `### Added`, `### Changed`, `### Fixed`, etc.

2. **Documentation**:
   Keep `README.md` and inline documentation updated if you change system requirements, setup scripts (`install.sh`, `install-local.sh`), or default configurations.

3. **Domain Skills (Load On-Demand)**:
   Detailed architectural rules and workflows are modularized into project skills under `.agents/skills/`. Load the matching skill before working on its scope:
   - **`flutter-material3`**: For any work in `src/ui/` (Material 3 conventions, `dart`/`material3` MCP servers, `analyze_files` checks, `tray_manager_patched`).
   - **`tts-audio-pipeline`**: For TTS synthesis, text normalization, neural punctuation, language detection, voice management, and audio playback/ducking (`tts_engine.py`, `voice_manager.py`, `audio_player.py`, `text_normalizer.py`, `punctuation_engine.py`, `sound_feedback.py`).
   - **`backend-daemon-api`**: For the FastAPI UDS server, Pydantic config schema, daemon lifecycle, Wayland selection/hotkeys, OCR capture, and system diagnostics (`api/server.py`, `config.py`, `main.py`, `selection_listener.py`, `keyboard_handler.py`, `screen_capture.py`, `ocr_engine.py`, `system_check.py`).
   - **`nuitka-release-packaging`**: Whenever modifying `pyproject.toml` dependencies, CLI entry points (`entrypoint.py`, `main.py`), `.github/workflows/release.yml`, or installer scripts (`install.sh`, `install-local.sh`, `uninstall.sh`).
