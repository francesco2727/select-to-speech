#!/usr/bin/env bash
REPO_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
exec "$REPO_DIR/.venv/bin/select-to-speech" "$@"
