"""Kokoro model management for sherpa-onnx — download, delete, and list models."""

import io
import logging
import shutil
import tarfile
from pathlib import Path
from typing import Callable, Optional

import requests

from .config import get_data_dir

logger = logging.getLogger(__name__)


def _voices_dir() -> Path:
    d = get_data_dir() / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Sherpa-ONNX Kokoro Models ──────────────────────────────────────────────────

SHERPA_TTS_BASE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
)

KOKORO_MODELS = {
    "kokoro-multi-lang-v1_0": {
        "name": "Kokoro v1.0 (FP32, ~350 MB)",
        "size_mb": 350,
        "archive": "kokoro-multi-lang-v1_0.tar.bz2",
        "dir_name": "kokoro-multi-lang-v1_0",
        "model_file": "model.onnx",
    },
    "kokoro-int8-multi-lang-v1_0": {
        "name": "Kokoro v1.0 (INT8, ~132 MB)",
        "size_mb": 132,
        "archive": "kokoro-int8-multi-lang-v1_0.tar.bz2",
        "dir_name": "kokoro-int8-multi-lang-v1_0",
        "model_file": "model.int8.onnx",
    },
}

# ── Speaker Mapping (sherpa-onnx Kokoro 54 speakers) ──────────────────────────

ID_TO_SPEAKER = {
    0: "af_alloy",
    1: "af_aoede",
    2: "af_bella",
    3: "af_heart",
    4: "af_jessica",
    5: "af_kore",
    6: "af_nicole",
    7: "af_nova",
    8: "af_river",
    9: "af_sarah",
    10: "af_sky",
    11: "am_adam",
    12: "am_echo",
    13: "am_eric",
    14: "am_fenrir",
    15: "am_liam",
    16: "am_michael",
    17: "am_onyx",
    18: "am_puck",
    19: "am_santa",
    20: "bf_alice",
    21: "bf_emma",
    22: "bf_isabella",
    23: "bf_lily",
    24: "bm_daniel",
    25: "bm_fable",
    26: "bm_george",
    27: "bm_lewis",
    28: "ef_dora",
    29: "em_alex",
    30: "ff_siwis",
    31: "hf_alpha",
    32: "hf_beta",
    33: "hm_omega",
    34: "hm_psi",
    35: "if_sara",
    36: "im_nicola",
    37: "jf_alpha",
    38: "jf_gongitsune",
    39: "jf_nezumi",
    40: "jf_tebukuro",
    41: "jm_kumo",
    42: "pf_dora",
    43: "pm_alex",
    44: "pm_santa",
    45: "zf_xiaobei",
    46: "zf_xiaoni",
    47: "zf_xiaoxiao",
    48: "zf_xiaoyi",
    49: "zm_yunjian",
    50: "zm_yunxi",
    51: "zm_yunxia",
    52: "zm_yunyang",
    53: "em_santa",
}

SPEAKER_TO_ID = {speaker: idx for idx, speaker in ID_TO_SPEAKER.items()}

# Old kokoro-onnx legacy filenames to clean up
LEGACY_KOKORO_FILES = [
    "kokoro-v1.0.onnx",
    "kokoro-v1.0.fp16.onnx",
    "kokoro-v1.0.int8.onnx",
    "voices-v1.0.bin",
]


def cleanup_legacy_kokoro() -> None:
    """Remove legacy kokoro-onnx files to free disk space."""
    d = _voices_dir()
    for filename in LEGACY_KOKORO_FILES:
        target = d / filename
        if target.exists():
            try:
                target.unlink()
                logger.info(f"Removed legacy kokoro-onnx file: {target}")
            except Exception as e:
                logger.warning(f"Could not remove legacy file {target}: {e}")


def is_kokoro_installed(model_id: str = "kokoro-multi-lang-v1_0") -> bool:
    """Return True if all Sherpa Kokoro model files are present locally."""
    if model_id not in KOKORO_MODELS:
        return False
    d = _voices_dir()
    model_dir = d / KOKORO_MODELS[model_id]["dir_name"]
    if not model_dir.is_dir():
        return False

    required = [
        KOKORO_MODELS[model_id]["model_file"],
        "voices.bin",
        "tokens.txt",
        "espeak-ng-data",
    ]
    return all((model_dir / f).exists() for f in required)


def download_kokoro(
    model_id: str = "kokoro-multi-lang-v1_0",
    force: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Download and extract Sherpa Kokoro model archive (.tar.bz2).

    Args:
        model_id: The ID of the model to download.
        force: Re-download even when files are already present.
        progress_cb: Optional callback ``(downloaded_bytes, total_bytes)``.

    Returns:
        True on success, False on any failure.
    """
    if model_id not in KOKORO_MODELS:
        logger.error("Unknown model_id: %s", model_id)
        return False

    # Automatically clean legacy kokoro-onnx files
    cleanup_legacy_kokoro()

    dest_dir = _voices_dir()
    model_dir = dest_dir / KOKORO_MODELS[model_id]["dir_name"]

    if not force and is_kokoro_installed(model_id):
        logger.info("Kokoro model already installed: %s", model_id)
        return True

    archive_name = KOKORO_MODELS[model_id]["archive"]
    archive_path = dest_dir / archive_name
    url = SHERPA_TTS_BASE_URL + archive_name

    logger.info("Downloading Sherpa Kokoro archive %s → %s", url, archive_path)
    max_retries = 3
    download_success = False

    for attempt in range(max_retries):
        try:
            downloaded_total = 0
            with requests.get(url, stream=True, timeout=(10, 180)) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("Content-Length", -1))

                with open(archive_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        downloaded_total += len(chunk)
                        if progress_cb is not None:
                            progress_cb(downloaded_total, total_size)

            logger.info("Downloaded %s (%d bytes)", archive_name, archive_path.stat().st_size)
            download_success = True
            break
        except Exception as exc:
            logger.error(
                "Failed to download %s (attempt %d/%d): %s",
                url,
                attempt + 1,
                max_retries,
                exc,
            )
            if archive_path.exists():
                archive_path.unlink()
            if attempt == max_retries - 1:
                return False
            import time
            time.sleep(2)

    if not download_success or not archive_path.exists():
        return False

    # Extract archive
    logger.info("Extracting %s into %s...", archive_path.name, dest_dir)
    try:
        # If directory already exists, clear it before fresh extraction
        if model_dir.exists():
            shutil.rmtree(model_dir)

        with tarfile.open(archive_path, "r:bz2") as tar:
            # Python 3.12+ safe extraction filter
            if hasattr(tarfile, "data_filter"):
                tar.extractall(dest_dir, filter="data")
            else:
                tar.extractall(dest_dir)

        # Remove archive after successful extraction to save disk space
        archive_path.unlink()
        logger.info("Successfully extracted and verified %s", model_id)
        return True
    except Exception as exc:
        logger.error("Failed to extract %s: %s", archive_path, exc, exc_info=True)
        if archive_path.exists():
            archive_path.unlink()
        if model_dir.exists():
            shutil.rmtree(model_dir)
        return False


def delete_kokoro(model_id: str = "kokoro-multi-lang-v1_0") -> bool:
    """Delete local Kokoro model directory."""
    if model_id not in KOKORO_MODELS:
        return False

    d = _voices_dir()
    model_dir = d / KOKORO_MODELS[model_id]["dir_name"]
    if model_dir.exists() and model_dir.is_dir():
        shutil.rmtree(model_dir)
        logger.info("Deleted %s", model_dir)
        return True
    logger.warning("No Kokoro model directory found to delete for %s", model_id)
    return False


def download_kokoro_cli() -> None:
    """CLI wrapper to download Kokoro models with terminal progress feedback."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Download Kokoro TTS model files")
    parser.add_argument(
        "--model",
        type=str,
        default="kokoro-multi-lang-v1_0",
        choices=list(KOKORO_MODELS.keys()),
        help="Model to download",
    )
    args = parser.parse_args()
    model_id = args.model

    logging.getLogger().setLevel(logging.WARNING)

    if is_kokoro_installed(model_id):
        print(f"Kokoro model {model_id} files are already installed.")
        return

    print(
        f"Downloading Kokoro TTS model {model_id} (~{KOKORO_MODELS[model_id]['size_mb']} MB)..."
    )

    last_pct = -1

    def progress_cb(downloaded: int, total: int) -> None:
        nonlocal last_pct
        if total > 0:
            pct = int((downloaded / total) * 100)
            if pct != last_pct:
                bar_length = 45
                filled_length = int(bar_length * pct // 100)
                bar = "█" * filled_length + "-" * (bar_length - filled_length)
                sys.stdout.write(
                    f"\rProgress: |{bar}| {pct}% ({downloaded / (1024*1024):.1f}/{total / (1024*1024):.1f} MB)"
                )
                sys.stdout.flush()
                last_pct = pct
        else:
            sys.stdout.write(f"\rDownloaded: {downloaded / (1024*1024):.1f} MB")
            sys.stdout.flush()

    try:
        success = download_kokoro(model_id=model_id, progress_cb=progress_cb)
        print()
        if success:
            print("✓ Kokoro model files downloaded and installed successfully!")
        else:
            print("✗ Failed to download Kokoro model files.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n✗ Download interrupted by user.")
        sys.exit(1)
