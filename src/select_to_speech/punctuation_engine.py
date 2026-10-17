"""Offline neural punctuation restoration using Sherpa-ONNX CT-Transformer.

Model supported:
- sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8
  Languages: English (en) and Chinese (zh).
"""

import io
import logging
import shutil
import tarfile
import threading
from pathlib import Path
from typing import Callable, Optional

import requests

from .config import get_data_dir

logger = logging.getLogger(__name__)

PUNCT_MODEL_ID = "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
PUNCT_MODEL_INFO = {
    "name": "CT-Transformer (ZH/EN, INT8, ~62 MB)",
    "archive": "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8.tar.bz2",
    "dir_name": "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8",
    "model_file": "model.int8.onnx",
    "supported_languages": ["en", "zh"],
    "download_url": (
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/"
        "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8.tar.bz2"
    ),
}


def _punct_dir() -> Path:
    d = get_data_dir() / "punctuation"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_punct_model_installed() -> bool:
    """Check if the punctuation model is downloaded and ready."""
    target_dir = _punct_dir() / PUNCT_MODEL_INFO["dir_name"]
    model_file = target_dir / PUNCT_MODEL_INFO["model_file"]
    return model_file.is_file() and model_file.stat().st_size > 1_000_000


def download_punct_model(
    force: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Download and unpack the neural punctuation model."""
    target_dir = _punct_dir() / PUNCT_MODEL_INFO["dir_name"]
    if not force and is_punct_model_installed():
        logger.info("Punctuation model already installed.")
        return True

    url = PUNCT_MODEL_INFO["download_url"]
    archive_path = _punct_dir() / PUNCT_MODEL_INFO["archive"]
    logger.info(f"Downloading neural punctuation model from {url}...")

    try:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()

            total = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(archive_path, "wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)

        logger.info(f"Punctuation archive downloaded ({downloaded} bytes). Extracting...")
        if target_dir.exists():
            shutil.rmtree(target_dir)

        with tarfile.open(archive_path, mode="r:bz2") as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(path=_punct_dir(), filter="data")
            else:
                tar.extractall(path=_punct_dir())

        archive_path.unlink(missing_ok=True)

        if is_punct_model_installed():
            logger.info("Neural punctuation model installed successfully.")
            return True
        else:
            logger.error("Punctuation model extraction completed, but model file was not found.")
            return False
    except Exception as e:
        logger.error(f"Failed to download punctuation model: {e}", exc_info=True)
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        return False


class NeuralPunctuationEngine:
    """Wrapper around sherpa_onnx.OfflinePunctuation with lazy-initialization."""

    def __init__(self, num_threads: int = 2, provider: str = "cpu"):
        self.num_threads = num_threads
        self.provider = provider
        self._punct = None
        self._lock = threading.Lock()

    def update_config(self, num_threads: int = 2, provider: str = "cpu") -> None:
        with self._lock:
            if self.num_threads != num_threads or self.provider != provider:
                self.num_threads = num_threads
                self.provider = provider
                self._punct = None

    def _init_model(self) -> bool:
        if self._punct is not None:
            return True

        if not is_punct_model_installed():
            logger.debug("Punctuation model not installed on disk.")
            return False

        try:
            import sherpa_onnx
        except ImportError:
            logger.error("sherpa_onnx not available for punctuation.")
            return False

        with self._lock:
            if self._punct is None:
                target_dir = _punct_dir() / PUNCT_MODEL_INFO["dir_name"]
                model_path = target_dir / PUNCT_MODEL_INFO["model_file"]
                logger.info(
                    f"Loading Sherpa-ONNX OfflinePunctuation ({model_path.name}, "
                    f"threads={self.num_threads}, provider='{self.provider}')..."
                )
                model_cfg = sherpa_onnx.OfflinePunctuationModelConfig(
                    ct_transformer=str(model_path),
                    num_threads=self.num_threads,
                    provider=self.provider,
                    debug=False,
                )
                cfg = sherpa_onnx.OfflinePunctuationConfig(model=model_cfg)
                self._punct = sherpa_onnx.OfflinePunctuation(cfg)
                logger.info("Sherpa-ONNX OfflinePunctuation initialized.")
        return True

    def add_punctuation(self, text: str, language: Optional[str] = None) -> str:
        """
        Add punctuation to unpunctuated text.
        Only runs for supported languages (en, zh).
        """
        if not text or not text.strip():
            return text

        lang = (language or "").split("-")[0].split("_")[0].lower()
        if lang not in PUNCT_MODEL_INFO["supported_languages"]:
            return text

        if not self._init_model():
            return text

        try:
            with self._lock:
                if self._punct is not None:
                    res = self._punct.add_punctuation(text)
                    return res if res else text
        except Exception as e:
            logger.warning(f"Neural punctuation restoration failed: {e}")

        return text
