#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="select-to-speech"

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
uv venv --allow-existing --system-site-packages "$INSTALL_DIR/.venv"
info "Running uv sync..."
uv sync --project "$INSTALL_DIR"

# ── Download Kokoro models ─────────────────────────────────────────────────────
info "Downloading Kokoro TTS model files (~340 MB)..."
if ! uv run --project "$INSTALL_DIR" select-to-speech-download --model kokoro-v1.0; then
    warn "Failed to download Kokoro model files during installation."
    warn "You can download them manually later via the settings GUI or by running:"
    warn "  uv run select-to-speech-download --model kokoro-v1.0"
fi

# ── Build/Download Flutter UI ───────────────────────────────────────────────────
info "Setting up Flutter UI..."
UI_BINARY="$INSTALL_DIR/src/ui/build/linux/x64/release/bundle/ui"
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

# ── Wrapper symlinks ───────────────────────────────────────────────────────────
info "Installing wrapper scripts to $BIN_DIR..."
if [ -d "$BIN_DIR" ] && [ ! -w "$BIN_DIR" ]; then
    warn "Directory $BIN_DIR is not writable. Fixing ownership..."
    sudo chown -R "$(id -u):$(id -g)" "$BIN_DIR"
fi
mkdir -p "$BIN_DIR"
chmod +x "$INSTALL_DIR/bin/select-to-speech-gui.sh"
chmod +x "$INSTALL_DIR/bin/select-to-speech-settings.sh"
ln -sf "$INSTALL_DIR/bin/select-to-speech-gui.sh"      "$BIN_DIR/select-to-speech-gui"
ln -sf "$INSTALL_DIR/bin/select-to-speech-settings.sh" "$BIN_DIR/select-to-speech-settings"

# ── Desktop file and Icons ─────────────────────────────────────────────────────
info "Installing icon to ~/.local/share/icons..."
ICONS_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICONS_DIR"
cp "$INSTALL_DIR/src/ui/images/select_to_speech_tray_icon.svg" "$ICONS_DIR/select-to-speech.svg"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" || true

info "Installing .desktop file to $APPS_DIR..."
if [ -d "$APPS_DIR" ] && [ ! -w "$APPS_DIR" ]; then
    warn "Directory $APPS_DIR is not writable. Fixing ownership..."
    sudo chown -R "$(id -u):$(id -g)" "$APPS_DIR"
fi
mkdir -p "$APPS_DIR"
sed "s|%h|$HOME|g" "$INSTALL_DIR/select-to-speech.desktop" > "$APPS_DIR/select-to-speech.desktop"
# Create a symlink for Wayland to match the default Flutter app_id
ln -sf "$APPS_DIR/select-to-speech.desktop" "$APPS_DIR/com.example.ui.desktop"
update-desktop-database "$APPS_DIR" || true

# ── Systemd user service ───────────────────────────────────────────────────────
info "Installing systemd user service..."
mkdir -p "$SYSTEMD_DIR"
cp "$INSTALL_DIR/select-to-speech.service" "$SYSTEMD_DIR/$SERVICE_NAME.service"
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME" || true

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
info "Installation complete!"
echo ""
echo "  Status:    systemctl --user status $SERVICE_NAME"
echo "  Logs:      journalctl --user -u $SERVICE_NAME -f"
echo "  Restart:   systemctl --user restart $SERVICE_NAME"
echo ""
echo "  To update after 'git pull':"
echo "    systemctl --user restart $SERVICE_NAME"
warn "Make sure $BIN_DIR is in your PATH (it usually is on KDE)."

# ── System Check ───────────────────────────────────────────────────────────────
echo ""
info "Running system dependencies check..."
uv run --project "$INSTALL_DIR" select-to-speech-check || true
