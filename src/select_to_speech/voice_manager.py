"""Voice model management for sherpa-onnx (Kokoro and Piper) — download, delete, and list models."""

import functools
import json
import logging
import re
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


def _download_and_extract(
    archive_name: str,
    dir_name: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Download a sherpa-onnx ``tts-models`` archive and extract it into the voices dir.

    The archive unpacks into ``dir_name``; any previous copy of that directory is
    replaced. Returns True on success, False on any failure.
    """
    dest_dir = _voices_dir()
    model_dir = dest_dir / dir_name
    archive_path = dest_dir / archive_name
    url = SHERPA_TTS_BASE_URL + archive_name

    logger.info("Downloading sherpa-onnx archive %s → %s", url, archive_path)
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
        logger.info("Successfully extracted %s", dir_name)
        return True
    except Exception as exc:
        logger.error("Failed to extract %s: %s", archive_path, exc, exc_info=True)
        if archive_path.exists():
            archive_path.unlink()
        if model_dir.exists():
            shutil.rmtree(model_dir)
        return False


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

    if not force and is_kokoro_installed(model_id):
        logger.info("Kokoro model already installed: %s", model_id)
        return True

    info = KOKORO_MODELS[model_id]
    return _download_and_extract(info["archive"], info["dir_name"], progress_cb)


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


# ── Sherpa-ONNX Piper (VITS) Voices ───────────────────────────────────────────
#
# Unlike Kokoro (one model, 54 speakers), every Piper voice is a separate model
# archive, published in three precisions. The list of voices comes from the
# bundled catalog generated by scripts/update_piper_catalog.py.

PIPER_PRECISIONS = ("int8", "fp16", "fp32")
DEFAULT_PIPER_PRECISION = "int8"
_PIPER_CATALOG_PATH = Path(__file__).parent / "data" / "piper_voices.json"
_PIPER_DIR_RE = re.compile(r"^vits-piper-(?P<key>.+?)(?:-(?P<precision>int8|fp16))?$")


@functools.lru_cache(maxsize=1)
def load_piper_catalog() -> dict[str, dict]:
    """Return the bundled Piper voice catalog: ``{voice_key: info}``."""
    try:
        data = json.loads(_PIPER_CATALOG_PATH.read_text(encoding="utf-8"))
        return data.get("voices", {})
    except (OSError, ValueError) as exc:
        logger.error("Could not load the Piper voice catalog %s: %s", _PIPER_CATALOG_PATH, exc)
        return {}


def parse_voice_ref(ref: str) -> tuple[str, int]:
    """Split a Piper voice reference (``key`` or ``key#speaker_id``) into its parts."""
    key, sep, sid = (ref or "").partition("#")
    if sep and sid.isdigit():
        return key, int(sid)
    return key, 0


def format_voice_ref(key: str, speaker_id: int = 0) -> str:
    """Build the voice reference stored in ``piper_language_models``."""
    return f"{key}#{speaker_id}" if speaker_id else key


def resolve_piper_precision(key: str, precision: str) -> str:
    """Return *precision* if the voice is published in it, else the closest available one.

    A few voices exist only in fp32; asking for int8 then falls back to fp32.
    """
    sizes = load_piper_catalog().get(key, {}).get("sizes", {})
    if not sizes or precision in sizes:
        return precision if precision in PIPER_PRECISIONS else DEFAULT_PIPER_PRECISION
    for candidate in ("fp32", "fp16", "int8"):
        if candidate in sizes:
            return candidate
    return next(iter(sizes))


def piper_dir_name(key: str, precision: str) -> str:
    """Directory (and archive stem) of a Piper voice in the given precision."""
    precision = resolve_piper_precision(key, precision)
    suffix = "" if precision == "fp32" else f"-{precision}"
    return f"vits-piper-{key}{suffix}"


def piper_model_dir(key: str, precision: str) -> Path:
    return _voices_dir() / piper_dir_name(key, precision)


def piper_model_file(model_dir: Path) -> Optional[Path]:
    """Return the ``.onnx`` model inside an extracted Piper voice directory."""
    if not model_dir.is_dir():
        return None
    models = sorted(model_dir.glob("*.onnx"))
    return models[0] if models else None


def is_piper_installed(key: str, precision: str = DEFAULT_PIPER_PRECISION) -> bool:
    """Return True if the Piper voice files are present locally."""
    model_dir = piper_model_dir(key, precision)
    return (
        piper_model_file(model_dir) is not None
        and (model_dir / "tokens.txt").exists()
        and (model_dir / "espeak-ng-data").is_dir()
    )


def download_piper(
    key: str,
    precision: str = DEFAULT_PIPER_PRECISION,
    force: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Download and extract one Piper voice. Returns True on success."""
    if key not in load_piper_catalog():
        logger.error("Unknown Piper voice: %s", key)
        return False
    if not force and is_piper_installed(key, precision):
        logger.info("Piper voice already installed: %s (%s)", key, precision)
        return True
    dir_name = piper_dir_name(key, precision)
    if not _download_and_extract(f"{dir_name}.tar.bz2", dir_name, progress_cb):
        return False
    if not is_piper_installed(key, precision):
        logger.error("Piper archive %s did not contain the expected files", dir_name)
        return False
    return True


def delete_piper(key: str, precision: str = DEFAULT_PIPER_PRECISION) -> bool:
    """Delete a downloaded Piper voice."""
    model_dir = piper_model_dir(key, precision)
    if model_dir.is_dir():
        shutil.rmtree(model_dir)
        logger.info("Deleted %s", model_dir)
        return True
    logger.warning("No Piper voice directory found to delete for %s (%s)", key, precision)
    return False


def get_piper_speakers(key: str, precision: Optional[str] = None) -> list[str]:
    """Speaker names of a multi-speaker Piper voice, ordered by speaker id.

    Single-speaker voices return an empty list. An installed voice is read from its
    ``*.onnx.json`` (authoritative); otherwise the bundled catalog is used.
    """
    precisions = [precision] if precision else list(PIPER_PRECISIONS)
    for p in precisions:
        model_file = piper_model_file(piper_model_dir(key, p))
        if model_file is None:
            continue
        meta_file = model_file.with_name(model_file.name + ".json")
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            break
        id_map = meta.get("speaker_id_map") or {}
        if meta.get("num_speakers", 1) > 1 and id_map:
            return [name for name, _ in sorted(id_map.items(), key=lambda kv: kv[1])]
        return []
    return list(load_piper_catalog().get(key, {}).get("speakers", []))


def get_piper_languages() -> list[str]:
    """ISO 639-1 codes of the languages with at least one Piper voice."""
    return sorted({v["language"] for v in load_piper_catalog().values()})


def get_piper_voices(language: str, precision: str = DEFAULT_PIPER_PRECISION) -> list[dict]:
    """Piper voices for *language*, with size and install state for *precision*."""
    voices = []
    for key, info in load_piper_catalog().items():
        if info.get("language") != language:
            continue
        effective = resolve_piper_precision(key, precision)
        voices.append({
            "id": key,
            "name": info.get("name", key),
            "locale": info.get("locale", ""),
            "quality": info.get("quality"),
            "precision": effective,
            "size_bytes": info.get("sizes", {}).get(effective, 0),
            "installed": is_piper_installed(key, effective),
            "speakers": get_piper_speakers(key, effective),
        })
    return voices


# ── Installed models (both engines) ───────────────────────────────────────────


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def list_installed_models() -> list[dict]:
    """Every downloaded Kokoro model and Piper voice, with its disk usage."""
    voices_dir = _voices_dir()
    installed = []
    for model_id, info in KOKORO_MODELS.items():
        model_dir = voices_dir / info["dir_name"]
        if model_dir.is_dir():
            installed.append({
                "engine": "kokoro",
                "id": model_id,
                "precision": None,
                "name": info["name"],
                "language": None,
                "size_bytes": _dir_size(model_dir),
            })
    catalog = load_piper_catalog()
    for model_dir in sorted(voices_dir.glob("vits-piper-*")):
        match = _PIPER_DIR_RE.match(model_dir.name)
        if not match or not model_dir.is_dir():
            continue
        key = match["key"]
        info = catalog.get(key, {})
        installed.append({
            "engine": "piper",
            "id": key,
            "precision": match["precision"] or "fp32",
            "name": info.get("name", key),
            "language": info.get("language"),
            "size_bytes": _dir_size(model_dir),
        })
    return installed


def download_kokoro_cli(argv: list[str] | None = None) -> None:
    """CLI wrapper to download Kokoro models with terminal progress feedback.

    ``argv`` defaults to ``sys.argv[1:]`` (console-script usage).
    """
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
    args = parser.parse_args(argv)
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
