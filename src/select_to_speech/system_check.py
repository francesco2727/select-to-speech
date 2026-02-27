"""System dependencies checker"""

import logging
import shutil
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

    Returns:
        True if all dependencies are found, False otherwise
    """
    required_packages = {
        "wl-paste": "wl-clipboard",
        "pactl": "pulseaudio",
    }

    missing = []
    found = []

    for command, package in required_packages.items():
        if shutil.which(command):
            found.append(f"✓ {command} ({package})")
        else:
            missing.append((command, package))

    logger.info("\n=== System Dependencies Check ===\n")

    for item in found:
        logger.info(item)

    if missing:
        logger.error("\nMissing dependencies:")
        for cmd, pkg in missing:
            logger.error(f"✗ {cmd} ({pkg})")

        logger.error("\n=== Installation Instructions (CachyOS/Arch) ===\n")
        logger.error("Install missing packages:")
        packages = list(set(pkg for _, pkg in missing))
        logger.error(f"  sudo pacman -S {' '.join(packages)}\n")

        return False

    logger.info("\n✓ All system dependencies are installed!\n")
    return True


def list_audio_devices() -> None:
    """List all available audio output devices"""
    if not pyaudio:
        logger.error("PyAudio not available")
        return

    p = pyaudio.PyAudio()
    device_count = p.get_device_count()

    logger.info("\n=== Available Audio Output Devices ===\n")
    
    default_info = p.get_default_output_device_info()
    default_name = default_info['name'] if default_info else None
    
    for i in range(device_count):
        info = p.get_device_info_by_index(i)
        if info['maxOutputChannels'] > 0:
            is_default = " [DEFAULT]" if info['name'] == default_name else ""
            logger.info(f"Device {i}: {info['name']}{is_default}")
            logger.info(f"  Channels: {info['maxOutputChannels']}")
            logger.info(f"  Sample Rate: {int(info['defaultSampleRate'])} Hz\n")

    p.terminate()

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
