"""Fullscreen screenshot capture with multi-method fallback."""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_WIDTH = 1920


def capture_fullscreen() -> Optional[bytes]:
    """Capture a fullscreen screenshot and return PNG bytes.

    Tries multiple capture methods in order of preference for
    KDE Plasma / Wayland / X11 compatibility.  Returns None on failure.
    The image is resized to at most 1920px wide to save bandwidth
    when sending to a vision model.
    """
    methods = [
        _capture_spectacle,
        _capture_grim,
        _capture_gnome_screenshot,
        _capture_scrot,
        _capture_pil,
    ]
    for method in methods:
        try:
            data = method()
            if data:
                data = _maybe_resize(data)
                logger.info("Screenshot captured via %s (%d bytes)", method.__name__, len(data))
                return data
        except Exception as e:
            logger.debug("%s failed: %s", method.__name__, e)
    logger.error("All screenshot methods failed")
    return None


def _read_and_cleanup(path: Path) -> Optional[bytes]:
    """Read file contents and delete it.  Returns None if empty or missing."""
    try:
        if path.exists() and path.stat().st_size > 0:
            data = path.read_bytes()
            path.unlink(missing_ok=True)
            return data
    except OSError as e:
        logger.debug("Failed to read %s: %s", path, e)
    path.unlink(missing_ok=True)
    return None


def _capture_spectacle() -> Optional[bytes]:
    """KDE Spectacle — native on KDE Plasma / Wayland."""
    if not shutil.which("spectacle"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    subprocess.run(
        ["spectacle", "-b", "-n", "-f", "-o", str(tmp)],
        capture_output=True, timeout=10,
    )
    return _read_and_cleanup(tmp)


def _capture_grim() -> Optional[bytes]:
    """grim — wlroots-based Wayland compositors."""
    if not shutil.which("grim"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    subprocess.run(
        ["grim", str(tmp)],
        capture_output=True, timeout=10,
    )
    return _read_and_cleanup(tmp)


def _capture_gnome_screenshot() -> Optional[bytes]:
    """gnome-screenshot — GNOME / Wayland."""
    if not shutil.which("gnome-screenshot"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    subprocess.run(
        ["gnome-screenshot", "-f", str(tmp)],
        capture_output=True, timeout=10,
    )
    return _read_and_cleanup(tmp)


def _capture_scrot() -> Optional[bytes]:
    """scrot — lightweight X11 screenshot tool."""
    if not shutil.which("scrot"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    subprocess.run(
        ["scrot", str(tmp)],
        capture_output=True, timeout=10,
    )
    return _read_and_cleanup(tmp)


def _capture_pil() -> Optional[bytes]:
    """PIL ImageGrab — universal fallback."""
    try:
        from PIL import ImageGrab
        import io

        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except (ImportError, AttributeError, OSError):
        return None


def _maybe_resize(png_bytes: bytes) -> bytes:
    """Resize image to at most _MAX_WIDTH pixels wide (preserving aspect ratio)."""
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(png_bytes))
        if img.width <= _MAX_WIDTH:
            return png_bytes
        ratio = _MAX_WIDTH / img.width
        new_size = (_MAX_WIDTH, int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        logger.debug("Resized screenshot from %dx%d to %dx%d", img.width, img.height, *new_size)
        return buf.getvalue()
    except ImportError:
        return png_bytes
