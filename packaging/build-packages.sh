#!/usr/bin/env bash
# Build the native packages (.deb, .rpm, .pkg.tar.zst) from dist/backend and dist/gui.
#
# Usage: packaging/build-packages.sh [VERSION]
#   VERSION defaults to the latest git tag without the leading "v" (e.g. 0.6.0).
# Output: dist/packages/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NFPM_VERSION="2.47.0"
NFPM_SHA256="0660ca602b2d2d2ae4781a06c692b3eeb9d437ffea05b831d76e41f4a3188783"
OUT_DIR="$ROOT/dist/packages"

cd "$ROOT"
VERSION="${1:-$(git describe --tags --abbrev=0 2>/dev/null || echo v0.0.0)}"
export VERSION="${VERSION#v}"

for d in dist/backend dist/gui; do
    [ -d "$d" ] || { echo "$d missing: run packaging/build-backend.sh and packaging/build-gui.sh first" >&2; exit 1; }
done

NFPM="$(command -v nfpm || true)"
if [ -z "$NFPM" ]; then
    NFPM="$ROOT/build/nfpm/nfpm"
    if [ ! -x "$NFPM" ]; then
        mkdir -p "$(dirname "$NFPM")"
        tarball="$(dirname "$NFPM")/nfpm.tar.gz"
        curl -sSfL --retry 5 --retry-delay 5 --retry-all-errors -o "$tarball" \
            "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VERSION}/nfpm_${NFPM_VERSION}_Linux_x86_64.tar.gz"
        echo "$NFPM_SHA256  $tarball" | sha256sum -c --quiet
        tar -xzf "$tarball" -C "$(dirname "$NFPM")" nfpm
        rm -f "$tarball"
    fi
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
for packager in deb rpm archlinux; do
    "$NFPM" package --config packaging/nfpm.yaml --packager "$packager" --target "$OUT_DIR/"
done

(cd "$OUT_DIR" && sha256sum -- * > SHA256SUMS)
ls -lh "$OUT_DIR"
