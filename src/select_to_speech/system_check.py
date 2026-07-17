"""System dependencies checker"""

import logging
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import pyaudio
except ImportError:
    pyaudio = None

# Configure basic console logging for the system check
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def check_system_dependencies() -> bool:
    """
    Check for required system dependencies.

    Required packages must all be present; optional packages trigger a warning
    but do not cause this function to return False.

    Returns:
        True if all *required* dependencies are found, False otherwise
    """
    required_packages = {
        "wl-paste": "wl-clipboard",
    }
    # Optional: enables selection capture inside XWayland (non-native Wayland) apps.
    optional_packages = {
        "xclip": "xclip",
    }

    missing = []
    found = []
    missing_optional = []

    for command, package in required_packages.items():
        if shutil.which(command):
            found.append(f"✓ {command} ({package})")
        else:
            missing.append((command, package))

    for command, package in optional_packages.items():
        if shutil.which(command):
            found.append(f"✓ {command} ({package}) [optional - XWayland support]")
        else:
            missing_optional.append((command, package))

    # Check OCR utilities (tesseract + screen capture tools)
    missing_ocr = []
    if shutil.which("tesseract"):
        tess_info = "✓ tesseract (tesseract) [optional - OCR engine]"
        try:
            res = subprocess.run(
                ["tesseract", "--list-langs"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                langs = {
                    l for l in lines
                    if not l.lower().startswith("list of") and l.lower() != "osd"
                }
                if langs:
                    tess_info += f" (languages: {', '.join(sorted(langs))})"
                else:
                    missing_ocr.append(
                        ("tesseract language packs", "tesseract-data-ita tesseract-data-eng", "no OCR language packs found (es. ita/eng)")
                    )
        except Exception:
            pass
        found.append(tess_info)
    else:
        missing_ocr.append(
            ("tesseract", "tesseract tesseract-data-ita tesseract-data-eng", "required for OCR text extraction")
        )

    has_spectacle = shutil.which("spectacle") is not None
    has_grim_slurp = shutil.which("grim") is not None and shutil.which("slurp") is not None

    if has_spectacle:
        found.append("✓ spectacle (spectacle) [optional - OCR screen capture (KDE primary)]")
    if has_grim_slurp:
        found.append("✓ slurp & grim (slurp grim) [optional - OCR screen capture (wlroots fallback)]")
    if not has_spectacle and not has_grim_slurp:
        missing_ocr.append(
            ("spectacle (or slurp+grim)", "spectacle slurp grim", "required for capturing rectangular screen regions for OCR")
        )

    logger.info("\n=== System Dependencies Check ===\n")

    for item in found:
        logger.info(item)

    if missing_optional:
        logger.warning("\nOptional dependencies not found (reduced functionality):")
        for cmd, pkg in missing_optional:
            logger.warning(
                f"  ⚠ {cmd} ({pkg}) – text selected in XWayland apps will not be captured"
            )
        packages_opt = list(set(pkg for _, pkg in missing_optional))
        logger.warning(f"  Install with: sudo pacman -S {' '.join(packages_opt)}")

    if missing_ocr:
        logger.warning("\nOptional OCR utilities not found (screen OCR via Alt+R will not work):")
        for cmd, pkg, reason in missing_ocr:
            logger.warning(f"  ⚠ {cmd} ({pkg}) – {reason}")
        packages_ocr = []
        for _, pkg, _ in missing_ocr:
            packages_ocr.extend(pkg.split())
        packages_ocr = sorted(list(set(packages_ocr)))
        logger.warning(f"  Install with: sudo pacman -S {' '.join(packages_ocr)}")

    if missing:
        logger.error("\nMissing required binary dependencies:")
        for cmd, pkg in missing:
            logger.error(f"✗ {cmd} ({pkg})")
        logger.error("\n=== Installation Instructions (CachyOS/Arch) ===\n")
        logger.error("Install missing packages:")
        packages = list(set(pkg for _, pkg in missing))
        logger.error(f"  sudo pacman -S {' '.join(packages)}\n")

    if missing:
        return False

    logger.info("\n✓ All required system dependencies are installed!\n")
    return True


def get_audio_devices() -> list[dict]:
    """Return structured list of audio output devices.

    Returns:
        List of dicts with keys: id, name, channels, sample_rate, is_default
    """
    devices: list[dict] = []
    if not pyaudio:
        return devices

    p = pyaudio.PyAudio()
    try:
        default_info = p.get_default_output_device_info()
        default_name = default_info["name"] if default_info else None

        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxOutputChannels"] > 0:
                devices.append({
                    "id": i,
                    "name": info["name"],
                    "channels": info["maxOutputChannels"],
                    "sample_rate": int(info["defaultSampleRate"]),
                    "is_default": info["name"] == default_name,
                })
    finally:
        p.terminate()

    return devices


def list_audio_devices() -> None:
    """List all available audio output devices"""
    devices = get_audio_devices()
    if not devices:
        logger.error("PyAudio not available or no output devices found")
        return

    logger.info("\n=== Available Audio Output Devices ===\n")

    for dev in devices:
        default_tag = " [DEFAULT]" if dev["is_default"] else ""
        logger.info(f"Device {dev['id']}: {dev['name']}{default_tag}")
        logger.info(f"  Channels: {dev['channels']}")
        logger.info(f"  Sample Rate: {dev['sample_rate']} Hz\n")

    logger.info("To use a specific device, edit ~/.config/select-to-speech/config.yaml:")
    logger.info("  audio:")
    logger.info("    device_id: <device_number>\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Select-to-Speech system checker")
    parser.add_argument("--audio-devices", action="store_true", help="List audio devices")
    
    args = parser.parse_args()

    if args.audio_devices:
        list_audio_devices()
    else:
        is_ok = check_system_dependencies()
        sys.exit(0 if is_ok else 1)
