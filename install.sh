#!/usr/bin/env bash
# Install (or update) Select-to-Speech from the latest GitHub release using the
# native package for this distribution, so dependencies are resolved by the
# package manager and updates/removal go through it as well.
#
#   curl -fsSL https://raw.githubusercontent.com/francesco2727/select-to-speech/main/install.sh | bash
#
# Supported: Arch-based (pacman), Debian/Ubuntu-based (apt), Fedora/RHEL-based (dnf).
set -euo pipefail

REPO="francesco2727/select-to-speech"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }

if command -v pacman >/dev/null 2>&1; then
    kind="pkg.tar.zst"; install_cmd=(sudo pacman -U --needed)
elif command -v apt-get >/dev/null 2>&1; then
    kind="deb"; install_cmd=(sudo apt-get install -y)
elif command -v dnf >/dev/null 2>&1; then
    kind="rpm"; install_cmd=(sudo dnf install -y)
else
    error "Unsupported distribution: no pacman, apt-get or dnf found."
    error "Download a package manually from https://github.com/$REPO/releases"
    exit 1
fi

info "Looking up the latest release..."
release_json="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest")"
asset_url() { grep -o "\"browser_download_url\": *\"[^\"]*$1\"" <<<"$release_json" | head -1 | sed -E 's/.*"(https[^"]+)"/\1/'; }
pkg_url="$(asset_url "\\.$kind")"
sums_url="$(asset_url "SHA256SUMS")"
if [ -z "$pkg_url" ] || [ -z "$sums_url" ]; then
    error "The latest release has no .$kind package."
    exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
pkg="$tmp/$(basename "$pkg_url")"
info "Downloading $(basename "$pkg_url")..."
curl -fL --progress-bar -o "$pkg" "$pkg_url"
curl -fsSL -o "$tmp/SHA256SUMS" "$sums_url"
(cd "$tmp" && grep " $(basename "$pkg")\$" SHA256SUMS | sha256sum -c --quiet) || { error "Checksum mismatch"; exit 1; }

# Old per-user installs (~/.local, systemd user service, onefile caches) would shadow the package
if [ -d "$HOME/.local/share/select-to-speech/bin" ] || [ -f "$HOME/.config/systemd/user/select-to-speech.service" ] \
   || compgen -G "$HOME/.cache/select-to-speech/v*" >/dev/null; then
    info "Removing the previous per-user installation (config and voices are kept)..."
    curl -fsSL "https://raw.githubusercontent.com/$REPO/main/uninstall.sh" | bash -s -- --quiet
fi

info "Installing with: ${install_cmd[*]} (sudo password may be required)"
"${install_cmd[@]}" "$pkg"

info "Starting Select-to-Speech (it also starts automatically at login)..."
setsid -f /usr/bin/select-to-speech-gui --background >/dev/null 2>&1 || true

echo ""
/usr/bin/select-to-speech --check || true
