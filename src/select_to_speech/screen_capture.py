"""Wayland native screen capture helper using slurp+grim (with KDE Spectacle fallback)"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class ScreenCapture:
    """Captures a screen region on Wayland using slurp/grim or KDE Spectacle fallback."""

    @staticmethod
    def is_spectacle_available() -> bool:
        """Check if KDE spectacle is installed."""
        return shutil.which("spectacle") is not None

    @staticmethod
    def is_grim_slurp_available() -> bool:
        """Check if grim and slurp are installed."""
        return shutil.which("grim") is not None and shutil.which("slurp") is not None

    @classmethod
    def capture_region(cls, output_path: Path | str) -> bool:
        """
        Interactive rectangular screen selection saved to output_path.

        Args:
            output_path: Destination path for the PNG screenshot

        Returns:
            True if capture succeeded and file was written, False otherwise
        """
        out_file = Path(output_path)
        if out_file.exists():
            try:
                out_file.unlink()
            except OSError:
                pass

        out_file.parent.mkdir(parents=True, exist_ok=True)

        # 1. Prioritize KDE Spectacle (with -k for immediate capture on click-and-release)
        if cls.is_spectacle_available():
            logger.info("Starting rectangular screen selection using KDE Spectacle (-k immediate capture)")
            cmd = [
                "spectacle",
                "-r",  # rectangular region
                "-b",  # background (do not open GUI editor after capture)
                "-n",  # non-notify
                "-k",  # release-capture (accept region on click-and-release)
                "-o",  str(out_file),
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode != 0:
                    logger.warning(f"Spectacle returned code {res.returncode}: {res.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning("Screen capture with Spectacle timed out after 30s")
            except Exception as e:
                logger.error(f"Failed to run spectacle: {e}")

            if out_file.exists() and out_file.stat().st_size > 0:
                logger.info(f"Screen capture saved to {out_file}")
                return True
            logger.info("Screen capture cancelled or failed with Spectacle")
            return False

        # 2. Fallback to slurp + grim (for wlroots compositors like Sway/Hyprland)
        if cls.is_grim_slurp_available():
            logger.info("Trying slurp + grim fallback for rectangular screen selection")
            try:
                slurp_res = subprocess.run(["slurp"], capture_output=True, text=True, timeout=30)
                if slurp_res.returncode != 0:
                    logger.info("Region selection cancelled")
                    return False
                region = slurp_res.stdout.strip()
                if not region:
                    return False
                grim_res = subprocess.run(["grim", "-g", region, str(out_file)], capture_output=True, text=True, timeout=10)
                if grim_res.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
                    logger.info(f"Screen capture saved to {out_file}")
                    return True
            except subprocess.TimeoutExpired:
                logger.warning("Screen capture with slurp/grim timed out")
            except Exception as e:
                logger.error(f"Failed to run slurp+grim: {e}")

        logger.error(
            "No supported screen capture tool found.\n"
            "Please install slurp and grim (or KDE Spectacle): sudo pacman -S slurp grim spectacle"
        )
        return False

