# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.2.2] - Unreleased

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
