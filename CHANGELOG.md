# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Windows OCR & Tesseract Auto-detection**: Added automatic discovery of Tesseract executable paths on Windows (PATH, `C:\Program Files\Tesseract-OCR\tesseract.exe`, `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`, `%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe`) and updated CLI/error guidance for `winget install UB-Mannheim.TesseractOCR`.
- **Windows Screen Capture Support**: Implemented Windows screen capture using Windows Snipping Tool / `ms-screenclip:` with automatic clipboard retrieval and Tkinter overlay/Pillow fallback, preserving existing Linux Wayland Spectacle and `slurp`+`grim` workflows.
- **Cross-Platform System Check**: Updated `system_check.py` to recognize Windows platform environments, validating Tesseract OCR, Snipping Tool, and providing appropriate Windows installation recommendations.
- **Flutter Windows Platform & Runner Scaffolding**: Added complete Win32 C++ Windows runner files (`CMakeLists.txt`, `runner/main.cpp`, `runner/flutter_window.cpp`, `runner/flutter_window.h`, `runner/win32_window.cpp`, `runner/win32_window.h`, `runner/utils.cpp`, `runner/utils.h`, `runner/resource.h`, `runner/runner.exe.manifest`, `runner/Runner.rc`).
- **Win32 Single-Instance Mutex**: Implemented single-instance enforcement in `windows/runner/main.cpp` using Win32 Named Mutex (`CreateMutexW`). If another instance exists, it brings the existing window to the foreground and exits.
- **Hide-on-Close Window Management**: Implemented `WM_CLOSE` handling in `flutter_window.cpp` to hide the window to the system tray instead of exiting the application.
- **Windows Tray & Application Icon**: Generated multi-resolution Windows ICO asset `tray_icon.ico` and `runner/resources/app_icon.ico`.
- **Dynamic Log Path & Backend Discovery for Windows**: Enhanced Flutter UI in `main.dart` to discover backend executables across Windows locations (`%LOCALAPPDATA%`, `venv/Scripts`, `.venv/Scripts`, `bin`) and dynamically format log path hints in the general settings view (`%LOCALAPPDATA%\select-to-speech\log\app.log` vs `~/.local/state/select-to-speech/app.log`).
- **Windows Selection Listener**: Implemented `WindowsSelectionListener` using `pynput` keystroke simulation (`Ctrl+C`) with clipboard backup/restore and Win32 ctypes fallback to read selections on Windows. Added `get_selection_listener` factory for transparent platform resolution.
- **Windows Audio Ducking**: Implemented `WindowsAudioDucker` using `pycaw` (Windows Core Audio APIs) with automatic COM lifecycle management (`ole32.CoInitialize`/`CoUninitialize`) and session-specific volume restoration.
- **Cross-Platform Audio Device Scanning**: Refactored `AudioPlayer._find_output_devices` to dynamically detect and prioritize default and connected audio endpoints on both Linux and Windows.
- **Cross-Platform Directory Abstraction**: Integrated `platformdirs` across backend configuration, data, state, and log directory lookups (`get_config_dir`, `get_data_dir`, `get_state_dir`, `get_log_dir`).
- **Dual IPC Transport**: Added support for dual IPC communication with TCP (`127.0.0.1:28374`) on Windows and Unix Domain Sockets (`ipc.sock`) on Linux/macOS.
- **Windows Local Installer & Batch Launchers**: Added `install-local.ps1` PowerShell installation script (equivalent to `install-local.sh` on Linux) with automatic `uv` setup, virtual environment sync, Kokoro model downloads, Flutter Windows release compilation, Start Menu shortcut creation, and optional Windows Startup configuration. Added `bin/select-to-speech-gui.bat` and `bin/select-to-speech-daemon.bat` launcher scripts.
- **Frontend Cross-Platform Client & Discovery**: Abstracted HTTP/IPC client instantiation (`createApiClient()`, `getBackendBaseUrl()`) and expanded backend executable discovery in Flutter for Windows binaries (`.exe`, `%LOCALAPPDATA%`, and Python `.venv/Scripts`).

### Changed
- **Cross-Platform Event Loop Waiting**: Replaced `signal.pause()` with `threading.Event().wait()` in `SelectToSpeechApp.run()` for cross-platform signal handling and process control.
- **Cross-Platform OCR Temporary Path**: Replaced hardcoded `/tmp` path with `tempfile.gettempdir()` for OCR image captures.
- **Conditional Linux Dependencies**: Made `pulsectl` conditional on `sys_platform == 'linux'` in `pyproject.toml` and guarded its import in `audio_player.py` for safe execution on Windows.

### Fixed
- **Windows Keyboard Hook & Synthetic Keystrokes**: Released physical modifier keys (Alt, Shift, Win) prior to injecting synthetic `Ctrl+C` in `WindowsSelectionListener` to prevent modifier collisions (e.g. `Ctrl+Alt+C`) on global hotkey invocation (`Alt+Esc`).
- **Windows Clipboard Concurrency & Sequence Detection**: Integrated `user32.GetClipboardSequenceNumber()` polling to safely verify clipboard updates by active applications without wiping non-text clipboard history or causing clipboard sharing race conditions.
- **Windows COM Multithreaded Apartment in Audio Ducker**: Switched `WindowsAudioDucker` to `CoInitializeEx(COINIT_MULTITHREADED)` to avoid COM apartment mismatch (`RPC_E_CHANGED_MODE`) and removed per-action uninitialization that caused COM proxy invalidation.
- **Win32 Clipboard Memory Leak**: Fixed handle leak in `_set_clipboard_win32` by invoking `GlobalFree` when `SetClipboardData` returns `NULL`.
- **Windows Screen Capture DPI Scaling & Multi-Monitor**: Enabled Per-Monitor DPI Awareness (`SetProcessDpiAwareness`) and added `all_screens=True` in PIL `ImageGrab.grab()` for high-DPI and multi-display setups.
- **Flutter Windows Tray Icon Resolution**: Resolved absolute filesystem path to `tray_icon.ico` within `data/flutter_assets/images/tray_icon.ico` for `trayManager.setIcon()` on Windows.
- **Console Signal & Control Event Handling on Windows**: Added Windows Console Control Handler (`SetConsoleCtrlHandler`) in both `main.py` and `server.py` for graceful daemon shutdown during console close / logoff events.
- **Extended Windows Tesseract Discovery**: Added Scoop (`~\scoop\shims\tesseract.exe`) and Chocolatey (`C:\ProgramData\chocolatey\bin\tesseract.exe`) search paths in `ocr_engine.py`.
- **UTF-8 Console Encoding in Batch Launchers**: Added `chcp 65001 >nul` to `select-to-speech-daemon.bat` and `select-to-speech-gui.bat` to prevent character encoding issues with Unicode terminal output.
- **Flutter Windows Window Title**: Corrected window title from generic `"ui"` to `"Select to Speech"` in `src/ui/windows/runner/main.cpp`.

## [v0.3.2] - 2026-08-29

### Added
- **Dynamic Kokoro Model Reloading**: Added dynamic runtime reloading of Kokoro TTS models when configuration changes without requiring an application restart. Thread-safe updates deallocate previous ONNX sessions and initialize the new model lazily on demand.
- **Kokoro Model Pre-warming (Warmup)**: Added background model pre-warming on daemon startup that pre-allocates ONNX runtime execution buffers, reducing cold-start first-byte synthesis latency from ~1.5s down to sub-100ms.
- **Quantized Kokoro Models**: Integrated support for FP16 (~170MB) and INT8 (~89MB) quantized Kokoro models, offering significant disk space and RAM savings with nearly indistinguishable audio quality.
- **Dynamic Model Selection**: The UI now fetches available models dynamically from the backend and allows seamless switching between them.
- **Dynamic Language Filtering**: The language selection dropdown now dynamically filters to display only the languages supported by the currently selected voice model.

### Changed
- **Asynchronous Audio Ducking**: Refactored `AudioDucker` to lower and restore background volumes in dedicated non-blocking threads, eliminating a 20–40ms latency stall on audio playback start.
- **PortAudio Device Caching**: Cached output audio devices to avoid repeated PortAudio descriptor scans on every playback request.
- **Persistent Selection Listener Executor**: Replaced per-call ThreadPoolExecutor lifecycle with a reusable thread pool for Wayland and X11 clipboard queries.
- **Deduplicated Text Sanitization**: Optimized TTS text chunking to avoid redundant preprocessing passes.
- **Voice Model Dropdown & Dynamic Download**: Replaced the free-form text input for **Voice Model** in the settings UI with a dropdown selector (currently featuring `Kokoro v1.0 (82M)`). Renamed the download button from "Re-download" to "Download" across all languages, and configured it to be visible only when the model files are not installed locally or while a download is actively in progress.
- **Model Display Labels**: Standardized the formatting of model display names in the UI dropdown to consistently include precision and approximate download size (`Kokoro v1.0 (FP32, ~340 MB)`, `Kokoro v1.0 (FP16, ~175 MB)`, `Kokoro v1.0 (INT8, ~114 MB)`).
- **Backend Model Status API**: Added `/model_installed` endpoint to query whether model files are present on the system.
- **SVG Icon & Desktop Launcher Integration**: Adjusted the `viewBox` in `select_to_speech_tray_icon.svg` to tightly frame the graphic (removing large transparent margins) and ensured proper icon path resolution in the `.desktop` file and system icon directories, preventing fallback placeholder icons in the launcher and taskbar.
- **Nuitka Packaging & CI System Dependencies**: Updated and completed Nuitka include flags for packages and package data (`lingua`, `pedalboard`, `soundfile`, `pyaudio`, `pynput`, `emoji`, `requests`, `certifi`, `yaml`) and ensured required CI system dependencies are present.

### Fixed
- **CI Build Configuration & Check Entry Point**: Fixed the Flutter build configuration and resolved the `select-to-speech-check` CLI entry point execution in CI workflows.

## [v0.3.1] - 2026-08-13

### Fixed
- **Precompiled Release Audio Ducking**: Included `pulsectl` package in the Nuitka build process to fix audio ducking silently failing in the precompiled standalone backend.
- **Settings UI Startup Timeout**: Increased the UI's retry count and timeout logic when fetching configuration on the very first launch. This prevents an empty settings page error caused by the longer startup extraction time of the precompiled Nuitka backend.

## [v0.3.0] - 2026-08-12

### Added
- **Emoji Text-to-Speech**: Added the ability for the TTS engine to naturally read emojis. Emojis are now automatically translated into text in the user's selected language (e.g., "😊" -> "faccina sorridente" in Italian) before synthesis, using the `emoji` package.
- **Audio Ducking**: Added an audio ducking feature (with UI toggle) that automatically lowers the volume of other playing applications (like browsers or music players) while the text-to-speech voice is active, restoring their original volume when synthesis finishes.

### Changed
- **Unified Application Icon**: Configured the `.desktop` file to use the custom SVG logo (`select-to-speech.svg`) instead of the generic system `audio-headphones` icon.
- **Window Icon Fix**: Added `StartupWMClass=com.example.ui` to the `.desktop` file to ensure Wayland and X11 correctly associate the running settings window with the application's `.desktop` file and icon.
- **Installer Updates**: Updated `install.sh` and `uninstall.sh` to correctly install and remove the SVG icon into the user's `~/.local/share/icons/hicolor/scalable/apps/` directory.

### Fixed
- **Missing OCR Translation**: Fixed a UI issue where the OCR shortcut label would incorrectly display the internal variable name (`ocr_key`) by adding proper translations for all supported languages.

## [v0.2.5] - 2026-08-09

### Changed
- **CI/CD Workflow Overhaul**: Comprehensive improvements to `.github/workflows/release.yml`:
  - Switched from `pip` to `uv` for dependency installation, consistent with project tooling.
  - Deduplicated Nuitka build commands into a reusable shell function with shared flags array.
  - Added `allow-prereleases: true` for Python 3.14 setup to prevent CI failures.
  - Configured `ccache` properly with `hendrikmuhs/ccache-action` for faster recompilation.
  - Added `pip` caching via `actions/setup-python` cache option.
  - Pinned Flutter version to `3.32.x` for reproducible builds.
  - Added explicit `flutter pub get` step before Flutter build.
  - Removed harmful `tray_manager_patched/lib` overwrite that replaced patched code with vanilla pub.dev version.
  - Added `concurrency` group to prevent duplicate release builds.
  - Added smoke tests for compiled binaries.
  - Improved tar packaging with dedicated `dist/` directory.
  - Enhanced GitHub Release with auto-generated release notes and descriptive name.

### Fixed
- **Date Reading Validation**: Fixed an issue where slashes (`/`) and hyphens (`-`) in dates were incorrectly read as mathematical operations ("divided by", "minus") by the TTS engine. Added recognition for major Anglo-Saxon and European date formats (e.g., DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, MM/YYYY) to preserve their native formatting and allow the TTS to read them naturally as dates.

## [v0.2.4] - 2026-08-05

### Added
- **Interactive Shortcut Recording**: Replaced standard text inputs for shortcut configuration with an interactive widget that listens to physical keystrokes, eliminating the need to manually type key names (e.g., "esc", "ctrl").
- **OCR Language Selection**: Added a dropdown menu in the OCR tab to select the Tesseract OCR language, with dynamic fetching of installed language packs. The backend now respects this setting during OCR extraction.

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
