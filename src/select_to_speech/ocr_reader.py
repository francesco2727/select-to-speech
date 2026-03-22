"""OCR screen region reader using grim + slurp + tesseract"""

import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def check_ocr_deps() -> list[str]:
    """
    Check which OCR dependencies are missing.

    Returns:
        List of missing tool names. Requires slurp and tesseract.
        For capture, needs at least one of: grim, import, scrot, or PIL.
    """
    # Strict requirements
    required = ["slurp", "tesseract"]
    missing = []

    for tool in required:
        if not shutil.which(tool):
            missing.append(tool)

    # Check for capture tools (need at least one)
    has_grim = shutil.which("grim") is not None
    has_import = shutil.which("import") is not None
    has_scrot = shutil.which("scrot") is not None
    has_pil = _check_pil_available()

    if not (has_grim or has_import or has_scrot or has_pil):
        missing.append("screenshot tool (grim, imagemagick, scrot, or pillow)")

    return missing


def _check_pil_available() -> bool:
    """Check if PIL with ImageGrab is available."""
    try:
        from PIL import ImageGrab
        return True
    except (ImportError, AttributeError):
        return False


def _capture_with_grim(geometry: str, tmp_path: str) -> bool:
    """Try to capture with grim. Returns True if successful."""
    try:
        subprocess.run(
            ["grim", "-g", geometry, tmp_path],
            timeout=10,
            check=True,
            capture_output=True,
            text=True
        )

        # Verify the file was actually created and has content
        if not Path(tmp_path).exists() or Path(tmp_path).stat().st_size == 0:
            logger.debug("grim created empty file")
            Path(tmp_path).unlink(missing_ok=True)
            return False

        return True
    except subprocess.CalledProcessError as e:
        logger.debug(f"grim failed: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        logger.debug(f"grim error: {e}")
        return False


def _capture_with_import(geometry: str, tmp_path: str) -> bool:
    """Try to capture with ImageMagick import (X11). Returns True if successful."""
    temp_capture = tmp_path + ".full"
    try:
        from PIL import Image

        # Parse geometry "x,y wxh" to coordinates and dimensions
        parts = geometry.split()
        coords = parts[0].split(",")
        dims = parts[1].split("x")
        x, y = int(coords[0]), int(coords[1])
        w, h = int(dims[0]), int(dims[1])

        # Capture full root window, then crop
        subprocess.run(
            ["import", "-window", "root", temp_capture],
            timeout=10,
            check=True,
            capture_output=True,
            text=True
        )

        # Verify capture created a valid file
        if not Path(temp_capture).exists() or Path(temp_capture).stat().st_size == 0:
            logger.debug("import created empty file")
            return False

        # Crop the captured image to the selected region
        img = Image.open(temp_capture)
        cropped = img.crop((x, y, x + w, y + h))
        cropped.save(tmp_path)

        # Verify final file has content
        if Path(tmp_path).stat().st_size == 0:
            logger.debug("import crop produced empty file")
            return False

        return True
    except subprocess.CalledProcessError as e:
        logger.debug(f"import failed: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        logger.debug(f"import crop failed: {e}")
        return False
    finally:
        Path(temp_capture).unlink(missing_ok=True)


def _capture_with_scrot(geometry: str, tmp_path: str) -> bool:
    """Try to capture with scrot (lightweight X11 tool)."""
    temp_capture = tmp_path + ".scrot"
    try:
        # Parse geometry "x,y wxh" to coordinates and dimensions
        parts = geometry.split()
        coords = parts[0].split(",")
        dims = parts[1].split("x")
        x, y = int(coords[0]), int(coords[1])
        w, h = int(dims[0]), int(dims[1])

        # Capture full screen, then crop with PIL
        subprocess.run(
            ["scrot", temp_capture],
            timeout=10,
            check=True,
            capture_output=True,
            text=True
        )

        # Verify capture created a valid file
        if not Path(temp_capture).exists() or Path(temp_capture).stat().st_size == 0:
            logger.debug("scrot created empty file")
            return False

        from PIL import Image
        img = Image.open(temp_capture)
        cropped = img.crop((x, y, x + w, y + h))
        cropped.save(tmp_path)

        # Verify final file has content
        if Path(tmp_path).stat().st_size == 0:
            logger.debug("scrot crop produced empty file")
            return False

        return True
    except subprocess.CalledProcessError as e:
        logger.debug(f"scrot failed: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        logger.debug(f"scrot capture failed: {e}")
        return False
    finally:
        Path(temp_capture).unlink(missing_ok=True)


def _capture_with_spectacle(geometry: str, tmp_path: str) -> bool:
    """Try to capture with Spectacle (KDE/Wayland-native)."""
    temp_capture = tmp_path + ".spectacle"
    try:
        from PIL import Image

        # Parse geometry "x,y wxh" to coordinates and dimensions
        parts = geometry.split()
        coords = parts[0].split(",")
        dims = parts[1].split("x")
        x, y = int(coords[0]), int(coords[1])
        w, h = int(dims[0]), int(dims[1])

        # Spectacle captures full screen by default
        subprocess.run(
            ["spectacle", "-b", "-n", "-o", temp_capture],
            timeout=10,
            check=True,
            capture_output=True,
            text=True
        )

        # Verify capture created a valid file
        if not Path(temp_capture).exists() or Path(temp_capture).stat().st_size == 0:
            logger.debug("spectacle created empty file")
            return False

        # Crop the captured image to the selected region
        img = Image.open(temp_capture)
        cropped = img.crop((x, y, x + w, y + h))
        cropped.save(tmp_path)

        # Verify final file has content
        if Path(tmp_path).stat().st_size == 0:
            logger.debug("spectacle crop produced empty file")
            return False

        return True
    except subprocess.CalledProcessError as e:
        logger.debug(f"spectacle failed: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        logger.debug(f"spectacle capture failed: {e}")
        return False
    finally:
        Path(temp_capture).unlink(missing_ok=True)


def _capture_with_gnome_screenshot(geometry: str, tmp_path: str) -> bool:
    """Try to capture with GNOME Screenshot (GNOME/Wayland)."""
    temp_capture = tmp_path + ".gnome"
    try:
        from PIL import Image

        # Parse geometry "x,y wxh" to coordinates and dimensions
        parts = geometry.split()
        coords = parts[0].split(",")
        dims = parts[1].split("x")
        x, y = int(coords[0]), int(coords[1])
        w, h = int(dims[0]), int(dims[1])

        # GNOME Screenshot captures full screen by default
        subprocess.run(
            ["gnome-screenshot", "-f", temp_capture],
            timeout=10,
            check=True,
            capture_output=True,
            text=True
        )

        # Verify capture created a valid file
        if not Path(temp_capture).exists() or Path(temp_capture).stat().st_size == 0:
            logger.debug("gnome-screenshot created empty file")
            return False

        # Crop the captured image to the selected region
        img = Image.open(temp_capture)
        cropped = img.crop((x, y, x + w, y + h))
        cropped.save(tmp_path)

        # Verify final file has content
        if Path(tmp_path).stat().st_size == 0:
            logger.debug("gnome-screenshot crop produced empty file")
            return False

        return True
    except subprocess.CalledProcessError as e:
        logger.debug(f"gnome-screenshot failed: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        logger.debug(f"gnome-screenshot capture failed: {e}")
        return False
    finally:
        Path(temp_capture).unlink(missing_ok=True)


def _capture_with_pil(geometry: str, tmp_path: str) -> bool:
    """Try to capture using PIL/Pillow (fallback, may be limited)."""
    try:
        from PIL import ImageGrab

        # Parse geometry "x,y wxh" to coordinates and dimensions
        parts = geometry.split()
        coords = parts[0].split(",")
        dims = parts[1].split("x")
        x, y = int(coords[0]), int(coords[1])
        w, h = int(dims[0]), int(dims[1])

        # Use PIL's screenshot - crops directly without temp file
        screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        if screenshot is None:
            logger.debug("PIL ImageGrab.grab() returned None")
            return False

        screenshot.save(tmp_path)

        # Verify the file was actually created and has content
        if not Path(tmp_path).exists() or Path(tmp_path).stat().st_size == 0:
            logger.debug("PIL saved empty image file")
            return False

        return True
    except ImportError:
        logger.debug("PIL ImageGrab not available")
        return False
    except Exception as e:
        logger.debug(f"PIL capture failed: {e}")
        return False


def capture_region_text(lang_hint: str = "") -> Optional[str]:
    """
    Interactively capture a screen region and extract text via OCR.

    Prompts user to draw a region with slurp, captures it with grim,
    and extracts text using pytesseract.

    Args:
        lang_hint: Language code for OCR hint (e.g. 'en', 'it')

    Returns:
        Extracted text string, or None if user cancels, no text found, or deps missing
    """
    missing = check_ocr_deps()
    if missing:
        logger.warning(
            f"OCR dependencies missing: {', '.join(missing)}. "
            "Install with: sudo pacman -S slurp tesseract tesseract-data-* grim imagemagick scrot && "
            "pip install pillow"
        )
        return None

    try:
        # Let user select a screen region with slurp
        geometry = subprocess.run(
            ["slurp"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )
        geometry = geometry.stdout.strip()

        if not geometry:
            logger.info("OCR selection cancelled by user")
            return None

        logger.debug(f"OCR region selected: {geometry}")

        # Capture region as PNG to a temporary file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Try capture tools in order of preference
            capture_methods = [
                ("spectacle (KDE/Wayland)", _capture_with_spectacle),
                ("gnome-screenshot (GNOME/Wayland)", _capture_with_gnome_screenshot),
                ("grim (Wayland)", _capture_with_grim),
                ("import (X11/ImageMagick)", _capture_with_import),
                ("scrot (X11 fallback)", _capture_with_scrot),
                ("PIL (universal fallback)", _capture_with_pil),
            ]

            success = False
            for method_name, method_func in capture_methods:
                if method_func(geometry, tmp_path):
                    logger.debug(f"Screen capture successful with {method_name}")
                    success = True
                    break
                logger.debug(f"{method_name} failed, trying next method...")

            if not success:
                logger.error(
                    "Screen capture failed: all methods unavailable. "
                    "Install: sudo pacman -S imagemagick grim scrot && "
                    "pip install pillow"
                )
                return None

            # Extract text using pytesseract
            try:
                from PIL import Image
                import pytesseract
            except ImportError as e:
                logger.error(f"pytesseract or PIL not installed: {e}")
                return None

            image = Image.open(tmp_path)

            # Build pytesseract config for language if provided
            config = ""
            if lang_hint:
                # Map language code to tesseract language code
                lang_map = {
                    "en": "eng",
                    "it": "ita",
                    "es": "spa",
                    "fr": "fra",
                    "de": "deu",
                    "pt": "por",
                    "nl": "nld",
                    "ru": "rus",
                    "ja": "jpn",
                    "zh": "chi_sim",
                    "ko": "kor",
                    "ar": "ara",
                    "hi": "hin",
                    "tr": "tur",
                    "pl": "pol",
                }
                tess_lang = lang_map.get(lang_hint, "eng")
                config = f"--psm 3 -l {tess_lang}"
            else:
                config = "--psm 3"

            text = pytesseract.image_to_string(image, config=config)
            text = text.strip()

            if not text:
                logger.info("OCR extraction returned empty result")
                return None

            logger.info(f"OCR extracted {len(text)} chars: {text[:60]}...")
            return text
        finally:
            # Clean up temporary file
            Path(tmp_path).unlink(missing_ok=True)

    except subprocess.TimeoutExpired:
        logger.warning("OCR operation timed out")
        return None
    except subprocess.CalledProcessError as e:
        stderr = getattr(e, 'stderr', 'no stderr captured')
        logger.error(f"OCR subprocess failed: {e.cmd} - {stderr}")
        return None
    except Exception as e:
        logger.error(f"OCR error: {e}", exc_info=True)
        return None
