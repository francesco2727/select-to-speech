#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="select-to-speech"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

# ── Systemd user service ───────────────────────────────────────────────────────
info "Disabling and stopping systemd service..."
systemctl --user disable --now "$SERVICE_NAME" &>/dev/null || true

if [ -d "$SYSTEMD_DIR" ] && [ ! -w "$SYSTEMD_DIR" ]; then
    warn "Directory $SYSTEMD_DIR is not writable. Fixing ownership..."
    sudo chown -R "$(id -u):$(id -g)" "$SYSTEMD_DIR"
fi
rm -f "$SYSTEMD_DIR/$SERVICE_NAME.service" || true
systemctl --user daemon-reload &>/dev/null || true

# ── Wrapper symlinks ───────────────────────────────────────────────────────────
info "Removing wrapper scripts..."
if [ -d "$BIN_DIR" ] && [ ! -w "$BIN_DIR" ]; then
    warn "Directory $BIN_DIR is not writable. Fixing ownership..."
    sudo chown -R "$(id -u):$(id -g)" "$BIN_DIR"
fi
rm -f "$BIN_DIR/select-to-speech-gui" || true
rm -f "$BIN_DIR/select-to-speech-settings" || true

# ── Desktop file and Icons ───────────────────────────────────────────────────
info "Removing .desktop file and icons..."
if [ -d "$APPS_DIR" ] && [ ! -w "$APPS_DIR" ]; then
    warn "Directory $APPS_DIR is not writable. Fixing ownership..."
    sudo chown -R "$(id -u):$(id -g)" "$APPS_DIR"
fi
rm -f "$APPS_DIR/select-to-speech.desktop" || true
rm -f "$APPS_DIR/com.example.ui.desktop" || true
update-desktop-database "$APPS_DIR" || true

ICONS_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
rm -f "$ICONS_DIR/select-to-speech.svg" || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" || true

# ── KDE notification config ────────────────────────────────────────────────────
NOTIFYRC="/usr/share/knotifications6/select-to-speech.notifyrc"
if [[ -f "$NOTIFYRC" ]]; then
    warn "Removing KDE notification config (requires sudo)..."
    sudo rm -f "$NOTIFYRC"
fi

# ── Application Binaries ───────────────────────────────────────────────────────
info "Removing application binaries..."
DATA_DIR="$HOME/.local/share/select-to-speech"
rm -rf "$DATA_DIR/bin" || true
rm -rf "$DATA_DIR/src" || true
rm -rf "$DATA_DIR/.venv" || true
rm -f "$DATA_DIR/select-to-speech.desktop" || true
rm -f "$DATA_DIR/select-to-speech.service" || true

echo ""
info "Uninstall complete. Config and voice files are kept in:"
echo "  ~/.config/select-to-speech/"
echo "  ~/.local/share/select-to-speech/voices/"
echo "  ~/.local/state/select-to-speech/"
warn "Remove those directories manually if you want a full clean."
