#!/bin/sh
# nfpm cannot emit pacman optdepends, so list the optional OCR packages here.
cat <<'EOF'
==> Select to Speech: optional dependencies for screen text recognition (OCR):
      tesseract tesseract-data-eng tesseract-data-ita   OCR engine + language packs
      spectacle  (KDE)  or  grim slurp  (wlroots)        screen region capture
==> The Kokoro voice model (~350 MB) is downloaded on first use, or from Settings.
==> Run `select-to-speech --check` to verify your setup.
EOF
