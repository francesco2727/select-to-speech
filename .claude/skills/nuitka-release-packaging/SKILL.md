---
name: nuitka-release-packaging
description: Load this skill when adding or removing Python dependencies in pyproject.toml, modifying the CLI entry point (entrypoint.py, main.py), editing the release workflow (.github/workflows/release.yml), the native packages (packaging/: nfpm.yaml, build-*.sh, test-packages.sh, .desktop files), or the install scripts (install.sh, install-local.sh, uninstall.sh).
---

# Nuitka Build, Native Packages (.deb/.rpm/Arch), and Release CI

Scope: Python dependency changes in `pyproject.toml`, the standalone backend build, the Flutter bundle build, the nfpm packages in `packaging/`, `.github/workflows/release.yml`, the CLI entry point (`src/select_to_speech/entrypoint.py`), and the install scripts.

## 1. Layout and build pipeline

The app ships as native packages built with **nfpm** (`packaging/nfpm.yaml`) from two directories:

```
/usr/lib/select-to-speech/backend/   Nuitka --standalone (dist/backend)
/usr/lib/select-to-speech/gui/       Flutter bundle      (dist/gui)
/usr/bin/select-to-speech      -> ../lib/select-to-speech/backend/select-to-speech
/usr/bin/select-to-speech-gui  -> ../lib/select-to-speech/gui/select-to-speech-gui
/usr/share/applications/select-to-speech-gui.desktop
/etc/xdg/autostart/select-to-speech.desktop
/usr/share/icons/hicolor/scalable/apps/com.selecttospeech.gui.svg
```

Every step is a script, used identically by CI and locally (CI only orchestrates them):

| Script | Output |
|---|---|
| `packaging/build-lingua.sh` | slim lingua wheel installed into `$PYTHON` |
| `packaging/build-backend.sh` | `dist/backend/` |
| `packaging/build-gui.sh` | `dist/gui/` (+ `build/gui-symbols/`) |
| `packaging/build-packages.sh [VERSION]` | `dist/packages/` (.deb, .rpm, .pkg.tar.zst, SHA256SUMS) |
| `packaging/test-packages.sh [distro...]` | installs each package in docker (Debian 12, Ubuntu 22.04/24.04, Fedora, Arch) and smoke-tests it |

- **Build on Ubuntu 22.04** (glibc 2.35, GLib 2.72) so binaries run on the oldest supported distros. Do not move jobs to `ubuntu-latest`. Native code must compile against GLib 2.72 (see the `G_APPLICATION_DEFAULT_FLAGS` shim in `src/ui/linux/my_application.cc`).
- `test-packages.sh` treats an `ldd` "not found" as an error only if the library is not shipped inside the bundle (Nuitka/Flutter load bundled libs by soname, which `ldd` does not see).
- `build-packages.sh` downloads nfpm with `curl --retry 5 --retry-all-errors` to survive transient CI errors; keep the retry flags.
- After changing anything in `packaging/`, run `packaging/build-packages.sh && packaging/test-packages.sh` (needs `dist/backend` and `dist/gui`).

## 2. Nuitka `--standalone` (never `--onefile`)

Flags live only in `packaging/build-backend.sh` (`NUITKA_FLAGS`). `--onefile` must not come back: it re-extracts ~500 MB into `~/.cache` per version and slows every start.

Whenever you add, remove, or upgrade a package in `pyproject.toml`, update `NUITKA_FLAGS`:
- **`--include-package` vs `--include-module`**: `--include-package=<name>` only for real packages (directories, e.g. `sherpa_onnx`, `fastapi`, `pulsectl`); `--include-module=<name>` for single-file modules and C-extension `.so` modules (e.g. `--include-module=pedalboard_native`). Passing a C-extension module to `--include-package` breaks compilation.
- **Runtime data (`--include-package-data`)**: add it when a dependency loads non-code files at runtime (currently `emoji`, `certifi`). lingua does not need it: its models are compiled into its extension module.
- **Exclusions (`--nofollow-import-to`)**: keep test suites, GUI toolkits and non-Linux backends (`_darwin`, `_win32`, `pytest`, `unittest`, `sherpa_onnx.cli`) excluded.
- Dependencies are installed from the lock: `uv sync --frozen --no-dev --no-editable`.

## 3. Slim lingua (`packaging/build-lingua.sh`)

The PyPI lingua wheel embeds the models of all 75 languages (~290 MB). The release builds lingua-rs (pinned tag + commit) with only the Cargo features for the languages in `_LINGUA_LANGUAGES` (`main.py`), ~10x smaller.
- **Adding a language to `_LINGUA_LANGUAGES` requires adding it to `LANGUAGES=(...)` in `build-lingua.sh`**, otherwise `lingua.Language.<X>` does not exist in the packaged binary and `main.py` fails at import. `tests/test_packaging.py` enforces this.
- The script must not use `git clone` for the lingua-rs source: in CI `SRC_DIR` may already exist holding only the restored `target/` cache, so it does `git init` + shallow `fetch` of the tag + `checkout`. It also resolves `PYTHON` to an absolute path. Keep both.
- When bumping `lingua-language-detector` in `uv.lock`, update `LINGUA_TAG` / `LINGUA_COMMIT` to the matching lingua-rs release.

## 4. Runtime dependencies of the packages

Libraries loaded from the system (everything else is bundled) are declared per format in `overrides:` of `nfpm.yaml` (names differ per distro):
- `wl-clipboard`, GTK 3, `libayatana-appindicator` (GUI/tray), **libEGL/libGLESv2** (`dlopen()`ed by libepoxy for Flutter rendering, so neither `ldd` nor GTK's dependencies catch it on minimal Debian/Ubuntu/Fedora), **PortAudio** (`pyaudio/_portaudio.so` links `libportaudio.so.2`, Nuitka does not bundle it), **libpulse** (pulsectl via ctypes), **libatomic** (`pedalboard_native.so`; missing from minimal Debian/Ubuntu/Fedora installs, part of `gcc-libs` on Arch).
- OCR tools are `recommends`/`suggests` on deb/rpm. nfpm cannot emit pacman `optdepends`, so Arch lists them in `packaging/arch-postinstall.sh`.
- If you add a new system library or external binary, add it to all three formats in `nfpm.yaml`, to `system_check.py`, and to the README requirements.
- Modules that load system C libraries at import time via `ctypes`/`cffi` (`pulsectl`, `pyaudio`) must catch **both** `(ImportError, OSError)`:
  ```python
  try:
      import pulsectl
  except (ImportError, OSError):
      pulsectl = None
  ```

## 5. CLI entry point

The binary is compiled from `src/select_to_speech/entrypoint.py`; `dispatch(argv)` is also the `select-to-speech` console script. Subcommands are **flags only** (`--check`, `--audio-devices`, `--download`); there are no `argv[0]`/symlink aliases. Each branch imports only what it needs (`--check` must not import lingua/sherpa: `tests/test_entrypoint.py`) and passes its remaining `argv` explicitly to the subcommand function. To add a subcommand: add the branch and help line in `entrypoint.py`, a test in `tests/test_entrypoint.py`, the README "Command line" section, and (if it is a cheap smoke check) the CI/`test-packages.sh` checks.

## 6. Flutter bundle

- `packaging/build-gui.sh` strips the Ubuntu-only transitive `DT_NEEDED` entries (`libayatana-indicator3.so.7`, `libayatana-ido3-0.4.so.0`) from `libtray_manager_plugin.so` with `patchelf` and sets its RPATH to `$ORIGIN`, so the bundle loads on Arch/Fedora. Keep this step.
- `packaging/build-gui.sh` also deletes `lib/libdartjni.so` from the bundle: it comes from the transitive `jni` package (Android-only use via `dynamic_color`) and needs `libjvm.so`, which does not exist on desktops. Keep this step.
- The GUI finds the backend at `<gui dir>/../backend/select-to-speech` (packages) or by walking up to a `.venv` (development); it uses `Platform.resolvedExecutable`, so the `/usr/bin` symlink works. Keep this in sync if the layout changes.

## 7. Wayland taskbar identity (GUI binary name)

The Flutter GUI binary is `select-to-speech-gui` (`BINARY_NAME` in `src/ui/linux/CMakeLists.txt`). On Wayland a GTK3 window's `app_id` is the **program name** (not `APPLICATION_ID`, which is only the D-Bus name `com.selecttospeech.gui`), and taskbars match it to the `.desktop` file **with the same name**. Hence the single desktop entry is `select-to-speech-gui.desktop`, with `StartupWMClass=select-to-speech-gui` for X11; the window icon name is set in `my_application.cc`.

**Icon name**: the app icon is `com.selecttospeech.gui` (same as the application id), installed as `com.selecttospeech.gui.svg` from `src/ui/images/select_to_speech_tray_icon.svg`. Do not rename it back to `select-to-speech`: KDE strips dash-separated suffixes from icon names (`select-to-speech` -> `select`) and finds the Breeze cursor icon before the hicolor one. The name must match in `packaging/nfpm.yaml` (dst), both `.desktop` files (`Icon=`), `install-local.sh`, `uninstall.sh` and `my_application.cc`.

If `BINARY_NAME` changes, update: `packaging/nfpm.yaml` (bundle path, `/usr/bin` symlink, desktop file name), `packaging/select-to-speech-gui.desktop` (file name, `Exec`, `StartupWMClass`), `packaging/select-to-speech-autostart.desktop` (`Exec`), `install-local.sh`, `uninstall.sh`, and `my_application.cc`.

## 8. Install scripts

- `install.sh`: end-user installer. Detects pacman/apt/dnf, downloads the matching package and `SHA256SUMS` from the latest release, verifies, installs with the package manager, and runs `uninstall.sh` if a legacy per-user install is found.
- `install-local.sh`: development install from the repo (`.venv` backend + locally built bundle, `~/.local/bin/select-to-speech-gui` symlink, desktop + autostart entries in `~/.local`/`~/.config`). Reuses the files in `packaging/` with `/usr/bin/` rewritten to `~/.local/bin/`.
- `uninstall.sh`: removes per-user installs only (legacy <= v0.5 layout with its systemd user service, the dev install, onefile caches). Also removes the old `select-to-speech.{png,svg}` icons from `~/.local/share/icons/hicolor/*/apps/`. Never touches the native package. `--purge` also removes config/voices/logs.
- Autostart is XDG autostart, not a systemd user service; do not reintroduce one (a unit in `~/.config/systemd/user` would also shadow the package's files).
