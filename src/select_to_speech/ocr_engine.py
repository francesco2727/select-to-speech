"""OCR Engine using Tesseract CLI"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)

# Spoken when the OCR shortcut is used but Tesseract (or its language packs) is missing.
# Keyed by the voice language codes Kokoro can speak; falls back to English.
OCR_MISSING_MESSAGES: dict[str, str] = {
    "en": "Screen reading is not available. To use it, install Tesseract and its language packs.",
    "it": "La lettura dallo schermo non è disponibile. Per usarla, installa Tesseract e i relativi pacchetti lingua.",
    "es": "La lectura de pantalla no está disponible. Para usarla, instala Tesseract y sus paquetes de idioma.",
    "fr": "La lecture de l'écran n'est pas disponible. Pour l'utiliser, installez Tesseract et ses paquets de langue.",
    "pt": "A leitura de tela não está disponível. Para usá-la, instale o Tesseract e os seus pacotes de idioma.",
    "hi": "स्क्रीन से पढ़ना उपलब्ध नहीं है। इसका उपयोग करने के लिए Tesseract और उसके भाषा पैक इंस्टॉल करें।",
    "ja": "画面の読み上げは利用できません。使用するには、Tesseract と言語パックをインストールしてください。",
    "ko": "화면 읽기를 사용할 수 없습니다. 사용하려면 Tesseract와 언어 팩을 설치하세요.",
    "zh": "屏幕朗读不可用。要使用此功能，请安装 Tesseract 及其语言包。",
}


def ocr_missing_message(language: str) -> str:
    """Return the "install Tesseract" reminder in the given language (English fallback)."""
    return OCR_MISSING_MESSAGES.get(language, OCR_MISSING_MESSAGES["en"])


class OcrEngine:
    """Extracts text from images using native Tesseract CLI (to keep uv environment lightweight)."""

    def __init__(self, default_languages: str = "ita+eng"):
        self.default_languages = default_languages
        self._available_langs: Optional[set[str]] = None

    def is_available(self) -> bool:
        """Check if tesseract CLI is installed and available on PATH."""
        return shutil.which("tesseract") is not None

    def get_available_languages(self) -> set[str]:
        """Check available tesseract language data packs."""
        # Only a non-empty result is cached, so installing Tesseract or a language
        # pack while the daemon runs is picked up without a restart.
        if self._available_langs:
            return self._available_langs

        if not self.is_available():
            return set()

        try:
            res = subprocess.run(
                ["tesseract", "--list-langs"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                lines = [
                    line.strip() for line in res.stdout.splitlines() if line.strip()
                ]
                # First line is usually "List of available languages (N):"
                langs = {
                    line
                    for line in lines
                    if not line.lower().startswith("list of") and line.lower() != "osd"
                }
                self._available_langs = langs or None
                return langs
        except Exception as e:
            logger.debug(f"Could not list tesseract languages: {e}")

        return set()

    def is_ready(self) -> bool:
        """True when Tesseract is installed with at least one language pack."""
        return self.is_available() and bool(self.get_available_languages())

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
            logger.warning(
                f"Requested Tesseract languages '{requested_langs}' not found, falling back to 'eng'"
            )
            return "eng"
        if "ita" in available:
            logger.warning(
                f"Requested Tesseract languages '{requested_langs}' not found, falling back to 'ita'"
            )
            return "ita"

        fallback = next(iter(available), None)
        logger.warning(
            f"Requested Tesseract languages '{requested_langs}' not found. "
            f"Using installed pack '{fallback}'. Please install tesseract-data-ita tesseract-data-eng."
        )
        return fallback

    def extract_text(
        self, image_path: Path | str, languages: Optional[str] = None
    ) -> str:
        """
        Extract text from an image file using Tesseract CLI.

        Args:
            image_path: Path to the image file
            languages: Language code(s) like 'ita+eng'

        Returns:
            Extracted text string
        """
        if not self.is_available():
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

        cmd = ["tesseract", str(img_path), "stdout"]
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
                logger.warning(
                    f"Tesseract exited with status {res.returncode}: {res.stderr}"
                )

            cleaned = res.stdout.strip()
            logger.info(f"OCR extracted {len(cleaned)} characters from {img_path.name}")
            return cleaned
        except subprocess.TimeoutExpired:
            logger.error("Tesseract OCR timed out")
        except Exception as e:
            logger.error(f"Error running Tesseract OCR: {e}")

        return ""
