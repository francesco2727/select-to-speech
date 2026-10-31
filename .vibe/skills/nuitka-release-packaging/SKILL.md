---
name: nuitka-release-packaging
description: Load this skill when adding or removing Python dependencies in pyproject.toml, modifying CLI entry points (entrypoint.py, main.py), editing GitHub Actions release workflows (.github/workflows/release.yml), or updating installation/uninstallation scripts (install.sh, install-local.sh, uninstall.sh, systemd/desktop files).
---

# Nuitka Compilation, Release CI, and Linux Packaging

Scope: Python dependency changes in `pyproject.toml`, standalone binary compilation in `.github/workflows/release.yml`, multi-call CLI entry points (`src/select_to_speech/entrypoint.py` and `src/select_to_speech/main.py`), and installer scripts (`install.sh`, `install-local.sh`, `uninstall.sh`, `bin/`).

## 1. Nuitka `--onefile` Synchronization (`pyproject.toml` ↔ `release.yml`)

Whenever you add, remove, or upgrade a package in `pyproject.toml`, verify and update `NUITKA_FLAGS` in `.github/workflows/release.yml`:

- **`--include-package` vs `--include-module`**:
  - Use `--include-package=<name>` **only** for actual Python packages (directories containing `__init__.py` or namespace packages, e.g., `select_to_speech`, `sherpa_onnx`, `fastapi`, `pulsectl`).
  - Use `--include-module=<name>` for single-file `.py` modules or compiled C/C++ extension `.so` modules (e.g., `--include-module=pedalboard_native`). Passing a C-extension module to `--include-package` breaks Nuitka compilation.
- **Runtime data assets (`--include-package-data`)**:
  - Add `--include-package-data=<pkg>` whenever a dependency loads non-code files at runtime (currently `lingua`, `emoji`, `certifi`).
- **Excluding unused modules (`--nofollow-import-to`)**:
  - Keep test suites, GUI toolkits, and non-Linux platform backends (`_darwin`, `_win32`, `pytest`, `unittest`, `sherpa_onnx.cli`) in `--nofollow-import-to` to minimize binary size and compile time.

## 2. Optional Native / C-Library Dependencies

Compiled Nuitka binaries always bundle the Python wrapper even when the target user's Linux distribution lacks the underlying system C shared library.
- When importing modules that load system C shared libraries at import time via `ctypes` or `cffi` (such as `pulsectl` or `pyaudio`), always catch **both** `(ImportError, OSError)`:
  ```python
  try:
      import pulsectl
  except (ImportError, OSError):
      pulsectl = None
  ```

## 3. Multi-Call Binary Dispatcher Alignment

The release build compiles a single `select-to-speech` binary from `src/select_to_speech/entrypoint.py` and creates symlinks (`select-to-speech-check`, `select-to-speech-audio`, `select-to-speech-download`) alongside flag-based dispatch (`--check`, `--audio-devices`, `--download`).

Whenever you add or modify a CLI subcommand or flag, keep all 4 locations synchronized:
1. `pyproject.toml` under `[project.scripts]`
2. `src/select_to_speech/entrypoint.py` (`dispatch()`)
3. `src/select_to_speech/main.py` (`main()`)
4. `.github/workflows/release.yml` (symlink creation and `xvfb-run` smoke tests)

Note: In Nuitka `--onefile` mode, `sys.argv[0]` points to the unpacked temporary binary, while the original symlink name is passed in `os.environ.get("NUITKA_ONEFILE_BINARY")`. Always check both.

## 4. Flutter Linux Bundle & Installer Scripts

- **`patchelf` on `libtray_manager_plugin.so`**:
  - Both `.github/workflows/release.yml` and `install.sh` / `install-local.sh` strip Ubuntu-specific transitive `DT_NEEDED` entries (`libayatana-indicator3.so.7`, `libayatana-ido3-0.4.so.0`) and set `RPATH` to `$ORIGIN` so the pre-compiled GUI bundle runs on Arch, Fedora, and Debian/Ubuntu alike. Preserve this step when modifying release or installer scripts.
- **Venv symlink compatibility**:
  - `install.sh` creates `$INSTALL_DIR/.venv/bin/select-to-speech` pointing to `$INSTALL_DIR/bin/select-to-speech` so the Flutter UI can locate the backend binary identically in both local-dev and release installations.

## 5. Wayland Taskbar Identity (GUI Binary Name)

The Flutter Linux GUI binary is named `select-to-speech-gui` (`BINARY_NAME` in `src/ui/linux/CMakeLists.txt`). This name is load-bearing for desktop integration:

- On Wayland, a GTK3 window's `app_id` reported to the compositor is the **program (binary) name**, not `APPLICATION_ID` (that is only the D-Bus name, currently `com.selecttospeech.gui`). KDE/GNOME taskbars therefore match the running window to a `.desktop` file **named exactly like the binary**; a mismatch shows a generic taskbar icon.
- `install.sh` / `install-local.sh` install `select-to-speech.desktop` and symlink it as `select-to-speech-gui.desktop` for Wayland matching; `StartupWMClass=select-to-speech-gui` covers X11; `uninstall.sh` removes the symlink.
- The window title ("Select to Speech") and `gtk_window_set_icon_name(window, "select-to-speech")` are set in `src/ui/linux/my_application.cc`.
- If `BINARY_NAME` ever changes, keep ALL of these in sync or the taskbar icon breaks: the two `bin/*.sh` wrappers (`$BUNDLE_DIR/<BINARY_NAME>`), `select-to-speech.desktop` (`StartupWMClass`), the Wayland desktop symlink in `install.sh` / `install-local.sh`, its removal in `uninstall.sh`, and the icon name in `my_application.cc`.
