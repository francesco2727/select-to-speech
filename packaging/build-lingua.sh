#!/usr/bin/env bash
# Build a slim lingua-language-detector wheel that only embeds the language models
# the app can actually speak (the keys of _LINGUA_LANGUAGES in main.py), and install
# it into $PYTHON's environment in place of the stock 290 MB PyPI wheel.
#
# The PyPI wheel compiles the n-gram models of all 75 languages into its extension
# module; restricting the Cargo features shrinks it to a fraction of that size.
# tests/test_packaging.py checks that LANGUAGES stays in sync with main.py.
#
# Requirements: cargo (Rust toolchain), git, and $PYTHON with the project installed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
# Absolute path (without resolving venv symlinks): the script cd-s into other directories.
PYTHON="$(realpath -s "$(command -v "$PYTHON")")"

# lingua-rs v1.8.0 == lingua-language-detector 2.2.0 on PyPI (pinned in uv.lock)
LINGUA_REPO="https://github.com/pemistahl/lingua-rs.git"
LINGUA_TAG="v1.8.0"
LINGUA_COMMIT="77e94d1a2a8e49bed873a7c502bcb51ba803ef0f"
MATURIN_VERSION="1.15.0"

LANGUAGES=(english italian spanish french german portuguese hindi japanese korean chinese)

SRC_DIR="$ROOT/build/lingua-rs"
WHEEL_DIR="$ROOT/build/lingua-wheel"

if [ ! -d "$SRC_DIR/.git" ]; then
    git clone --quiet --depth 1 --branch "$LINGUA_TAG" "$LINGUA_REPO" "$SRC_DIR"
fi
actual="$(git -C "$SRC_DIR" rev-parse HEAD)"
if [ "$actual" != "$LINGUA_COMMIT" ]; then
    echo "lingua-rs checkout is at $actual, expected $LINGUA_COMMIT" >&2
    exit 1
fi

"$PYTHON" -m pip --version >/dev/null 2>&1 && PIP=("$PYTHON" -m pip install -q) || PIP=(uv pip install -q --python "$PYTHON")
"${PIP[@]}" "maturin==$MATURIN_VERSION"

features="pyo3/extension-module,python,$(IFS=,; echo "${LANGUAGES[*]}")"
rm -rf "$WHEEL_DIR"
(cd "$SRC_DIR" && "$PYTHON" -m maturin build --release --locked \
    --no-default-features --features "$features" \
    --interpreter "$PYTHON" --compatibility off --out "$WHEEL_DIR")

"${PIP[@]}" --reinstall --no-deps "$WHEEL_DIR"/lingua_language_detector-*.whl
echo "Slim lingua installed ($(du -h "$WHEEL_DIR"/*.whl | cut -f1) wheel, ${#LANGUAGES[@]} languages)"
