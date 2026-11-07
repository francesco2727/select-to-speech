# Select-to-Speech

Designed specifically for people with visual impairments, reading difficulties, or anyone requiring effortless audio feedback, Select-to-Speech is a Wayland-native text-to-speech application for Linux that reads selected text aloud using a simple keyboard shortcut. It supports multilingual automatic language detection and streaming audio playback with natural voices.

## Features

- **Designed for accessibility** — tailored for visually impaired users to instantly listen to any on-screen text without complex screen reader setup
- **Read selected text** — highlight any text and press a hotkey to hear it spoken
- **Screen OCR & read** — draw a screen region (`Alt + r`) with `slurp`/`grim` (or KDE Spectacle) to extract text via Tesseract and read it aloud
- **Automatic language detection** — switches voice per language segment (e.g. Italian + English in the same paragraph)
- **Multilingual text normalization** — automatically converts math operators (`+`, `-`, `%`, etc.) and currency symbols (`$`, `€`, `£`, `¥`, etc.) into natural spoken words based on the detected language
- **TTS engine** — [Sherpa-ONNX](https://github.com/k2-fsa/sherpa-onnx) running Kokoro TTS (high quality, offline, native C++ runtime)
- **System tray GUI** — native tray icon with settings window
- **Pause / resume / stop** playback from tray or keyboard

---

## Installation

Select-to-Speech ships as a native package for **Arch Linux**, **Debian/Ubuntu** and **Fedora**
(x86_64; Debian 12 / Ubuntu 22.04 or newer). The package manager installs the required system
dependencies, and updates/removal go through it as well.

### Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/francesco2727/select-to-speech/main/install.sh | bash
```

The script picks the right package for your distribution from the
[latest release](https://github.com/francesco2727/select-to-speech/releases/latest), verifies its
checksum, installs it with `pacman`, `apt` or `dnf`, removes leftovers of old per-user installs
and starts the app.

### Manual install

Download the package for your distribution from the
[releases page](https://github.com/francesco2727/select-to-speech/releases/latest), then:

```bash
sudo pacman -U select-to-speech-*.pkg.tar.zst     # Arch Linux and derivatives
sudo apt install ./select-to-speech_*_amd64.deb   # Debian, Ubuntu and derivatives
sudo dnf install ./select-to-speech-*.x86_64.rpm  # Fedora
```

Select-to-Speech then starts automatically at login (XDG autostart; disable it from your
desktop's autostart settings). To start it right away, launch **Select to Speech** from the
application menu.

The Kokoro voice model (~350 MB) is downloaded on first use, or from **Settings**. To download it
in advance:

```bash
select-to-speech --download
```

### Uninstall

Remove the `select-to-speech` package with your package manager. Config, voice models and logs
are kept in `~/.config/select-to-speech/`, `~/.local/share/select-to-speech/` and
`~/.local/state/select-to-speech/`.

### Upgrading from v0.5 or older

Older versions were installed per user in `~/.local`, with a systemd user service that would
shadow the package. `install.sh` cleans this up automatically; if you install the package
manually, run this first (config and voices are kept):

```bash
curl -fsSL https://raw.githubusercontent.com/francesco2727/select-to-speech/main/uninstall.sh | bash
```

`select-to-speech --check` warns if any leftovers are still present.

---

## Requirements

Installed automatically with the package:

- **`wl-clipboard`** (`wl-paste`): reads the selected text on Wayland.
- **GTK 3**, **EGL** and **`libayatana-appindicator`**: settings window and system tray icon.
- **PortAudio**: audio output.
- **libpulse**: lowers other applications' volume while reading (PipeWire and PulseAudio).

> **XWayland compatibility is built in**: selections inside X11 applications running under
> XWayland are read directly through python-Xlib, so no extra package (e.g. `xclip`) is required.

### Optional: screen text recognition (OCR, `Alt + R`)

| | Arch | Debian / Ubuntu | Fedora |
|---|---|---|---|
| OCR engine + languages | `tesseract tesseract-data-eng tesseract-data-ita` | `tesseract-ocr tesseract-ocr-eng tesseract-ocr-ita` | `tesseract tesseract-langpack-eng tesseract-langpack-ita` |
| Screen capture (KDE) | `spectacle` | `kde-spectacle` | `spectacle` |
| Screen capture (wlroots: Sway, Hyprland…) | `grim slurp` | `grim slurp` | `grim slurp` |

On Debian/Ubuntu and Fedora the OCR engine is installed by default as a recommended package.
Install additional Tesseract language packs for other languages.

Check what is installed at any time with:

```bash
select-to-speech --check
```

---

## Command line

```bash
select-to-speech --check            # check system dependencies, voice models and old installs
select-to-speech --audio-devices    # list audio output devices (to find device_id)
select-to-speech --download         # download the Kokoro voice model
select-to-speech-gui --settings     # open the settings window
```

---

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.12+ is managed by it) and the
[Flutter SDK](https://docs.flutter.dev/get-started/install/linux) with its Linux desktop toolchain.

```bash
git clone https://github.com/francesco2727/select-to-speech.git
cd select-to-speech
./install-local.sh
```

`install-local.sh` installs the dependencies with `uv sync`, downloads the Kokoro model, builds the
Flutter GUI in release mode, links it as `~/.local/bin/select-to-speech-gui`, adds the desktop and
autostart entries and starts it. The GUI runs the backend from the repository's `.venv`, so Python
changes only need an app restart (quit from the tray, then relaunch); Dart changes need
`./install-local.sh` again. `./uninstall.sh` removes the development install.

Useful commands:

```bash
uv run pytest                         # tests
uv run select-to-speech               # backend daemon only, in the foreground (Ctrl+C to exit)
uv run select-to-speech --check       # CLI subcommands, as above
(cd src/ui && flutter run -d linux)   # GUI in debug mode, with hot reload
```

### Building the packages

The release workflow (`.github/workflows/release.yml`) runs on Ubuntu 22.04 so the binaries also
work on the oldest supported distributions. The same scripts can be run locally:

```bash
PYTHON=.venv/bin/python packaging/build-lingua.sh   # slim lingua: only the languages the app speaks
PYTHON=.venv/bin/python packaging/build-backend.sh  # Nuitka standalone -> dist/backend/
packaging/build-gui.sh                              # Flutter bundle -> dist/gui/
packaging/build-packages.sh                         # nfpm -> dist/packages/*.{deb,rpm,pkg.tar.zst}
packaging/test-packages.sh                          # install + smoke test in distro containers (docker)
```

---

## Default keyboard shortcuts

| Action | Shortcut |
|---|---|
| Read selected text | `Alt + Esc` |
| Screen OCR & Read | `Alt + R` |
| Pause / Resume | `Alt + W` |
| Stop playback | `Alt + S` |

All shortcuts are configurable in `~/.config/select-to-speech/config.yaml`.

---

## Configuration

The configuration file is loaded from:

```
~/.config/select-to-speech/config.yaml
```

If the file does not exist, defaults are used. You can edit it manually or use the settings GUI.

### Configuration sections

| Section | Description |
|---|---|
| `voice` | TTS engine selection, default language, and per-language voice mapping |
| `audio` | Output device, playback speed, pitch, and volume |
| `keyboard` | Modifier and trigger keys for all hotkeys |
| `debug` | Set to `true` to enable verbose logging |
| `gui_language` | Language for the settings GUI (`auto` follows the system locale) |

### Voice models

**Kokoro**: model files (~350 MB) are downloaded to `~/.local/share/select-to-speech/voices/` on first use, from Settings, or with `select-to-speech --download`. Voice names follow the pattern `{lang_prefix}_{name}` (e.g. `if_sara` for Italian female, `af_heart` for American English female).

---

## Logs

Application logs are written to:

```
~/.local/state/select-to-speech/app.log
```
