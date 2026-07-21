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

# Determine install mode
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ] && [ -d "$(dirname "${BASH_SOURCE[0]}")/.git" ]; then
    INSTALL_MODE="local"
    INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    info "Running in local development mode (git repository detected)."
else
    INSTALL_MODE="remote"
    INSTALL_DIR="$HOME/.local/share/select-to-speech"
    info "Running in remote installation mode."
fi
# ── Download App (Remote Mode) ──────────────────────────────────────────────────
if [ "$INSTALL_MODE" = "remote" ]; then
    info "Downloading latest release..."
    REPO_NAME="francesco2727/select-to-speech"
    
    mkdir -p "$INSTALL_DIR"
    
    # Get the latest release tag from GitHub API
    LATEST_TAG=$(curl -s "https://api.github.com/repos/${REPO_NAME}/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
    if [ -z "$LATEST_TAG" ]; then
        warn "Could not determine latest release, defaulting to main branch."
        TAR_URL="https://github.com/${REPO_NAME}/archive/refs/heads/main.tar.gz"
    else
        info "Found latest release: $LATEST_TAG"
        TAR_URL="https://github.com/${REPO_NAME}/archive/refs/tags/${LATEST_TAG}.tar.gz"
    fi
    
    info "Downloading from $TAR_URL..."
    curl -L -f -o "/tmp/select-to-speech.tar.gz" "$TAR_URL"
    
    info "Extracting to $INSTALL_DIR..."
    tar -xzf "/tmp/select-to-speech.tar.gz" -C "$INSTALL_DIR" --strip-components=1
    rm -f "/tmp/select-to-speech.tar.gz"
fi

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
info "Downloading Kokoro TTS model files (~350 MB)..."
if ! uv run --project "$INSTALL_DIR" select-to-speech-download; then
    warn "Failed to download Kokoro model files during installation."
    warn "You can download them manually later via the settings GUI or by running:"
    warn "  uv run select-to-speech-download"
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

# In local mode with flutter installed, compile locally. Otherwise, fetch pre-built release.
if [ "${FORCE_DOWNLOAD:-0}" != "1" ] && command -v flutter &> /dev/null && [ "$INSTALL_MODE" = "local" ]; then
    info "Compiling Flutter user interface locally (release mode)..."
    (cd "$INSTALL_DIR/src/ui" && flutter clean && flutter build linux --release)
else
    if [ ! -f "$UI_BINARY" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
        info "Downloading pre-compiled GUI from GitHub Releases..."
        REPO_NAME="francesco2727/select-to-speech"
        
        RELEASE_URL="https://github.com/${REPO_NAME}/releases/latest/download/select-to-speech-gui-linux.tar.gz"
        info "Downloading pre-compiled GUI from: $RELEASE_URL"
        mkdir -p "$UI_BUNDLE_DIR"
        if curl -L -f -o "$INSTALL_DIR/select-to-speech-gui-linux.tar.gz" "$RELEASE_URL"; then
            info "Extracting GUI bundle..."
            tar -xzf "$INSTALL_DIR/select-to-speech-gui-linux.tar.gz" -C "$UI_BUNDLE_DIR"
            rm -f "$INSTALL_DIR/select-to-speech-gui-linux.tar.gz"
            info "GUI bundle set up successfully."
        else
            error "Failed to download pre-compiled GUI from GitHub Releases."
            error "Please install the Flutter SDK to build it from source, or check your internet connection."
            rm -f "$INSTALL_DIR/select-to-speech-gui-linux.tar.gz"
            exit 1
        fi
    else
        info "Existing UI binary found. Skipping download."
    fi
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

# ── Desktop file ───────────────────────────────────────────────────────────────
info "Installing .desktop file to $APPS_DIR..."
if [ -d "$APPS_DIR" ] && [ ! -w "$APPS_DIR" ]; then
    warn "Directory $APPS_DIR is not writable. Fixing ownership..."
    sudo chown -R "$(id -u):$(id -g)" "$APPS_DIR"
fi
mkdir -p "$APPS_DIR"
sed "s|%h|$HOME|g" "$INSTALL_DIR/select-to-speech.desktop" > "$APPS_DIR/select-to-speech.desktop"

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
if [ "$INSTALL_MODE" = "local" ]; then
    echo "  To update after 'git pull':"
    echo "    systemctl --user restart $SERVICE_NAME"
else
    echo "  To update to the latest release:"
    echo "    curl -sSL https://raw.githubusercontent.com/francesco2727/select-to-speech/main/install.sh | bash"
fi
warn "Make sure $BIN_DIR is in your PATH (it usually is on KDE)."

# ── System Check ───────────────────────────────────────────────────────────────
echo ""
info "Running system dependencies check..."
uv run --project "$INSTALL_DIR" select-to-speech-check || true
