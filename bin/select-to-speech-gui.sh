#!/usr/bin/env bash
# Wrapper for development mode: runs via 'poetry run' from the repo directory.
# Symlinked to ~/.local/bin/select-to-speech-gui by install.sh.
# To switch to pipx: run 'pipx install .' and remove the symlinks.
REPO_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
exec poetry -C "$REPO_DIR" run select-to-speech-gui "$@"
