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

KOKORO_MODELS = {
    "kokoro-v1.0": {
        "name": "Kokoro v1.0 (FP32, ~340 MB)",
        "size_mb": 340,
        "files": [
            ("kokoro-v1.0.onnx", "kokoro-v1.0.onnx"),
            ("voices-v1.0.bin", "voices-v1.0.bin"),
        ]
    },
    "kokoro-v1.0-fp16": {
        "name": "Kokoro v1.0 (FP16, ~175 MB)",
        "size_mb": 175,
        "files": [
            ("kokoro-v1.0.fp16.onnx", "kokoro-v1.0.fp16.onnx"),
            ("voices-v1.0.bin", "voices-v1.0.bin"),
        ]
    },
    "kokoro-v1.0-int8": {
        "name": "Kokoro v1.0 (INT8, ~114 MB)",
        "size_mb": 114,
        "files": [
            ("kokoro-v1.0.int8.onnx", "kokoro-v1.0.int8.onnx"),
            ("voices-v1.0.bin", "voices-v1.0.bin"),
        ]
    }
}


def is_kokoro_installed(model_id: str = "kokoro-v1.0") -> bool:
    """Return True if all Kokoro model files are present locally."""
    if model_id not in KOKORO_MODELS:
        return False
    d = _voices_dir()
    return all((d / local).exists() for _, local in KOKORO_MODELS[model_id]["files"])


def download_kokoro(
    model_id: str = "kokoro-v1.0",
    force: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Download Kokoro model files from GitHub releases.

    Args:
        model_id: The ID of the model to download.
        force: Re-download even when files are already present.
        progress_cb: Optional callback ``(downloaded_bytes, total_bytes)``
            called after each network chunk. *total_bytes* may be -1 if the
            server does not send Content-Length.

    Returns:
        True on success, False on any failure.
    """
    if model_id not in KOKORO_MODELS:
        logger.error("Unknown model_id: %s", model_id)
        return False

    if not force and is_kokoro_installed(model_id):
        logger.info("Kokoro models already installed. Use force=True to re-download.")
        return True

    dest_dir = _voices_dir()
    downloaded_total = 0
    total_size = -1  # unknown until we have Content-Length headers

    files = KOKORO_MODELS[model_id]["files"]

    for remote_name, local_name in files:
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
                        total_size = file_total * len(files)

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


def delete_kokoro(model_id: str = "kokoro-v1.0") -> bool:
    """Delete local Kokoro model files.

    Returns:
        True if at least one file was deleted, False if nothing was found.
    """
    if model_id not in KOKORO_MODELS:
        return False
        
    d = _voices_dir()
    deleted = False
    for _, local_name in KOKORO_MODELS[model_id]["files"]:
        path = d / local_name
        if path.exists():
            path.unlink()
            logger.info("Deleted %s", path)
            deleted = True
    if not deleted:
        logger.warning("No Kokoro model files found to delete.")
    return deleted

def download_kokoro_cli(args: Optional[list[str]] = None) -> None:
    """CLI wrapper to download Kokoro models with terminal progress feedback."""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Download Kokoro TTS model files")
    parser.add_argument("--model", type=str, default="kokoro-v1.0", choices=list(KOKORO_MODELS.keys()), help="Model to download")
    parsed = parser.parse_args(args=args if args is not None else sys.argv[1:])
    model_id = parsed.model

    # Configure logging level for the CLI session
    logging.getLogger().setLevel(logging.WARNING)

    if is_kokoro_installed(model_id):
        print(f"Kokoro model {model_id} files are already installed.")
        return

    print(f"Downloading Kokoro TTS model {model_id} files (~{KOKORO_MODELS[model_id]['size_mb']} MB)...")

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
        success = download_kokoro(model_id=model_id, progress_cb=progress_cb)
        print()  # Newline after progress bar
        if success:
            print("✓ Kokoro model files downloaded successfully!")
        else:
            print("✗ Failed to download Kokoro model files.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n✗ Download interrupted by user.")
        sys.exit(1)

