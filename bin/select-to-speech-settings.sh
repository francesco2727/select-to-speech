#!/usr/bin/env bash
# Wrapper for development mode: runs via 'uv run' from the repo directory.
# Symlinked to ~/.local/bin/select-to-speech-settings by install.sh.
REPO_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
exec "$REPO_DIR/.venv/bin/select-to-speech-settings" "$@"
