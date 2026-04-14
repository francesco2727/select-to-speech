# Select-to-Speech

A Wayland-native text-to-speech application for Linux that reads selected text aloud using a keyboard shortcut. It supports multilingual automatic language detection, streaming audio playback, and optional AI-powered screen reading via Ollama vision models.

## Features

- **Read selected text** — highlight any text and press a hotkey to hear it spoken
- **Automatic language detection** — switches voice per language segment (e.g. Italian + English in the same paragraph)
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

```bash
git clone https://github.com/your-user/select-to-speech.git
cd select-to-speech

poetry install

# Copy the KDE notification config (needed for desktop notifications)
sudo cp select-to-speech.notifyrc /usr/share/knotifications6/
```

On first run the Kokoro model files (~350 MB) are downloaded automatically.

---

## Running the app

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

The screen reading and screen description features require a locally running [Ollama](https://ollama.com) server with a vision-capable model.

### 1. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Or on Arch / CachyOS:

```bash
sudo pacman -S ollama
```

### 2. Start the Ollama server

```bash
ollama serve
```

The server listens on `http://localhost:11434` by default. To start it automatically as a systemd service:

```bash
sudo systemctl enable --now ollama
```

### 3. Pull a vision model

The default model configured in this app is `gemma4:e2b` (Google Gemma 4, 2B — lightweight and fast):

```bash
ollama pull gemma4:e2b
```

Any other Ollama vision model works. To use a different one, change `read_screen_model` and `describe_screen_model` in `~/.config/select-to-speech/config.yaml`.

Some alternatives:

| Model | Size | Notes |
|---|---|---|
| `gemma4:e2b` | ~2 GB | Default — fast, low memory |
| `llava:7b` | ~4 GB | Widely tested vision model |
| `minicpm-v:8b` | ~5 GB | Strong OCR performance |
| `llama3.2-vision:11b` | ~8 GB | Higher accuracy, needs more VRAM |

### 4. Verify the server is running

```bash
curl http://localhost:11434
# Expected: "Ollama is running"
```

Once Ollama is running and a vision model is pulled, the screen reading shortcuts (`Alt + Ctrl + R` and `Alt + Ctrl + D`) become active.

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

### Full example

```yaml
debug: false
gui_language: auto   # 'auto' | 'en' | 'it' | 'es' | 'fr'

voice:
  engine: kokoro           # 'kokoro' (default) or 'piper'
  model: kokoro-v1.0       # base model name
  language: it             # default language code (ISO 639-1)
  language_models:         # per-language voice mapping
    en: af_heart
    it: if_sara
    es: ""    # empty = no voice configured for this language
    fr: ""
    de: ""
    hi: ""
    ja: ""
    ko: ""
    pt: ""
    zh: ""

audio:
  device_id: null   # null = system default; use select-to-speech-audio to list IDs
  speed: 1.0        # 0.5 – 2.0
  pitch: 1.0        # 0.5 – 2.0
  volume: 1.0       # 0.0 – 2.0

keyboard:
  modifier_key: alt    # 'alt' | 'ctrl' | 'shift'
  trigger_key: esc     # key combined with modifier to start reading
  pause_key: w         # key combined with modifier to pause/resume
  stop_key: s          # key combined with modifier to stop

ollama:
  server_url: http://localhost:11434
  read_screen_model: gemma4:e2b       # vision model for text extraction
  describe_screen_model: gemma4:e2b   # vision model for screen description
  read_screen_modifier: alt+ctrl
  read_screen_key: r
  describe_screen_modifier: alt+ctrl
  describe_screen_key: d
```

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
