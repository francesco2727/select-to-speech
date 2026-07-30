# Select-to-Speech

Designed specifically for people with visual impairments, reading difficulties, or anyone requiring effortless audio feedback, Select-to-Speech is a Wayland-native text-to-speech application for Linux that reads selected text aloud using a simple keyboard shortcut. It supports multilingual automatic language detection and streaming audio playback with natural voices.

## Features

- **Designed for accessibility** — tailored for visually impaired users to instantly listen to any on-screen text without complex screen reader setup
- **Read selected text** — highlight any text and press a hotkey to hear it spoken
- **Screen OCR & read** — draw a screen region (`Alt + r`) with `slurp`/`grim` (or KDE Spectacle) to extract text via Tesseract and read it aloud
- **Automatic language detection** — switches voice per language segment (e.g. Italian + English in the same paragraph)
- **Multilingual text normalization** — automatically converts math operators (`+`, `-`, `%`, etc.) and currency symbols (`$`, `€`, `£`, `¥`, etc.) into natural spoken words based on the detected language
- **TTS engine** — [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) (high quality, offline)
- **System tray GUI** — native tray icon with settings window
- **Pause / resume / stop** playback from tray or keyboard

---

## Requirements

### System packages (Arch Linux)

You can check your system's dependency status at any time by running `select-to-speech-check` (or `uv run select-to-speech-check`).

#### 1. Required Core Dependencies
These packages are strictly required for Wayland text selection access and system tray functionality:

```bash
sudo pacman -S wl-clipboard libayatana-appindicator
```
- **`wl-clipboard`** (`wl-paste`) — Required for reading selected or copied text in native Wayland environments.
- **`libayatana-appindicator`** — System library required by the Flutter GUI to show the system tray icon and menu.

#### 2. Optional Dependencies: Screen Text Recognition (OCR — `Alt + r`)
Required if you want to select a rectangular region of your screen and read extracted text aloud:

```bash
sudo pacman -S tesseract tesseract-data-ita tesseract-data-eng spectacle slurp grim
```
- **`tesseract`** — Core OCR engine.
- **`tesseract-data-ita` / `tesseract-data-eng`** — Language packs for Italian and English character recognition (install additional `tesseract-data-*` packages for other languages).
- **`spectacle`** (or **`slurp` & `grim`**) — Screen capture tools (Spectacle for KDE Wayland; slurp & grim for wlroots-based environments like Sway or Hyprland).

#### 3. Optional Dependencies: XWayland Compatibility
Required if you want to read selected text inside legacy X11 applications running under XWayland:

```bash
sudo pacman -S xclip
```
- **`xclip`** — Allows intercepting primary selection inside non-native XWayland applications.

#### 👉 Install All Dependencies (Required + Optional)
To install everything and enable all features right away, run:

```bash
sudo pacman -S wl-clipboard libayatana-appindicator tesseract tesseract-data-ita tesseract-data-eng spectacle slurp grim xclip
```


### Python (managed by uv)

Python 3.14 is required.

```bash
# uv is used for project and dependency management
# Install uv if you don't have it:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Installation

### Quick Install (Recommended)

The easiest way to install Select-to-Speech is via the automated installation script, which downloads the latest pre-compiled release and configures your system automatically:

```bash
curl -sSL https://raw.githubusercontent.com/francesco2727/select-to-speech/main/install.sh | bash
```

### Local Development Install

If you want to modify the source code or compile the application locally:

```bash
git clone https://github.com/francesco2727/select-to-speech.git
cd select-to-speech
./install-local.sh
```

The script:
1. Runs `uv sync` (after creating a virtual environment in `.venv/` with system site packages)
2. Downloads Kokoro TTS model files and sets up the Flutter GUI binary
3. Creates wrapper scripts in `~/.local/bin/` that run directly using the virtual environment's executables (this ensures they run successfully without requiring `uv` to be in the `$PATH` when launched by systemd or desktop menus)
4. Adds a `.desktop` entry to the KDE launcher
5. Registers and starts a systemd user service (`select-to-speech.service`)
6. Executes `select-to-speech-check` as its final step to display an at-a-glance check of all required and optional system dependencies along with clear purpose explanations and exact installation instructions if any are missing

During installation, the Kokoro model files (~350 MB) are downloaded automatically (with a fallback to downloading on first run or manually if installation download fails or is skipped).

#### After a code update

No reinstallation needed — just restart the service:

```bash
git pull
systemctl --user restart select-to-speech
```

#### Useful service commands

```bash
systemctl --user status select-to-speech    # check status
systemctl --user restart select-to-speech   # restart after code changes
journalctl --user -u select-to-speech -f    # follow logs
```

#### Uninstall

```bash
./uninstall.sh
```

Removes the service, symlinks, and desktop entry. Config and voice files in `~/.config/select-to-speech/` and `~/.local/share/select-to-speech/` are kept.

---

### Manual / development mode

```bash
git clone https://github.com/your-user/select-to-speech.git
cd select-to-speech

# Create virtual environment with access to system packages, then sync dependencies
uv venv --system-site-packages
uv sync

# Copy the KDE notification config (needed for desktop notifications)
sudo cp select-to-speech.notifyrc /usr/share/knotifications6/
```

---

## Running the app (manual / development)

To run the application manually from the repository:

### Start the GUI (System Tray + Settings window)

Run the GUI wrapper script:

```bash
./bin/select-to-speech-gui.sh
```

Starts the app with a system tray icon. Right-click the tray for pause/stop and settings.

### Start the core daemon only (Headless mode)

To run the API server and keyboard shortcut listener without showing a GUI window:

```bash
uv run select-to-speech
```

Runs the backend API and hotkey listeners in the foreground. Use keyboard shortcuts to control playback. Exit with `Ctrl+C`.

### Open settings window only

You can launch the GUI specifically into the settings tab by running:

```bash
./bin/select-to-speech-settings.sh
```

### Utility commands

```bash
# Check system dependencies and optional OCR utilities (tesseract, spectacle, slurp, grim)
uv run select-to-speech-check

# List available audio output devices (to find device_id)
uv run select-to-speech-audio
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

**Kokoro**: model files are downloaded automatically during installation (~350 MB) to `~/.local/share/select-to-speech/voices/` (or on first run if missing). Voice names follow the pattern `{lang_prefix}_{name}` (e.g. `if_sara` for Italian female, `af_heart` for American English female).

---

## Logs

Application logs are written to:

```
~/.local/state/select-to-speech/app.log
```
