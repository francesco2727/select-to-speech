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
