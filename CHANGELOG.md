# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.2.1] - Unreleased

### Added
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
