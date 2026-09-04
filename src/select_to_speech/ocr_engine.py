"""OCR Engine using Tesseract CLI"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


def _find_windows_tesseract() -> Optional[str]:
    """Look for tesseract executable in standard Windows install directories."""
    paths_to_check = []
    
    # 1. Check PATH first
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path

    # 2. Check standard Program Files and AppData locations
    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "ProgramData"):
        base = os.environ.get(env_var)
        if base:
            if env_var == "LOCALAPPDATA":
                candidate = Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
            elif env_var == "ProgramData":
                candidate = Path(base) / "chocolatey" / "bin" / "tesseract.exe"
            else:
                candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            paths_to_check.append(candidate)

    # 3. Check Scoop install locations in user profile
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        paths_to_check.append(Path(user_profile) / "scoop" / "shims" / "tesseract.exe")
        paths_to_check.append(Path(user_profile) / "scoop" / "apps" / "tesseract" / "current" / "tesseract.exe")

    # 4. Hardcoded standard fallbacks if env vars are missing
    paths_to_check.extend([
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
        Path("C:/ProgramData/chocolatey/bin/tesseract.exe"),
    ])

    for candidate in paths_to_check:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    return None


class OcrEngine:
    """Extracts text from images using native Tesseract CLI (to keep uv environment lightweight)."""

    def __init__(self, default_languages: str = "ita+eng", tesseract_cmd: Optional[str] = None):
        self.default_languages = default_languages
        self._custom_tesseract_cmd = tesseract_cmd
        self._available_langs: Optional[set[str]] = None

    def get_tesseract_cmd(self) -> Optional[str]:
        """Resolve tesseract executable command path."""
        if self._custom_tesseract_cmd:
            return self._custom_tesseract_cmd
        if sys.platform == "win32":
            return _find_windows_tesseract()
        return shutil.which("tesseract")

    def is_available(self) -> bool:
        """Check if tesseract CLI is installed and available."""
        return self.get_tesseract_cmd() is not None

    def get_available_languages(self) -> set[str]:
        """Check available tesseract language data packs."""
        cmd_path = self.get_tesseract_cmd()
        if not cmd_path:
            self._available_langs = set()
            return self._available_langs

        try:
            res = subprocess.run(
                [cmd_path, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                # First line is usually "List of available languages (N):"
                langs = {
                    l for l in lines
                    if not l.lower().startswith("list of") and l.lower() != "osd"
                }
                self._available_langs = langs
                return self._available_langs
        except Exception as e:
            logger.debug(f"Could not list tesseract languages: {e}")

        self._available_langs = set()
        return self._available_langs

    def _resolve_lang_flag(self, requested_langs: str) -> Optional[str]:
        """Resolve valid tesseract language string based on installed packs."""
        available = self.get_available_languages()
        if not available:
            return None

        parts = [p.strip() for p in requested_langs.split("+") if p.strip()]
        valid_parts = [p for p in parts if p in available]

        if valid_parts:
            return "+".join(valid_parts)

        # Fallback to 'eng' or 'ita' or first available
        if "eng" in available:
            logger.warning(f"Requested Tesseract languages '{requested_langs}' not found, falling back to 'eng'")
            return "eng"
        if "ita" in available:
            logger.warning(f"Requested Tesseract languages '{requested_langs}' not found, falling back to 'ita'")
            return "ita"

        fallback = next(iter(available), None)
        logger.warning(
            f"Requested Tesseract languages '{requested_langs}' not found. "
            f"Using installed pack '{fallback}'. Please install tesseract-data-ita tesseract-data-eng."
        )
        return fallback

    def extract_text(self, image_path: Path | str, languages: Optional[str] = None) -> str:
        """
        Extract text from an image file using Tesseract CLI.

        Args:
            image_path: Path to the image file
            languages: Language code(s) like 'ita+eng'

        Returns:
            Extracted text string
        """
        cmd_path = self.get_tesseract_cmd()
        if not cmd_path:
            if sys.platform == "win32":
                logger.error(
                    "Tesseract CLI not found. Please install Tesseract on Windows:\n"
                    "winget install UB-Mannheim.TesseractOCR"
                )
            else:
                logger.error(
                    "Tesseract CLI not found. Please install tesseract and language packs:\n"
                    "Arch Linux: sudo pacman -S tesseract tesseract-data-ita tesseract-data-eng"
                )
            return ""

        img_path = Path(image_path)
        if not img_path.exists():
            logger.error(f"Image file not found for OCR: {img_path}")
            return ""

        lang_req = languages or self.default_languages
        lang_flag = self._resolve_lang_flag(lang_req)

        cmd = [cmd_path, str(img_path), "stdout"]
        if lang_flag:
            cmd.extend(["-l", lang_flag])

        logger.debug(f"Running Tesseract OCR: {' '.join(cmd)}")
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode != 0:
                logger.warning(f"Tesseract exited with status {res.returncode}: {res.stderr}")

            cleaned = res.stdout.strip()
            logger.info(f"OCR extracted {len(cleaned)} characters from {img_path.name}")
            return cleaned
        except subprocess.TimeoutExpired:
            logger.error("Tesseract OCR timed out")
        except Exception as e:
            logger.error(f"Error running Tesseract OCR: {e}")

        return ""
