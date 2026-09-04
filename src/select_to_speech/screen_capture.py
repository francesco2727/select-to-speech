"""Screen capture helper for Linux (Wayland slurp+grim, Spectacle) and Windows (ms-screenclip, snippingtool, PIL/Tkinter)"""

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


def _capture_region_windows_snipping_tool(output_path: Path) -> bool:
    """
    Capture a region on Windows using Snipping Tool / ms-screenclip protocol
    and reading the captured image from the Windows clipboard.
    """
    try:
        from PIL import Image, ImageGrab
    except Exception:
        ImageGrab = None
        Image = None

    # Try launching ms-screenclip URI or snippingtool /clip
    launched = False

    # Check for snippingtool.exe on PATH or System32
    snipping_exe = shutil.which("snippingtool.exe") or shutil.which("snippingtool")
    if not snipping_exe:
        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        cand = Path(sys_root) / "System32" / "SnippingTool.exe"
        if cand.exists():
            snipping_exe = str(cand)

    if snipping_exe:
        try:
            logger.info("Launching Windows Snipping Tool in clip mode...")
            # snippingtool /clip triggers the modern screen clipper
            subprocess.Popen([snipping_exe, "/clip"])
            launched = True
        except Exception as e:
            logger.debug(f"Failed to launch SnippingTool.exe /clip: {e}")

    if not launched:
        try:
            logger.info("Launching ms-screenclip: protocol handler...")
            os.startfile("ms-screenclip:")
            launched = True
        except Exception as e:
            logger.debug(f"Failed to launch ms-screenclip URI: {e}")

    if not launched:
        return False

    if not ImageGrab:
        logger.warning("PIL / Pillow (ImageGrab) is not available to read clipboard image.")
        return False

    # Grab clipboard initially to see if it changes to an image
    init_img = None
    try:
        init_img = ImageGrab.grabclipboard()
    except Exception:
        pass

    logger.info("Waiting for user to complete screen region clipping...")
    # Poll clipboard for a new Image object (up to 30 seconds)
    start_time = time.time()
    while time.time() - start_time < 30:
        time.sleep(0.5)
        try:
            img = ImageGrab.grabclipboard()
            # If img is a PIL Image (or a list of file paths containing an image)
            if img is not None and img != init_img:
                if (Image and isinstance(img, getattr(Image, "Image", object))) or hasattr(img, "save"):
                    img.save(str(output_path), "PNG")
                    if output_path.exists() and output_path.stat().st_size > 0:
                        logger.info(f"Screen capture saved to {output_path}")
                        return True
                elif isinstance(img, list) and len(img) > 0:
                    src_file = Path(img[0])
                    if src_file.exists() and src_file.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
                        shutil.copyfile(src_file, output_path)
                        logger.info(f"Screen capture saved to {output_path}")
                        return True
        except Exception as e:
            logger.debug(f"Clipboard grab error: {e}")

    logger.info("Snipping Tool capture timed out or cancelled.")
    return False


def _capture_region_windows_tk_overlay(output_path: Path) -> bool:
    """
    Fallback region capture for Windows using Tkinter overlay and PIL.ImageGrab.
    """
    try:
        import tkinter as tk
        from PIL import ImageGrab
    except ImportError:
        return False

    # Ensure process is DPI-aware on Windows so coordinates match physical pixels
    if sys.platform == "win32":
        try:
            import ctypes
            # Try per-monitor DPI aware (Windows 8.1+)
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    selection = {}

    try:
        root = tk.Tk()
        root.attributes("-alpha", 0.3)
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        root.config(cursor="cross")

        canvas = tk.Canvas(root, cursor="cross", bg="grey15")
        canvas.pack(fill="both", expand=True)

        rect_id = None
        start_x = 0
        start_y = 0

        def on_mouse_down(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x_root, event.y_root
            rect_id = canvas.create_rectangle(
                event.x, event.y, event.x, event.y, outline="red", width=2
            )

        def on_mouse_move(event):
            nonlocal rect_id
            if rect_id:
                canvas.coords(rect_id, start_x, start_y, event.x, event.y)

        def on_mouse_up(event):
            nonlocal selection
            end_x, end_y = event.x_root, event.y_root
            x1 = min(start_x, end_x)
            y1 = min(start_y, end_y)
            x2 = max(start_x, end_x)
            y2 = max(start_y, end_y)
            if x2 - x1 > 5 and y2 - y1 > 5:
                selection["bbox"] = (x1, y1, x2, y2)
            root.quit()

        def on_escape(event):
            root.quit()

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_move)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)
        root.bind("<Escape>", on_escape)

        root.mainloop()
        root.destroy()

        if "bbox" in selection:
            bbox = selection["bbox"]
            try:
                img = ImageGrab.grab(bbox=bbox, all_screens=True)
            except TypeError:
                # Older Pillow versions might not support all_screens keyword
                img = ImageGrab.grab(bbox=bbox)
            img.save(str(output_path), "PNG")
            return output_path.exists() and output_path.stat().st_size > 0
    except Exception as e:
        logger.debug(f"Tkinter overlay capture failed: {e}")

    return False


class ScreenCapture:
    """Captures a screen region on Linux (slurp/grim, Spectacle) or Windows."""

    @staticmethod
    def is_spectacle_available() -> bool:
        """Check if KDE spectacle is installed."""
        return shutil.which("spectacle") is not None

    @staticmethod
    def is_grim_slurp_available() -> bool:
        """Check if grim and slurp are installed."""
        return shutil.which("grim") is not None and shutil.which("slurp") is not None

    @staticmethod
    def is_windows_capture_available() -> bool:
        """Check if Windows screen capture capabilities are present."""
        if sys.platform != "win32":
            return False
        # Windows 10/11 have SnippingTool or ms-screenclip support
        return True

    @classmethod
    def _capture_region_windows(cls, output_path: Path) -> bool:
        """Capture screen region on Windows."""
        # 1. Try Windows Snipping Tool / ms-screenclip
        if _capture_region_windows_snipping_tool(output_path):
            return True

        # 2. Try Tkinter overlay fallback if Pillow is available
        if _capture_region_windows_tk_overlay(output_path):
            return True

        logger.error(
            "Windows screen capture failed. Please make sure Snipping Tool or Pillow is available."
        )
        return False

    @classmethod
    def _capture_region_linux(cls, output_path: Path) -> bool:
        """Capture screen region on Linux using Spectacle or slurp+grim."""
        # 1. Prioritize KDE Spectacle (with -k for immediate capture on click-and-release)
        if cls.is_spectacle_available():
            logger.info("Starting rectangular screen selection using KDE Spectacle (-k immediate capture)")
            cmd = [
                "spectacle",
                "-r",  # rectangular region
                "-b",  # background (do not open GUI editor after capture)
                "-n",  # non-notify
                "-k",  # release-capture (accept region on click-and-release)
                "-o",  str(output_path),
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode != 0:
                    logger.warning(f"Spectacle returned code {res.returncode}: {res.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning("Screen capture with Spectacle timed out after 30s")
            except Exception as e:
                logger.error(f"Failed to run spectacle: {e}")

            if output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"Screen capture saved to {output_path}")
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
                grim_res = subprocess.run(["grim", "-g", region, str(output_path)], capture_output=True, text=True, timeout=10)
                if grim_res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    logger.info(f"Screen capture saved to {output_path}")
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

        if sys.platform == "win32":
            return cls._capture_region_windows(out_file)

        return cls._capture_region_linux(out_file)


