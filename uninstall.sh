#!/usr/bin/env bash
# Remove a per-user (~/.local) installation of Select-to-Speech:
#   - the legacy install.sh layout (<= v0.5: onefile binary in ~/.local/share/select-to-speech,
#     systemd user service, wrapper scripts),
#   - the development install made by install-local.sh,
#   - the onefile extraction caches (~/.cache/select-to-speech/v*, ~520 MB each).
#
# The native package (.deb/.rpm/Arch) is NOT touched: remove it with your package manager.
# Config, voice models and logs are kept unless --purge is given.
#
# Usage: uninstall.sh [--purge] [--quiet]
set -euo pipefail

PURGE=0; QUIET=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        --quiet) QUIET=1 ;;
        *) echo "Usage: $0 [--purge] [--quiet]" >&2; exit 2 ;;
    esac
done

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { [ "$QUIET" = 1 ] || echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
DATA_DIR="$HOME/.local/share/select-to-speech"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/com.selecttospeech.gui.svg"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/select-to-speech.desktop"
SERVICE="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/select-to-speech.service"

# ── Stop running instances started from ~/.local ──────────────────────────────
if [ -f "$SERVICE" ]; then
    info "Disabling legacy systemd user service..."
    systemctl --user disable --now select-to-speech &>/dev/null || true
    rm -f "$SERVICE"
    systemctl --user daemon-reload &>/dev/null || true
fi
# Legacy onefile backend, dev GUI bundle, dev backend (python .venv/bin/select-to-speech)
for pattern in "$DATA_DIR/bin/select-to-speech" \
               "/src/ui/build/linux/x64/release/bundle/select-to-speech-gui" \
               "/\.venv/bin/select-to-speech( |$)"; do
    pkill -f "$pattern" 2>/dev/null || true
done

# ── Launchers, desktop entries, autostart, icon ────────────────────────────────
info "Removing launchers, desktop entries and autostart entry..."
for f in "$BIN_DIR/select-to-speech-gui" "$BIN_DIR/select-to-speech-settings"; do
    # Only remove our own links/wrappers, never an unrelated file with the same name
    if [ -L "$f" ] || grep -qs "select-to-speech" "$f"; then rm -f "$f"; fi
done
rm -f "$APPS_DIR/select-to-speech.desktop" "$APPS_DIR/select-to-speech-gui.desktop" \
      "$APPS_DIR/com.example.ui.desktop" "$AUTOSTART" "$ICON"
# Old icon name (clashed with the Breeze "select" icon) and its stale PNGs
rm -f "$HOME"/.local/share/icons/hicolor/*/apps/select-to-speech.{png,svg}
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" &>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" &>/dev/null || true

# ── Legacy install.sh payload (binaries + downloaded source tree) ──────────────
if [ -d "$DATA_DIR" ]; then
    info "Removing legacy application files from $DATA_DIR..."
    find "$DATA_DIR" -mindepth 1 -maxdepth 1 ! -name voices ! -name punctuation -exec rm -rf {} +
fi

# ── Onefile extraction caches ──────────────────────────────────────────────────
if compgen -G "$HOME/.cache/select-to-speech/v*" >/dev/null; then
    info "Removing onefile extraction caches ($(du -sch "$HOME"/.cache/select-to-speech/v* | tail -1 | cut -f1))..."
    rm -rf "$HOME"/.cache/select-to-speech/v*
    rmdir "$HOME/.cache/select-to-speech" 2>/dev/null || true
fi

if [ "$PURGE" = 1 ]; then
    info "Purging config, voice models and logs..."
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/select-to-speech" "$DATA_DIR" "$HOME/.local/state/select-to-speech"
elif [ "$QUIET" = 0 ]; then
    echo ""
    info "Done. Config, voice models and logs are kept in:"
    echo "  ~/.config/select-to-speech/"
    echo "  ~/.local/share/select-to-speech/{voices,punctuation}/"
    echo "  ~/.local/state/select-to-speech/"
    echo "  (run with --purge to remove them too)"
fi
