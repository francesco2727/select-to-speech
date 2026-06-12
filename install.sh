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
for pkg in wl-clipboard libayatana-appindicator; do
    pacman -Qi "$pkg" &>/dev/null || MISSING_PKGS+=("$pkg")
done

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    warn "Installing missing system packages: ${MISSING_PKGS[*]}"
    sudo pacman -S --needed "${MISSING_PKGS[@]}"
fi

# ── uv install ─────────────────────────────────────────────────────────────────
if ! command -v uv &> /dev/null; then
    warn "uv is not installed. Attempting to install uv automatically..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &> /dev/null; then
        error "Failed to install uv. Please install it manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
fi

info "Setting up virtual environment with system packages..."
uv venv --allow-existing --system-site-packages "$REPO_DIR/.venv"
info "Running uv sync..."
uv sync --project "$REPO_DIR"

# Translations compilation removed (no longer used)

# ── Download Kokoro models ─────────────────────────────────────────────────────
info "Downloading Kokoro TTS model files (~350 MB)..."
if ! uv run --project "$REPO_DIR" select-to-speech-download; then
    warn "Failed to download Kokoro model files during installation."
    warn "You can download them manually later via the settings GUI or by running:"
    warn "  uv run select-to-speech-download"
fi

# ── Build Flutter UI ───────────────────────────────────────────────────────────
info "Setting up Flutter UI..."
UI_BINARY="$REPO_DIR/src/ui/build/linux/x64/release/bundle/ui"
UI_BUNDLE_DIR="$REPO_DIR/src/ui/build/linux/x64/release/bundle"

if [ -f "$UI_BINARY" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    info "Found existing UI binary, skipping build."
else
    if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
        info "Force download enabled. Cleaning local UI bundle..."
        rm -rf "$UI_BUNDLE_DIR"
    fi

    if ! command -v flutter &> /dev/null; then
        if [ -d "$HOME/develop/flutter/bin" ]; then
            export PATH="$HOME/develop/flutter/bin:$PATH"
        fi
    fi

    if [ "${FORCE_DOWNLOAD:-0}" != "1" ] && command -v flutter &> /dev/null; then
        info "Compiling Flutter user interface locally (release mode)..."
        (cd "$REPO_DIR/src/ui" && flutter clean && flutter build linux --release)
    else
        info "Flutter SDK not found. Attempting to download pre-compiled GUI from GitHub Releases..."
        REPO_NAME="francesco2727/select-to-speech"
        if command -v git &> /dev/null; then
            REMOTE_URL=$(git config --get remote.origin.url || true)
            if [[ "$REMOTE_URL" =~ github.com[:/]([^/]+/[^/]+)(\.git)?$ ]]; then
                REPO_NAME="${BASH_REMATCH[1]}"
                REPO_NAME="${REPO_NAME%.git}"
            fi
        fi
        
        RELEASE_URL="https://github.com/${REPO_NAME}/releases/latest/download/select-to-speech-gui-linux.tar.gz"
        info "Downloading pre-compiled GUI from: $RELEASE_URL"
        mkdir -p "$UI_BUNDLE_DIR"
        if curl -L -f -o "$REPO_DIR/select-to-speech-gui-linux.tar.gz" "$RELEASE_URL"; then
            info "Extracting GUI bundle..."
            tar -xzf "$REPO_DIR/select-to-speech-gui-linux.tar.gz" -C "$UI_BUNDLE_DIR"
            rm -f "$REPO_DIR/select-to-speech-gui-linux.tar.gz"
            info "GUI bundle set up successfully."
        else
            error "Failed to download pre-compiled GUI from GitHub Releases."
            error "Please install the Flutter SDK to build it from source, or check your internet connection."
            rm -f "$REPO_DIR/select-to-speech-gui-linux.tar.gz"
            exit 1
        fi
    fi
fi

# ── Wrapper symlinks ───────────────────────────────────────────────────────────
info "Installing wrapper scripts to $BIN_DIR..."
if [ -d "$BIN_DIR" ] && [ ! -w "$BIN_DIR" ]; then
    warn "Directory $BIN_DIR is not writable. Fixing ownership..."
    sudo chown -R "$(id -u):$(id -g)" "$BIN_DIR"
fi
mkdir -p "$BIN_DIR"
chmod +x "$REPO_DIR/bin/select-to-speech-gui.sh"
chmod +x "$REPO_DIR/bin/select-to-speech-settings.sh"
ln -sf "$REPO_DIR/bin/select-to-speech-gui.sh"      "$BIN_DIR/select-to-speech-gui"
ln -sf "$REPO_DIR/bin/select-to-speech-settings.sh" "$BIN_DIR/select-to-speech-settings"

# ── Desktop file ───────────────────────────────────────────────────────────────
# %h is a systemd variable, not valid in .desktop files — substitute $HOME here.
info "Installing .desktop file to $APPS_DIR..."
if [ -d "$APPS_DIR" ] && [ ! -w "$APPS_DIR" ]; then
    warn "Directory $APPS_DIR is not writable. Fixing ownership..."
    sudo chown -R "$(id -u):$(id -g)" "$APPS_DIR"
fi
mkdir -p "$APPS_DIR"
sed "s|%h|$HOME|g" "$REPO_DIR/select-to-speech.desktop" > "$APPS_DIR/select-to-speech.desktop"

# KDE notification config removed (no longer used)

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
