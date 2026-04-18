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
if systemctl --user is-enabled "$SERVICE_NAME" &>/dev/null; then
    info "Disabling and stopping systemd service..."
    systemctl --user disable --now "$SERVICE_NAME"
fi
rm -f "$SYSTEMD_DIR/$SERVICE_NAME.service"
systemctl --user daemon-reload

# ── Wrapper symlinks ───────────────────────────────────────────────────────────
info "Removing wrapper scripts..."
rm -f "$BIN_DIR/select-to-speech-gui"
rm -f "$BIN_DIR/select-to-speech-settings"

# ── Desktop file ───────────────────────────────────────────────────────────────
info "Removing .desktop file..."
rm -f "$APPS_DIR/select-to-speech.desktop"

# ── KDE notification config ────────────────────────────────────────────────────
NOTIFYRC="/usr/share/knotifications6/select-to-speech.notifyrc"
if [[ -f "$NOTIFYRC" ]]; then
    warn "Removing KDE notification config (requires sudo)..."
    sudo rm -f "$NOTIFYRC"
fi

echo ""
info "Uninstall complete. Config and voice files are kept in:"
echo "  ~/.config/select-to-speech/"
echo "  ~/.local/share/select-to-speech/"
echo "  ~/.local/state/select-to-speech/"
warn "Remove those directories manually if you want a full clean."
