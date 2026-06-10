# Select-to-Speech

A Wayland-native text-to-speech application for Linux that reads selected text aloud using a keyboard shortcut. It supports multilingual automatic language detection and streaming audio playback.

## Features

- **Read selected text** — highlight any text and press a hotkey to hear it spoken
- **Automatic language detection** — switches voice per language segment (e.g. Italian + English in the same paragraph)
- **TTS engine** — [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) (high quality, offline)
- **System tray GUI** — native tray icon with settings window
- **Pause / resume / stop** playback from tray or keyboard

---

## Requirements

### System packages (Arch / CachyOS)

```bash
sudo pacman -S wl-clipboard gettext
```

- `wl-clipboard` — required for Wayland primary-selection access
- `gettext` — required to compile translation files during installation

### Python (managed by uv)

Python 3.14 is required.

```bash
# uv is used for project and dependency management
# Install uv if you don't have it:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Installation

> [!NOTE]
> **Migration from Poetry to `uv`**: The project has transitioned from Poetry to `uv` for faster installation, simpler dependency management, and lighter runtime footprints. If you are upgrading from an older Poetry-based version, simply run `git pull` followed by `./install.sh`. The install script will recreate the virtual environment using `uv` and update all services automatically. You can then safely remove old Poetry files or environments if desired.

### System install (recommended)

Installs the app as a native KDE system service with autostart and launcher entry:

```bash
git clone https://github.com/your-user/select-to-speech.git
cd select-to-speech
./install.sh
```

The script:
1. Installs missing system packages via `pacman`
2. Runs `uv sync` (after creating a virtual environment in `.venv/` with system site packages)
3. Creates wrapper scripts in `~/.local/bin/` that run directly using the virtual environment's executables (this ensures they run successfully without requiring `uv` to be in the `$PATH` when launched by systemd or desktop menus)
4. Adds a `.desktop` entry to the KDE launcher
5. Installs the KDE notification config (requires sudo)
6. Registers and starts a systemd user service (`select-to-speech.service`)

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

## Running the app (manual)

### GUI mode (system tray — recommended)

```bash
uv run select-to-speech-gui
```

Starts the app with a KDE system tray icon. Right-click the tray for pause/stop and settings.

### Headless / CLI mode

```bash
uv run select-to-speech
```

Runs without a GUI. Use keyboard shortcuts to control playback. Exit with `Ctrl+C`.

### Open settings window only

```bash
uv run select-to-speech-settings
```

### Utility commands

```bash
# Check system dependencies
uv run select-to-speech-check

# List available audio output devices (to find device_id)
uv run select-to-speech-audio
```

---

## Default keyboard shortcuts

| Action | Shortcut |
|---|---|
| Read selected text | `Alt + Esc` |
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
