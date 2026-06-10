#!/usr/bin/env bash
REPO_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
exec "$REPO_DIR/src/ui/build/linux/x64/release/bundle/ui" "$@"
