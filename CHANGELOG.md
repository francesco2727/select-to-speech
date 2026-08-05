# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **UI Settings Sidebar**: Renamed the existing "Shortcuts" tab to "OCR" and created a new dedicated "Shortcuts" tab to manage all keyboard shortcuts, updating the sidebar layout to support 5 tabs instead of 4.

## [v0.2.3] - 2026-07-26

### Added
- **Nuitka Backend Compilation**: Added a new CI job (`build-backend`) in `.github/workflows/release.yml` to compile the Python backend and entry points (`select-to-speech`, `select-to-speech-check`, `select-to-speech-audio`, `select-to-speech-download`) into a standalone binary tarball (`select-to-speech-backend-linux.tar.gz`).
- **Binary-Only Installation**: Created a new `install.sh` designed for end-users that automatically downloads pre-compiled backend and GUI tarballs from GitHub Releases, completely removing the dependency on `uv`, `pip`, or a local Python toolchain.
- **Multilingual System Check (`select-to-speech-check`)**: Added full localization (`en`, `it`, `fr`, `es`) and automatic system language detection (`LC_ALL`, `LANG`, or `locale`) for dependency check descriptions and installation instructions, with English (`en`) as the fallback default and an explicit CLI override option (`--lang en|it|fr|es`).
- **Language-Adaptive Currency Reading**: Added intelligent text normalization (`preprocess_text`) across all Kokoro supported languages (`en`, `it`, `es`, `fr`, `de`, `pt`, `ja`, `zh`, `hi`, `ko`) for currency symbols (`$`, `€`, `£`, `¥`, `₹`, `₽`, `₩`, `¢`, `฿`, `₺`, `₴`), automatically converting prefix notation (`$100`, `$100 milioni`) and suffix/standalone symbols (`50€`) into naturally spoken words (`100 dollari`, `100 milioni dollari`, `50 euro`, etc.) adapted to the detected language.
- **OCR System Checks**: Added diagnostic verification of OCR dependencies (`tesseract` CLI with language packs `tesseract-data-ita` / `tesseract-data-eng`, plus screen capture tools `spectacle` and `slurp` + `grim`) to `select-to-speech-check` (`system_check.py`), reporting installed OCR capabilities and precise installation instructions (`sudo pacman -S tesseract tesseract-data-ita tesseract-data-eng spectacle slurp grim`) when needed.

### Changed
- **Local Installation**: Refactored `install-local.sh` to strictly handle local installations from source code (requiring local `uv` and `flutter`), completely removing fallback remote download logic.

### Fixed
- **Nuitka Backend Compilation**: Fixed a critical `ImportError` on backend startup caused by compiling `main.py` directly instead of treating it as a module (`select_to_speech.main`), which broke relative imports.
- **FastAPI / Uvicorn Missing Modules**: Added explicit Nuitka `--include-package` flags for `uvicorn`, `fastapi`, and `pydantic` to prevent dynamic import errors when starting the backend server.
- **Installation Script (`install.sh`)**: Added `$HOME/.cargo/bin` alongside `$HOME/.local/bin` to `$PATH` when automatically installing `uv` to ensure seamless detection across different Linux configurations.
- **Kokoro ONNX Token Truncation**: Fixed `IndexError: index 510 is out of bounds for axis 0 with size 510` in `kokoro_onnx` when phoneme sequences exceed model capacity by intercepting and truncating tokenized sequences to 509 tokens and chunking long text in `synthesize()`.
- **Audio Stream Concurrency & Race Conditions**: Added `_play_lock` around `play()` and `play_stream()` in `AudioPlayer` with clean state reset (`_stop_requested = False`) upon lock acquisition, and guarded `stream.write()` with `_stream_lock` to prevent crashes, freezes, or blocked playback when rapid hotkey presses interrupt ongoing audio.
- **Screen Capture Timeouts & Concurrency**: Added timeouts (`30s` for `spectacle`/`slurp`, `10s` for `grim`) and concurrency checks in `_on_ocr_pressed` to prevent deadlocks and infinite hangs when screen capture tools fail or cancel.

## [v0.2.2] - 2026-07-12

### Added
- **Audio Feedback (Earcons)**: Added synthetic, non-blocking audio feedback tones (`sound_feedback` option in `config.py`) for text selection start, OCR region selection activation, OCR success, and audio error alerts.
- **Screen OCR & Read**: Added support for capturing a rectangular region of the screen (`Alt + r` default shortcut) using KDE Spectacle (`spectacle -r -b -n`) and reading extracted text via CLI `tesseract` OCR.
- **OCR Shortcut Configuration**: Added configurable OCR hotkey setting (`ocr_key`) in `config.py` and editable directly from the Flutter GUI Keyboard Shortcuts tab.

### Changed
- **Screen OCR Capture Tool**: Configured KDE Spectacle with `-k` (`--release-capture`) for immediate region capture on click-and-release as the primary capture tool on KDE Wayland systems, with `slurp` + `grim` as fallback for wlroots environments.
- **Auto-Save Settings**: Removed the manual "Save Settings" button. Settings are now saved automatically and silently in the background when changed.

### Fixed
- **TTS Chunking Crash**: Fixed an `IndexError: index 510 is out of bounds` crash in Kokoro TTS caused by unpunctuated OCR segments exceeding 510 tokens by adding automatic word-level fallback chunking.
- **OCR Language Handling**: Filtered out `osd` from Tesseract available languages and added warning logs when requested language packs are missing.


## [v0.2.1] - 2026-06-21

### Added
- **Quick Install**: Restructured `install.sh` to support remote installation via `curl`, automatically downloading pre-compiled releases and avoiding local build steps for end-users.
- **Light Theme**: Implemented a new light theme for the Flutter GUI settings window.
- **Theme Selection Config**: Added `theme_mode` configuration option in `config.py` supporting `dark`, `light`, and `system` modes.

### Fixed / Chore
- **UI Code Cleanup**: Resolved all Flutter static analysis warnings and deprecations in `main.dart` and `widget_test.dart` to maintain a clean, warning-free UI codebase.

## [v0.2.0] - 2026-06-14

### Added
- **Single Instance Behavior**: Implemented single instance behavior using `GApplication` on Linux to prevent multiple instances of the app from running concurrently.
- **Background Mode**: Added support for running the GUI in the background upon closing the window.
- **UI Layout Redesign**: Re-architected the GUI settings panel with a modern left sidebar, centered layout, and relocated the save button to the bottom-right corner.
- **SVG Tray Icon**: Switched from traditional tray icons to a cleaner SVG tray icon.

### Changed / Refactored
- **App Indicator**: Migrated from deprecated `app_indicator_new` to `g_object_new` for better Linux integration.
- **Build System**: Updated `install.sh` to compile the Flutter GUI during installation.

## [v0.1.0] - 2026-06-12

### Added
- **GUI Migration**: Fully migrated the settings GUI from Python to Flutter.
- **FastAPI Backend**: Re-implemented the daemon backend using FastAPI.
- **Internationalization (i18n)**: Implemented full GUI internationalization in Flutter (with auto-compilation of translation files on install/runtime).
- **Audio Improvements**: Voices now read math symbols and dots in URLs/filenames. Added a clipboard fallback mechanism to read the last selected clipboard text.
- **CI/CD Workflow**: Added GitHub Actions workflow to build and package Linux GUI releases, supporting automated asset uploads.
