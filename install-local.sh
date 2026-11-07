#!/usr/bin/env bash
set -euo pipefail

# Development install: runs the backend from the repo's .venv and the GUI from the
# locally built Flutter bundle. End users should install the native package instead.
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }

# Ensure this is being run inside the repository
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -d "$INSTALL_DIR/.git" ] && [ ! -f "$INSTALL_DIR/pyproject.toml" ]; then
    error "install-local.sh must be run from inside the select-to-speech repository directory."
    exit 1
fi

info "Running in local installation mode using current repository: $INSTALL_DIR"

if [ -x /usr/bin/select-to-speech-gui ]; then
    warn "The select-to-speech system package is installed too: both would autostart."
    warn "Remove the package first if you want to run the development build."
fi

# Remove previous ~/.local installs (legacy install.sh layout, systemd service, old caches)
"$INSTALL_DIR/uninstall.sh" --quiet

# ── uv install ─────────────────────────────────────────────────────────────────
if ! command -v uv &> /dev/null; then
    warn "uv is not installed. Attempting to install uv automatically..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv &> /dev/null; then
        error "Failed to install uv. Please install it manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
fi

info "Setting up virtual environment with system packages..."
# Same Python as the release builds (see .github/workflows/release.yml)
uv venv --allow-existing --system-site-packages --python 3.12 "$INSTALL_DIR/.venv"
info "Running uv sync..."
uv sync --project "$INSTALL_DIR"

# ── Download Kokoro models ─────────────────────────────────────────────────────
info "Downloading Kokoro TTS model files (~350 MB)..."
if ! uv run --project "$INSTALL_DIR" select-to-speech --download --model kokoro-multi-lang-v1_0; then
    warn "Failed to download Kokoro model files during installation."
    warn "You can download them manually later via the settings GUI or by running:"
    warn "  uv run select-to-speech --download --model kokoro-multi-lang-v1_0"
fi

# ── Build/Download Flutter UI ───────────────────────────────────────────────────
info "Setting up Flutter UI..."
UI_BUNDLE_DIR="$INSTALL_DIR/src/ui/build/linux/x64/release/bundle"

if ! command -v flutter &> /dev/null; then
    if [ -d "$HOME/develop/flutter/bin" ]; then
        export PATH="$HOME/develop/flutter/bin:$PATH"
    elif [ -d "$HOME/development/flutter/bin" ]; then
        export PATH="$HOME/development/flutter/bin:$PATH"
    fi
fi

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    info "Force download enabled. Cleaning local UI bundle..."
    rm -rf "$UI_BUNDLE_DIR"
fi

# Compile Flutter UI locally
if command -v flutter &> /dev/null; then
    info "Compiling Flutter user interface locally (release mode)..."
    (cd "$INSTALL_DIR/src/ui" && flutter clean && flutter build linux --release)
else
    error "Flutter SDK was not found in PATH."
    error "Please install Flutter or ensure it is in your PATH to build the UI locally."
    exit 1
fi

# ── Launcher ───────────────────────────────────────────────────────────────────
# The bundle finds its libraries via RPATH ($ORIGIN/lib) and the backend by walking up
# to the repo's .venv, so a plain symlink is enough.
info "Linking $BIN_DIR/select-to-speech-gui to the GUI bundle..."
mkdir -p "$BIN_DIR"
ln -sf "$UI_BUNDLE_DIR/select-to-speech-gui" "$BIN_DIR/select-to-speech-gui"

# ── Desktop entry, autostart and icon ──────────────────────────────────────────
info "Installing icon, desktop entry and autostart entry..."
ICONS_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICONS_DIR" "$APPS_DIR" "$AUTOSTART_DIR"
cp "$INSTALL_DIR/src/ui/images/select_to_speech_tray_icon.svg" "$ICONS_DIR/select-to-speech.svg"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" &>/dev/null || true

# Same files as the native package, pointed at ~/.local/bin instead of /usr/bin.
# The desktop file is named after the GUI binary for Wayland taskbar matching.
sed "s|/usr/bin/|$BIN_DIR/|g" "$INSTALL_DIR/packaging/select-to-speech-gui.desktop" > "$APPS_DIR/select-to-speech-gui.desktop"
sed "s|/usr/bin/|$BIN_DIR/|g" "$INSTALL_DIR/packaging/select-to-speech-autostart.desktop" > "$AUTOSTART_DIR/select-to-speech.desktop"
update-desktop-database "$APPS_DIR" &>/dev/null || true
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi

# ── Start now (next logins use the autostart entry) ────────────────────────────
info "Starting Select-to-Speech in the background..."
setsid -f "$BIN_DIR/select-to-speech-gui" --background >/dev/null 2>&1 || true

echo ""
info "Installation complete! Select-to-Speech starts automatically at login."
echo "  Logs:    ~/.local/state/select-to-speech/app.log"
echo "  Update:  git pull && ./install-local.sh"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not in your PATH." ;; esac

# ── System Check ───────────────────────────────────────────────────────────────
echo ""
info "Running system dependencies check..."
uv run --project "$INSTALL_DIR" select-to-speech --check || true
