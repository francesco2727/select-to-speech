#!/usr/bin/env bash
REPO_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
BUNDLE_DIR="$REPO_DIR/src/ui/build/linux/x64/release/bundle"
export LD_LIBRARY_PATH="$BUNDLE_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$BUNDLE_DIR/ui" --settings "$@"
