"""Kokoro model management — download, delete, and list models."""

import logging
from pathlib import Path
from typing import Callable, Optional

import requests

from .config import get_data_dir

logger = logging.getLogger(__name__)


def _voices_dir() -> Path:
    d = get_data_dir() / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d




# ── Kokoro model management ───────────────────────────────────────────────────

KOKORO_BASE_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
)

# (remote filename, local filename) — kept identical for clarity
KOKORO_FILES: list[tuple[str, str]] = [
    ("kokoro-v1.0.onnx", "kokoro-v1.0.onnx"),
    ("voices-v1.0.bin", "voices-v1.0.bin"),
]


def is_kokoro_installed() -> bool:
    """Return True if all Kokoro model files are present locally."""
    d = _voices_dir()
    return all((d / local).exists() for _, local in KOKORO_FILES)


def download_kokoro(
    force: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Download Kokoro model files from GitHub releases.

    Args:
        force: Re-download even when files are already present.
        progress_cb: Optional callback ``(downloaded_bytes, total_bytes)``
            called after each network chunk. *total_bytes* may be -1 if the
            server does not send Content-Length.

    Returns:
        True on success, False on any failure.
    """
    if not force and is_kokoro_installed():
        logger.info("Kokoro models already installed. Use force=True to re-download.")
        return True

    dest_dir = _voices_dir()
    downloaded_total = 0
    total_size = -1  # unknown until we have Content-Length headers

    for remote_name, local_name in KOKORO_FILES:
        url = KOKORO_BASE_URL + remote_name
        dest = dest_dir / local_name
        if dest.exists() and not force:
            continue

        logger.info("Downloading Kokoro file %s → %s", url, dest)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with requests.get(url, stream=True, timeout=(10, 120)) as resp:
                    resp.raise_for_status()
                    file_total = int(resp.headers.get("Content-Length", -1))
                    if file_total > 0 and total_size == -1:
                        # Rough estimate: assume similar size for both files
                        total_size = file_total * len(KOKORO_FILES)

                    with open(dest, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if not chunk:
                                continue
                            fh.write(chunk)
                            downloaded_total += len(chunk)
                            if progress_cb is not None:
                                progress_cb(downloaded_total, total_size)

                logger.info("Downloaded %s (%d bytes)", local_name, dest.stat().st_size)
                break  # Success, exit retry loop
            except Exception as exc:
                logger.error("Failed to download %s (attempt %d/%d): %s", url, attempt + 1, max_retries, exc)
                if dest.exists():
                    dest.unlink()
                if attempt == max_retries - 1:
                    return False
                import time
                time.sleep(2)

    return True


def delete_kokoro() -> bool:
    """Delete local Kokoro model files.

    Returns:
        True if at least one file was deleted, False if nothing was found.
    """
    d = _voices_dir()
    deleted = False
    for _, local_name in KOKORO_FILES:
        path = d / local_name
        if path.exists():
            path.unlink()
            logger.info("Deleted %s", path)
            deleted = True
    if not deleted:
        logger.warning("No Kokoro model files found to delete.")
    return deleted

def download_kokoro_cli() -> None:
    """CLI wrapper to download Kokoro models with terminal progress feedback."""
    import sys

    # Configure logging level for the CLI session
    logging.getLogger().setLevel(logging.WARNING)

    if is_kokoro_installed():
        print("Kokoro model files are already installed.")
        return

    print("Downloading Kokoro TTS model files (~350 MB)...")

    last_pct = -1
    def progress_cb(downloaded: int, total: int) -> None:
        nonlocal last_pct
        if total > 0:
            pct = int((downloaded / total) * 100)
            if pct != last_pct:
                bar_length = 45
                filled_length = int(bar_length * pct // 100)
                bar = '█' * filled_length + '-' * (bar_length - filled_length)
                sys.stdout.write(f"\rProgress: |{bar}| {pct}% ({downloaded / (1024*1024):.1f}/{total / (1024*1024):.1f} MB)")
                sys.stdout.flush()
                last_pct = pct
        else:
            sys.stdout.write(f"\rDownloaded: {downloaded / (1024*1024):.1f} MB")
            sys.stdout.flush()

    try:
        success = download_kokoro(progress_cb=progress_cb)
        print()  # Newline after progress bar
        if success:
            print("✓ Kokoro model files downloaded successfully!")
        else:
            print("✗ Failed to download Kokoro model files.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n✗ Download interrupted by user.")
        sys.exit(1)

