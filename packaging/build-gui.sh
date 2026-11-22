#!/usr/bin/env bash
# Build the Flutter Linux GUI bundle.
#
# Output: dist/gui/ (select-to-speech-gui, lib/, data/), installed by the native
# packages as /usr/lib/select-to-speech/gui/. Dart debug symbols are split out of
# libapp.so into build/gui-symbols/ (smaller bundle; keep them to symbolize crash traces).
#
# Requirements: Flutter SDK, clang, cmake, ninja, pkg-config, libgtk-3-dev,
# libx11-dev, libxi-dev (the tray icon's native code, built by the cnativeapi hook).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="$ROOT/src/ui"
BUNDLE_DIR="$UI_DIR/build/linux/x64/release/bundle"
OUT_DIR="$ROOT/dist/gui"
SYMBOLS_DIR="$ROOT/build/gui-symbols"

mkdir -p "$SYMBOLS_DIR"
cd "$UI_DIR"
flutter pub get
flutter build linux --release --split-debug-info="$SYMBOLS_DIR"

# libdartjni.so comes from the `jni` package (transitive, Android-only use via dynamic_color)
# and needs libjvm.so, which does not exist on desktops. Nothing uses it on Linux.
rm -f "$BUNDLE_DIR/lib/libdartjni.so"

rm -rf "$OUT_DIR"
mkdir -p "$(dirname "$OUT_DIR")"
cp -a "$BUNDLE_DIR" "$OUT_DIR"

echo "GUI built in $OUT_DIR ($(du -sh "$OUT_DIR" | cut -f1))"
