# AI Agent Guidelines for Select-to-Speech

Welcome! If you are an AI agent working on this project, please read this guide to orient yourself and follow the established conventions.

## Project Overview

**Select-to-Speech** is a Wayland-native text-to-speech application for Linux that reads selected text aloud using a keyboard shortcut. It supports automatic language detection and uses the Kokoro ONNX offline TTS engine.

### Architecture
The project is split into two main components:
1. **Backend / Daemon (Python)**:
   - Located in the `src/select_to_speech/` directory.
   - Built with Python 3.14+ and managed via `uv`.
   - Uses FastAPI for the internal server/daemon logic.
   - Responsible for hotkey listening, clipboard monitoring (via Wayland), language detection, and audio playback.

2. **Frontend / GUI (Flutter)**:
   - Located in the `src/ui/` directory.
   - Written in Dart/Flutter.
   - Acts as the settings interface and system tray application.
   - Communicates with the backend daemon.

### Dependency Management
- Python dependencies are managed with `uv`. (See `pyproject.toml` and `uv.lock` in the root).
- Flutter dependencies are managed with `pubspec.yaml` inside `src/ui/`.

## Mandatory Rules for AI Agents

1. **Changelog Updates**: 
   Whenever you add a new feature, make significant modifications, or fix a bug in the code, you **MUST** update the `CHANGELOG.md` file located in the root of the project.
   - Add your changes under the `[Unreleased]` or the current draft version section (e.g., `[v0.2.2] - Unreleased`).
   - Follow the established format (categorizing under `### Added`, `### Changed`, `### Fixed`, etc.).

2. **Backend Changes**:
   Ensure compatibility with FastAPI and `uv`. Avoid modifying `.venv` manually.

3. **Frontend Changes**:
   Respect the existing Flutter UI architecture and run static analysis checks where possible to maintain clean code.

4. **Documentation**:
   Keep the `README.md` and inline documentation updated if you change system requirements, setup scripts (`install.sh`), or default configurations.

5. **Flutter Dependencies (tray_manager_patched)**:
   The UI uses a custom patched version of `tray_manager` located in `src/ui/tray_manager_patched`. This patch is necessary to resolve C++ deprecation warnings on Linux (using `g_object_new` instead of `app_indicator_new`) and support SVG icons. It is overridden via `src/ui/pubspec_overrides.yaml`. Do not remove this override, and ensure the `lib` folder inside `tray_manager_patched` is intact for successful Flutter compilation.

6. **Nuitka Compilation Readiness**:
   Whenever you make substantial modifications to the Python backend, add/remove dependencies in `pyproject.toml`, or change CLI entry points, you **MUST** verify that the code remains ready for standalone `--onefile` compilation with Nuitka (configured in `.github/workflows/release.yml`):
   - Keep `NUITKA_FLAGS` in `.github/workflows/release.yml` synchronized with `pyproject.toml` dependencies.
   - Use `--include-package` only for actual packages (directories with `__init__.py` or namespace packages) and `--include-module` for single-file `.py` or C-extension `.so` modules.
   - Include `--include-package-data` for any new dependency that loads non-code assets at runtime.
   - Catch `(ImportError, OSError)` when importing optional dependencies that load system C shared libraries via `ctypes`/`cffi` at import time (e.g., `pulsectl`, `pyaudio`), since compiled Nuitka binaries always bundle the Python wrapper even if the host C library is missing.
   - Keep the multi-call CLI dispatcher in `src/select_to_speech/main.py` and `run_main.py` (in `.github/workflows/release.yml`) aligned.
