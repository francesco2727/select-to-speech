#!/usr/bin/env bash
# Wrapper for development mode: runs via 'poetry run' from the repo directory.
# Symlinked to ~/.local/bin/select-to-speech-settings by install.sh.
REPO_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
exec poetry -C "$REPO_DIR" run select-to-speech-settings "$@"
