#!/usr/bin/env bash
# Compile the Python backend into a standalone directory with Nuitka.
#
# Output: dist/backend/ (the `select-to-speech` executable plus its .so files and data).
# Installed by the native packages as /usr/lib/select-to-speech/backend/.
#
# Requirements: the interpreter in $PYTHON must already have the project and its
# dependencies installed (see .github/workflows/release.yml), plus a C compiler,
# patchelf and (optionally) ccache.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
NUITKA_VERSION="4.3.4"
OUT_DIR="$ROOT/dist/backend"
BUILD_DIR="$ROOT/build/nuitka"

cd "$ROOT"
"$PYTHON" -m pip --version >/dev/null 2>&1 && PIP=("$PYTHON" -m pip install -q) || PIP=(uv pip install -q --python "$PYTHON")
"${PIP[@]}" "nuitka==$NUITKA_VERSION" ordered-set zstandard

NUITKA_FLAGS=(
    --standalone
    --lto=yes
    --jobs="$(nproc)"
    --assume-yes-for-downloads
    --python-flag=no_site
    --python-flag=no_docstrings
    --python-flag=no_asserts
    --nofollow-import-to=pytest,unittest,doctest,pdb,tkinter,idlelib,pulsectl.tests,sherpa_onnx.cli
    --nofollow-import-to=pynput.keyboard._darwin,pynput.keyboard._win32,pynput.mouse._darwin,pynput.mouse._win32,pynput._util.darwin,pynput._util.win32
    --include-package=select_to_speech
    --include-package=sherpa_onnx
    --include-package=uvicorn
    --include-package=fastapi
    --include-package=pydantic
    --include-package=pulsectl
    --include-package=lingua
    --include-package=pedalboard
    --include-module=pedalboard_native
    --include-package=pynput
    --include-package=Xlib
    --include-package=pyaudio
    --include-package=yaml
    --include-package=emoji
    --include-package=requests
    --include-package=urllib3
    --include-package=certifi
    --include-package-data=emoji
    --include-package-data=certifi
    --output-dir="$BUILD_DIR"
    --output-filename=select-to-speech
)

rm -rf "$BUILD_DIR/entrypoint.dist" "$OUT_DIR"
"$PYTHON" -m nuitka "${NUITKA_FLAGS[@]}" src/select_to_speech/entrypoint.py

mkdir -p "$(dirname "$OUT_DIR")"
mv "$BUILD_DIR/entrypoint.dist" "$OUT_DIR"

echo "Backend built in $OUT_DIR ($(du -sh "$OUT_DIR" | cut -f1))"
