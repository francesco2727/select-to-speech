#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="select-to-speech"
INSTALL_DIR="$HOME/.local/share/select-to-speech"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }

info "Running in remote installation mode."

# ── Download Source ─────────────────────────────────────────────────────────────
info "Downloading latest release..."
REPO_NAME="francesco2727/select-to-speech"

mkdir -p "$INSTALL_DIR"

LATEST_TAG=$(curl -s "https://api.github.com/repos/${REPO_NAME}/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
if [ -z "$LATEST_TAG" ]; then
    warn "Could not determine latest release, defaulting to main branch."
    TAR_URL="https://github.com/${REPO_NAME}/archive/refs/heads/main.tar.gz"
else
    info "Found latest release: $LATEST_TAG"
    TAR_URL="https://github.com/${REPO_NAME}/archive/refs/tags/${LATEST_TAG}.tar.gz"
fi

info "Downloading source from $TAR_URL..."
curl -L -f -o "/tmp/select-to-speech.tar.gz" "$TAR_URL"

info "Extracting to $INSTALL_DIR..."
tar -xzf "/tmp/select-to-speech.tar.gz" -C "$INSTALL_DIR" --strip-components=1
rm -f "/tmp/select-to-speech.tar.gz"

# ── Stop running service before replacing binaries ─────────────────────────────
if systemctl --user is-active --quiet select-to-speech 2>/dev/null; then
    info "Stopping running select-to-speech service before update..."
    systemctl --user stop select-to-speech || true
    sleep 1
fi

# ── Download Backend ──────────────────────────────────────────────────────────
BACKEND_URL="https://github.com/${REPO_NAME}/releases/latest/download/select-to-speech-backend-linux.tar.gz"
info "Downloading pre-compiled Backend from: $BACKEND_URL"
mkdir -p "$INSTALL_DIR/bin"
if curl -L -f -o "$INSTALL_DIR/select-to-speech-backend-linux.tar.gz" "$BACKEND_URL"; then
    info "Extracting Backend..."
    tar -xzf "$INSTALL_DIR/select-to-speech-backend-linux.tar.gz" -C "$INSTALL_DIR/bin"
    rm -f "$INSTALL_DIR/select-to-speech-backend-linux.tar.gz"
else
    error "Failed to download Backend from GitHub Releases."
    exit 1
fi

# Create a dummy .venv for the GUI to find the backend binary without modifying main.dart
mkdir -p "$INSTALL_DIR/.venv/bin"
ln -sf "$INSTALL_DIR/bin/select-to-speech" "$INSTALL_DIR/.venv/bin/select-to-speech"

# ── Download Kokoro models ─────────────────────────────────────────────────────
info "Downloading Kokoro TTS model files (~350 MB)..."
if ! "$INSTALL_DIR/bin/select-to-speech-download"; then
    warn "Failed to download Kokoro model files during installation."
    warn "You can download them manually later via the settings GUI or by running:"
    warn "  $INSTALL_DIR/bin/select-to-speech-download"
fi

# ── Download Flutter UI ────────────────────────────────────────────────────────
info "Setting up Flutter UI..."
UI_BUNDLE_DIR="$INSTALL_DIR/src/ui/build/linux/x64/release/bundle"
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
echo "  To update to the latest release:"
echo "    curl -sSL https://raw.githubusercontent.com/francesco2727/select-to-speech/main/install.sh | bash"
warn "Make sure $BIN_DIR is in your PATH (it usually is on KDE)."
echo ""
info "To uninstall, run:"
info "  $INSTALL_DIR/uninstall.sh"

# ── System Check ───────────────────────────────────────────────────────────────
echo ""
info "Running system dependencies check..."
"$INSTALL_DIR/bin/select-to-speech-check" || true
