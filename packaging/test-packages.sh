#!/usr/bin/env bash
# Smoke-test the native packages in clean distro containers (requires docker).
#
# For each distro: install the package with its package manager (so the declared
# dependency names are validated), then check that
#   - every bundled ELF resolves all its shared libraries (ldd: no "not found"),
#   - the CLI runs (--help, --check, --audio-devices: loads pyaudio/portaudio),
#   - the daemon imports its whole stack (lingua, sherpa-onnx, fastapi) and answers
#     /status on its socket, then exits on SIGTERM,
#   - the .desktop files are valid.
#
# Usage: packaging/test-packages.sh [distro ...]   (default: all)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$ROOT/dist/packages"
DISTROS=("${@:-debian:12 ubuntu:22.04 ubuntu:24.04 fedora:42 archlinux:latest}")
read -r -a DISTROS <<< "${DISTROS[*]}"

deb="$(cd "$PKG_DIR" && ls select-to-speech_*.deb)"
rpm="$(cd "$PKG_DIR" && ls select-to-speech-*.rpm)"
arch="$(cd "$PKG_DIR" && ls select-to-speech-*.pkg.tar.zst)"

# Runs inside the container after installation.
read -r -d '' CHECKS <<'EOF' || true
set -eu
fail=0
# A library ldd cannot resolve is only a problem if it is not shipped in the bundle:
# Nuitka and Flutter load bundled libraries by soname from the top-level directories,
# which ldd (RPATH only) does not see.
bundled=$(find /usr/lib/select-to-speech -name '*.so*' -printf '%f\n' | sort -u)
missing=$(find /usr/lib/select-to-speech -type f \( -name '*.so*' -o -perm -u+x \) -exec sh -c \
    'file -b "$1" | grep -q ELF && ldd "$1" 2>/dev/null | awk -v f="$1" "/not found/ {print \$1, f}"' _ {} \; \
    | while read -r lib file; do printf '%s\n' "$bundled" | grep -qxF "$lib" || echo "$lib (needed by $file)"; done | sort -u)
if [ -n "$missing" ]; then echo "UNRESOLVED LIBRARIES:"; echo "$missing"; fail=1; fi

select-to-speech --help >/dev/null
select-to-speech --check --lang en >/tmp/check.log 2>&1 || true   # no voice model in CI: non-zero is expected
grep -q "SYSTEM DEPENDENCIES CHECK" /tmp/check.log
select-to-speech --audio-devices >/dev/null 2>&1 || { echo "--audio-devices failed"; fail=1; }

# Daemon: start headless (Xvfb for pynput's X backend), wait for /status, stop it.
export HOME=/tmp/home; mkdir -p "$HOME"
Xvfb :99 >/dev/null 2>&1 & export DISPLAY=:99
select-to-speech >/tmp/daemon.log 2>&1 & pid=$!
sock="$HOME/.local/state/select-to-speech/ipc.sock"; ok=0
for _ in $(seq 1 120); do
    if [ -S "$sock" ] && curl -s --unix-socket "$sock" http://localhost/status | grep -q '"ok"'; then ok=1; break; fi
    sleep 0.25
done
if [ "$ok" = 1 ]; then
    kill -TERM "$pid"
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    if kill -0 "$pid" 2>/dev/null; then echo "daemon ignored SIGTERM"; fail=1; kill -9 "$pid"; fi
else
    echo "daemon did not answer /status:"; tail -30 /tmp/daemon.log; fail=1
fi

# GUI: must start under a session bus and launch the packaged backend.
cat >/tmp/gui-test.sh <<'GUI'
select-to-speech-gui --background >/tmp/gui.log 2>&1 & gui=$!
for _ in $(seq 1 120); do
    if [ -S "$HOME/.local/state/select-to-speech/ipc.sock" ] \
       && curl -s --unix-socket "$HOME/.local/state/select-to-speech/ipc.sock" http://localhost/status | grep -q '"ok"'; then break; fi
    sleep 0.25
done
for p in /proc/[0-9]*; do readlink "$p/exe"; done 2>/dev/null | grep -qx /usr/lib/select-to-speech/backend/select-to-speech \
    || { echo "GUI did not start the packaged backend:"; tail -20 /tmp/gui.log; exit 1; }
kill -0 "$gui" || { echo "GUI exited:"; tail -20 /tmp/gui.log; exit 1; }
GUI
rm -f "$HOME/.local/state/select-to-speech/ipc.sock"
dbus-run-session -- sh /tmp/gui-test.sh || fail=1

desktop-file-validate /usr/share/applications/select-to-speech-gui.desktop /etc/xdg/autostart/select-to-speech.desktop || fail=1
[ -L /usr/bin/select-to-speech-gui ] && [ -x /usr/lib/select-to-speech/gui/select-to-speech-gui ] || { echo "GUI not installed"; fail=1; }
exit $fail
EOF

result=0
for distro in "${DISTROS[@]}"; do
    case "$distro" in
        debian*|ubuntu*)
            install="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends /pkgs/$deb file curl xvfb desktop-file-utils dbus >/dev/null" ;;
        fedora*)
            install="dnf install -y -q --setopt=install_weak_deps=False /pkgs/$rpm file curl xorg-x11-server-Xvfb desktop-file-utils dbus-daemon >/dev/null" ;;
        archlinux*)
            install="pacman -Syu --noconfirm --needed file curl xorg-server-xvfb desktop-file-utils dbus >/dev/null && pacman -U --noconfirm /pkgs/$arch" ;;
        *) echo "unknown distro $distro" >&2; exit 2 ;;
    esac
    echo "=== $distro"
    if docker run --rm -v "$PKG_DIR":/pkgs:ro "$distro" sh -c "$install && $CHECKS"; then
        echo "=== $distro: OK"
    else
        echo "=== $distro: FAILED"; result=1
    fi
done
exit $result
