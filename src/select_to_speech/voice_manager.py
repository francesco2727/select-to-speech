"""Piper voice management — download, delete, and list voices from HuggingFace."""

import logging
from pathlib import Path
from typing import Callable, Optional

import requests

from .config import get_data_dir

logger = logging.getLogger(__name__)

VOICES_INDEX_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
HF_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"

# In-process cache so multiple callers don't re-fetch within the same session.
_voice_index_cache: Optional[dict] = None


def fetch_voice_index(force: bool = False) -> dict:
    """Fetch and return the full piper voices index from HuggingFace.

    The result is cached in memory. Pass *force=True* to bypass the cache.
    Returns an empty dict on network failure.
    """
    global _voice_index_cache
    if _voice_index_cache is not None and not force:
        return _voice_index_cache
    try:
        logger.info("Fetching piper voices index from %s", VOICES_INDEX_URL)
        response = requests.get(VOICES_INDEX_URL, timeout=15)
        response.raise_for_status()
        _voice_index_cache = response.json()
        logger.info("Fetched %d voices from index", len(_voice_index_cache))
        return _voice_index_cache
    except Exception as exc:
        logger.error("Failed to fetch piper voices index: %s", exc)
        return {}


def list_remote_voices(lang_filter: Optional[str] = None) -> list[str]:
    """Return a sorted list of available voice names from the HuggingFace index.

    *lang_filter* is an ISO 639-1 language code (e.g. ``"en"``, ``"it"``).
    When given, only voices whose name starts with ``"{lang_filter}_"`` are returned.
    """
    index = fetch_voice_index()
    names = sorted(index.keys())
    if lang_filter:
        prefix = f"{lang_filter}_"
        names = [n for n in names if n.lower().startswith(prefix.lower())]
    return names


def _voices_dir() -> Path:
    d = get_data_dir() / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_installed(voice_name: str) -> bool:
    """Return True if both the .onnx and .onnx.json files are present locally."""
    d = _voices_dir()
    return (d / f"{voice_name}.onnx").exists() and (d / f"{voice_name}.onnx.json").exists()


def download_voice(
    voice_name: str,
    force: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Download a piper voice from HuggingFace.

    Args:
        voice_name: Voice identifier, e.g. ``"en_US-lessac-medium"``.
        force: If False and the voice is already installed, skip the download.
        progress_cb: Optional callback ``(downloaded_bytes, total_bytes)`` called
            after each network chunk. *total_bytes* is -1 when the server does not
            send Content-Length.

    Returns:
        True on success, False on failure.
    """
    if not force and is_installed(voice_name):
        logger.info("Voice '%s' is already installed. Use force=True to re-download.", voice_name)
        return True

    index = fetch_voice_index()
    if voice_name not in index:
        logger.error("Voice '%s' not found in the remote index.", voice_name)
        return False

    voice_info = index[voice_name]
    files: dict = voice_info.get("files", {})
    if not files:
        logger.error("No files listed for voice '%s'.", voice_name)
        return False

    dest_dir = _voices_dir()
    downloaded_total = 0

    # Compute overall total size from Content-Length hints stored in index (if any).
    # voices.json often has a "size_bytes" per file; fall back to -1 if absent.
    total_size = sum(
        meta.get("size_bytes", 0) if isinstance(meta, dict) else 0
        for meta in files.values()
    )
    if total_size == 0:
        total_size = -1

    for rel_path, _meta in files.items():
        url = HF_BASE_URL + rel_path
        # The filename is the last component of the relative path.
        filename = Path(rel_path).name
        dest = dest_dir / filename

        logger.info("Downloading %s → %s", url, dest)
        try:
            with requests.get(url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                file_total = int(resp.headers.get("Content-Length", -1))

                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        downloaded_total += len(chunk)
                        if progress_cb is not None:
                            cb_total = total_size if total_size != -1 else file_total
                            progress_cb(downloaded_total, cb_total)

            logger.info("Downloaded %s (%d bytes)", filename, dest.stat().st_size)
        except Exception as exc:
            logger.error("Failed to download %s: %s", url, exc)
            if dest.exists():
                dest.unlink()
            return False

    return True


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
        try:
            with requests.get(url, stream=True, timeout=60) as resp:
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
        except Exception as exc:
            logger.error("Failed to download %s: %s", url, exc)
            if dest.exists():
                dest.unlink()
            return False

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


# ── Piper voice management ────────────────────────────────────────────────────

def delete_voice(voice_name: str) -> bool:
    """Delete the local files for a piper voice.

    Removes ``{voice_name}.onnx`` and ``{voice_name}.onnx.json`` from the
    voices directory.

    Returns:
        True if at least one file was deleted, False if nothing was found.
    """
    d = _voices_dir()
    deleted = False
    for suffix in (".onnx", ".onnx.json"):
        path = d / f"{voice_name}{suffix}"
        if path.exists():
            path.unlink()
            logger.info("Deleted %s", path)
            deleted = True
    if not deleted:
        logger.warning("No files found for voice '%s'.", voice_name)
    return deleted
