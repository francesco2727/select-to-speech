# Select-to-Speech

A Wayland-native text-to-speech application for Linux that reads selected text aloud using a keyboard shortcut. It supports multilingual automatic language detection, streaming audio playback, and optional AI-powered screen reading via Ollama vision models.

## Features

- **Read selected text** — highlight any text and press a hotkey to hear it spoken
- **Automatic language detection** — switches voice per language segment (e.g. Italian + English in the same paragraph)
- **Smart English Loanword Detection** — correctly pronounces English tech terms and loanwords within non-English text without switching the voice
- **Two TTS engines** — [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) (default, high quality) and [Piper TTS](https://github.com/rhasspy/piper)
- **Screen reading via Ollama** — capture the screen and have a local vision LLM extract or describe its content, then read it aloud
- **KDE Plasma system tray GUI** — native PySide6/KDE tray icon with settings window
- **Pause / resume / stop** playback from tray or keyboard

---

## Requirements

### System packages (Arch / CachyOS)

```bash
sudo pacman -S pyside6 shiboken6 wl-clipboard
```

- `wl-clipboard` — required for Wayland primary-selection access
- `xclip` — optional, fallback for XWayland apps
- `pulseaudio` or `pipewire` — audio playback (usually pre-installed on KDE)
- KDE Frameworks Python bindings (`KWidgetsAddons`, `KCoreAddons`, `KNotifications`, `KStatusNotifierItem`) — bundled with KDE Plasma system packages

### Python (managed by Poetry)

Python 3.14 is required.

```bash
pip install poetry   # or use your distro's poetry package
```

---

## Installation

### System install (recommended)

Installs the app as a native KDE system service with autostart and launcher entry:

```bash
git clone https://github.com/your-user/select-to-speech.git
cd select-to-speech
./install.sh
```

The script:
1. Installs missing system packages via `pacman`
2. Runs `poetry install`
3. Creates symlinks in `~/.local/bin/`
4. Adds a `.desktop` entry to the KDE launcher
5. Installs the KDE notification config (requires sudo)
6. Registers and starts a systemd user service (`select-to-speech.service`)

On first run the Kokoro model files (~350 MB) are downloaded automatically.

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

poetry install

# Copy the KDE notification config (needed for desktop notifications)
sudo cp select-to-speech.notifyrc /usr/share/knotifications6/
```

---

## Running the app (manual)

### GUI mode (system tray — recommended)

```bash
poetry run select-to-speech-gui
```

Starts the app with a KDE system tray icon. Right-click the tray for pause/stop and settings.

### Headless / CLI mode

```bash
poetry run select-to-speech
```

Runs without a GUI. Use keyboard shortcuts to control playback. Exit with `Ctrl+C`.

### Open settings window only

```bash
poetry run select-to-speech-settings
```

### Utility commands

```bash
# Check system dependencies
poetry run select-to-speech-check

# List available audio output devices (to find device_id)
poetry run select-to-speech-audio
```

---

## Ollama (optional — screen reading features)

The screen reading and screen description features require a locally running [Ollama](https://ollama.com) server with a vision-capable model. You must install Ollama and pull a vision model (like `gemma4:e2b`, `llava:7b`, etc) for the shortcuts (`Alt + Ctrl + R` and `Alt + Ctrl + D`) to become active.

---

## Default keyboard shortcuts

| Action | Shortcut |
|---|---|
| Read selected text | `Alt + Esc` |
| Pause / Resume | `Alt + W` |
| Stop playback | `Alt + S` |
| Read screen text (Ollama) | `Alt + Ctrl + R` |
| Describe screen (Ollama) | `Alt + Ctrl + D` |

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
| `ollama` | Ollama server URL, vision model names, and screen-feature hotkeys |
| `debug` | Set to `true` to enable verbose logging |
| `gui_language` | Language for the settings GUI (`auto` follows the system locale) |

### Voice models

**Kokoro** (default): model files are downloaded automatically on first run (~350 MB) to `~/.local/share/select-to-speech/voices/`. Voice names follow the pattern `{lang_prefix}_{name}` (e.g. `if_sara` for Italian female, `af_heart` for American English female).

**Piper**: download `.onnx` + `.onnx.json` files from [HuggingFace rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) and place them in `~/.local/share/select-to-speech/voices/`.

---

## Logs

Application logs are written to:

```
~/.local/state/select-to-speech/app.log
```
