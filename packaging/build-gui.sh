#!/usr/bin/env bash
# Build the Flutter Linux GUI bundle.
#
# Output: dist/gui/ (select-to-speech-gui, lib/, data/), installed by the native
# packages as /usr/lib/select-to-speech/gui/. Dart debug symbols are split out of
# libapp.so into build/gui-symbols/ (smaller bundle; keep them to symbolize crash traces).
#
# Requirements: Flutter SDK, clang, cmake, ninja, pkg-config, libgtk-3-dev,
# libayatana-appindicator3-dev, patchelf.
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

# The tray plugin is linked on Ubuntu against libayatana-indicator3 / libayatana-ido3,
# which are only transitive dependencies of libayatana-appindicator3 and do not exist
# under those sonames on Arch/Fedora. Drop them so the bundle loads everywhere.
patchelf --remove-needed libayatana-indicator3.so.7 \
         --remove-needed libayatana-ido3-0.4.so.0 \
         --set-rpath '$ORIGIN' \
         "$BUNDLE_DIR/lib/libtray_manager_plugin.so"

rm -rf "$OUT_DIR"
mkdir -p "$(dirname "$OUT_DIR")"
cp -a "$BUNDLE_DIR" "$OUT_DIR"

echo "GUI built in $OUT_DIR ($(du -sh "$OUT_DIR" | cut -f1))"
