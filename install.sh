#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_NAME="select-to-speech"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }

# ── System dependencies ────────────────────────────────────────────────────────
info "Checking system dependencies..."
MISSING_PKGS=()
for pkg in gettext pyside6 shiboken6 wl-clipboard; do
    pacman -Qi "$pkg" &>/dev/null || MISSING_PKGS+=("$pkg")
done

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    warn "Installing missing system packages: ${MISSING_PKGS[*]}"
    sudo pacman -S --needed "${MISSING_PKGS[@]}"
fi

# ── uv install ─────────────────────────────────────────────────────────────────
info "Setting up virtual environment with system packages..."
uv venv --allow-existing --system-site-packages "$REPO_DIR/.venv"
info "Running uv sync..."
uv sync --project "$REPO_DIR"

# ── Compile translations ───────────────────────────────────────────────────────
info "Compiling translations..."
if which msgfmt &>/dev/null; then
    for po_file in "$REPO_DIR"/src/select_to_speech/locale/*/LC_MESSAGES/*.po; do
        if [[ -f "$po_file" ]]; then
            mo_file="${po_file%.po}.mo"
            info "  Compiling $po_file -> $mo_file"
            msgfmt -o "$mo_file" "$po_file"
        fi
    done
else
    warn "msgfmt not found, translations will be compiled at runtime if msgfmt becomes available."
fi

# ── Download Kokoro models ─────────────────────────────────────────────────────
info "Downloading Kokoro TTS model files (~350 MB)..."
if ! uv run --project "$REPO_DIR" select-to-speech-download; then
    warn "Failed to download Kokoro model files during installation."
    warn "You can download them manually later via the settings GUI or by running:"
    warn "  uv run select-to-speech-download"
fi

# ── Wrapper symlinks ───────────────────────────────────────────────────────────
info "Installing wrapper scripts to $BIN_DIR..."
mkdir -p "$BIN_DIR"
chmod +x "$REPO_DIR/bin/select-to-speech-gui.sh"
chmod +x "$REPO_DIR/bin/select-to-speech-settings.sh"
ln -sf "$REPO_DIR/bin/select-to-speech-gui.sh"      "$BIN_DIR/select-to-speech-gui"
ln -sf "$REPO_DIR/bin/select-to-speech-settings.sh" "$BIN_DIR/select-to-speech-settings"

# ── Desktop file ───────────────────────────────────────────────────────────────
# %h is a systemd variable, not valid in .desktop files — substitute $HOME here.
info "Installing .desktop file to $APPS_DIR..."
mkdir -p "$APPS_DIR"
sed "s|%h|$HOME|g" "$REPO_DIR/select-to-speech.desktop" > "$APPS_DIR/select-to-speech.desktop"

# ── KDE notification config ────────────────────────────────────────────────────
NOTIFYRC_DEST="/usr/share/knotifications6/select-to-speech.notifyrc"
if [[ ! -f "$NOTIFYRC_DEST" ]]; then
    info "Installing KDE notification config (requires sudo)..."
    sudo cp "$REPO_DIR/select-to-speech.notifyrc" "$NOTIFYRC_DEST"
else
    info "KDE notification config already installed, skipping."
fi

# ── Systemd user service ───────────────────────────────────────────────────────
info "Installing systemd user service..."
mkdir -p "$SYSTEMD_DIR"
cp "$REPO_DIR/select-to-speech.service" "$SYSTEMD_DIR/$SERVICE_NAME.service"
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME"

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
echo ""
warn "Make sure $BIN_DIR is in your PATH (it usually is on KDE)."
