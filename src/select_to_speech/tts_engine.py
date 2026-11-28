"""Text-to-Speech engine implementations using Sherpa-ONNX."""

import logging
import queue
import re
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Iterator, Optional, Tuple, Union

import emoji
import numpy as np

from .config import VoiceConfig, get_data_dir
from .voice_manager import (
    DEFAULT_PIPER_PRECISION,
    KOKORO_MODELS,
    SPEAKER_TO_ID,
    download_piper,
    is_kokoro_installed,
    is_piper_installed,
    load_piper_catalog,
    parse_voice_ref,
    piper_model_dir,
    piper_model_file,
    resolve_piper_precision,
)

logger = logging.getLogger(__name__)


# Kokoro voice-name prefixes by language
_KOKORO_LANG_PREFIXES: dict[str, tuple[str, ...]] = {
    "en": ("af_", "am_", "bf_", "bm_"),
    "es": ("ef_", "em_"),
    "fr": ("ff_",),
    "hi": ("hf_", "hm_"),
    "it": ("if_", "im_"),
    "ja": ("jf_", "jm_"),
    "ko": (),
    "pt": ("pf_", "pm_"),
    "zh": ("zf_", "zm_"),
}

# Kokoro lang codes passed to espeak/sherpa GenerationConfig.extra["lang"]
_KOKORO_LANG_CODES: dict[str, str] = {
    "en": "en-us",
    "es": "es",
    "fr": "fr",
    "hi": "hi",
    "it": "it",
    "ja": "ja",
    "ko": "ko",
    "pt": "pt-br",
    "zh": "zh",
}

# Currency symbol to dictionary key mapping
_CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "dollar",
    "€": "euro",
    "£": "pound",
    "¥": "yen",
    "₹": "rupee",
    "₽": "ruble",
    "₩": "won",
    "¢": "cent",
    "฿": "baht",
    "₺": "lira",
    "₴": "hryvnia",
}

# Word mappings for mathematical symbols and punctuation by language
_SYMBOL_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "percent": "percent",
        "plus": "plus",
        "minus": "minus",
        "times": "times",
        "divide": "divided by",
        "equals": "equals",
        "less": "less than",
        "greater": "greater than",
        "dot": "dot",
        "dollar": "dollars",
        "euro": "euros",
        "pound": "pounds",
        "yen": "yen",
        "rupee": "rupees",
        "ruble": "rubles",
        "won": "won",
        "cent": "cents",
        "baht": "baht",
        "lira": "lira",
        "hryvnia": "hryvnia",
        "at": "at",
    },
    "it": {
        "percent": "percento",
        "plus": "più",
        "minus": "meno",
        "times": "per",
        "divide": "diviso",
        "equals": "uguale",
        "less": "minore di",
        "greater": "maggiore di",
        "dot": "punto",
        "dollar": "dollari",
        "euro": "euro",
        "pound": "sterline",
        "yen": "yen",
        "rupee": "rupie",
        "ruble": "rubli",
        "won": "won",
        "cent": "centesimi",
        "baht": "baht",
        "lira": "lire",
        "hryvnia": "grivne",
        "at": "chiocciola",
    },
    "es": {
        "percent": "por ciento",
        "plus": "más",
        "minus": "menos",
        "times": "por",
        "divide": "dividido por",
        "equals": "igual a",
        "less": "menor que",
        "greater": "mayor que",
        "dot": "punto",
        "dollar": "dólares",
        "euro": "euros",
        "pound": "libras",
        "yen": "yenes",
        "rupee": "rupias",
        "ruble": "rublos",
        "won": "won",
        "cent": "centavos",
        "baht": "baht",
        "lira": "liras",
        "hryvnia": "grivnas",
        "at": "arroba",
    },
    "fr": {
        "percent": "pour cent",
        "plus": "plus",
        "minus": "moins",
        "times": "fois",
        "divide": "divisé par",
        "equals": "égal",
        "less": "inférieur à",
        "greater": "supérieur à",
        "dot": "point",
        "dollar": "dollars",
        "euro": "euros",
        "pound": "livres",
        "yen": "yens",
        "rupee": "roupies",
        "ruble": "roubles",
        "won": "wons",
        "cent": "centimes",
        "baht": "bahts",
        "lira": "lires",
        "hryvnia": "hryvnias",
        "at": "arobase",
    },
    "de": {
        "percent": "Prozent",
        "plus": "plus",
        "minus": "minus",
        "times": "mal",
        "divide": "geteilt durch",
        "equals": "gleich",
        "less": "kleiner als",
        "greater": "größer als",
        "dot": "Punkt",
        "dollar": "Dollar",
        "euro": "Euro",
        "pound": "Pfund",
        "yen": "Yen",
        "rupee": "Rupien",
        "ruble": "Rubel",
        "won": "Won",
        "cent": "Cent",
        "baht": "Baht",
        "lira": "Lira",
        "hryvnia": "Hrywnja",
        "at": "at",
    },
    "pt": {
        "percent": "por cento",
        "plus": "mais",
        "minus": "menos",
        "times": "vezes",
        "divide": "dividido por",
        "equals": "igual a",
        "less": "menor que",
        "greater": "maior que",
        "dot": "ponto",
        "dollar": "dólares",
        "euro": "euros",
        "pound": "libras",
        "yen": "ienes",
        "rupee": "rúpias",
        "ruble": "rublos",
        "won": "won",
        "cent": "centavos",
        "baht": "baht",
        "lira": "liras",
        "hryvnia": "grivnas",
        "at": "arroba",
    },
    "ja": {
        "percent": "パーセント",
        "plus": "プラス",
        "minus": "マイナス",
        "times": "かける",
        "divide": "わる",
        "equals": "イコール",
        "less": "より小さい",
        "greater": "より大きい",
        "dot": "ドット",
        "dollar": "ドル",
        "euro": "ユーロ",
        "pound": "ポンド",
        "yen": "円",
        "rupee": "ルピー",
        "ruble": "ルーブル",
        "won": "ウォン",
        "cent": "セント",
        "baht": "バーツ",
        "lira": "リラ",
        "hryvnia": "フリヴニャ",
        "at": "アット",
    },
    "zh": {
        "percent": "百分之",
        "plus": "加",
        "minus": "减",
        "times": "乘",
        "divide": "除以",
        "equals": "等于",
        "less": "小于",
        "greater": "大于",
        "dot": "点",
        "dollar": "美元",
        "euro": "欧元",
        "pound": "英镑",
        "yen": "日元",
        "rupee": "卢比",
        "ruble": "卢布",
        "won": "韩元",
        "cent": "分",
        "baht": "泰铢",
        "lira": "里拉",
        "hryvnia": "格里夫纳",
        "at": "艾特",
    },
    "hi": {
        "percent": "प्रतिशत",
        "plus": "प्लस",
        "minus": "माइनस",
        "times": "गुना",
        "divide": "भागा",
        "equals": "बराबर",
        "less": "से कम",
        "greater": "से बड़ा",
        "dot": "डॉट",
        "dollar": "डॉलर",
        "euro": "यूरो",
        "pound": "पाउंड",
        "yen": "येन",
        "rupee": "रुपए",
        "ruble": "रूबल",
        "won": "वॉन",
        "cent": "सेंट",
        "baht": "बात",
        "lira": "लीरा",
        "hryvnia": "रिव्निया",
        "at": "एट",
    },
    "ko": {
        "percent": "퍼센트",
        "plus": "더하기",
        "minus": "빼기",
        "times": "곱하기",
        "divide": "나누기",
        "equals": "는",
        "less": "보다 작음",
        "greater": "보다 큼",
        "dot": "점",
        "dollar": "달러",
        "euro": "유로",
        "pound": "파운드",
        "yen": "엔",
        "rupee": "루피",
        "ruble": "루블",
        "won": "원",
        "cent": "센트",
        "baht": "바트",
        "lira": "리라",
        "hryvnia": "흐리우냐",
        "at": "골뱅이",
    },
}


# Typographic quotes, dashes and ellipsis → their plain ASCII spelling (one pass)
_TYPOGRAPHY_TABLE = str.maketrans(
    {
        **dict.fromkeys("\u2019\u2018\u02bc\u02bb\u00b4\u0060", "'"),
        **dict.fromkeys("\u201c\u201d\u00ab\u00bb", '"'),
        "\u2014": " - ",
        "\u2013": " - ",
        "\u2026": "...",
    }
)

# Precompiled regular expressions for text preprocessing
_RE_EMOJI_COLON = re.compile(r":([^:]+):")
_RE_DATE_PATTERNS = [
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2}\b"),
    re.compile(r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/-]\d{4}\b"),
]
_RE_DOT = re.compile(
    r"(?<=[a-zA-Z_-])\.(?=[a-zA-Z0-9_-])|(?<=[a-zA-Z0-9_-])\.(?=[a-zA-Z_-])"
)
_SCALE_WORDS = (
    r"(?:thousand|thousands|million|millions|billion|billions|trillion|trillions|"
    r"mila|milione|milioni|miliardo|miliardi|mil|millón|millones|billón|billones|"
    r"mille|millier|milliers|milliard|milliards|Tausend|Million|Millionen|Milliarde|Milliarden|"
    r"milhão|milhões|bilhão|bilhões|bilião|biliões)"
)
_RE_PREFIX_CURRENCY = re.compile(
    rf"([$€£¥₹₽₩¢฿₺₴])\s*(\d+(?:[.,]\d+)*)(?:\s+({_SCALE_WORDS})\b)?",
    re.IGNORECASE,
)
_RE_MINUS_SPACED = re.compile(r"\s+-\s+")
_RE_MINUS_NUMBER = re.compile(r"(^|\s)-(?=\d)")
_RE_TIMES_DIGIT = re.compile(r"(?<=\d)\s*\*\s*(?=\d)")
_RE_TIMES_SPACED = re.compile(r"\s+\*\s+")
_RE_DIVIDE_DIGIT = re.compile(r"(?<=\d)\s*/\s*(?=\d)")
_RE_DIVIDE_SPACED = re.compile(r"\s+/\s+")
_RE_DATE_SEP = re.compile(r"[/-]")
_RE_WHITESPACE = re.compile(r"\s+")
_RE_SANITIZE_CHARS = re.compile(r"[^\w\s.,!?;:\'\"/-]")
_RE_NEWLINE_WITH_PUNCT = re.compile(r"([.!?])\s*\n+")
_RE_NEWLINE_NO_PUNCT = re.compile(r"([^.!?\s])\s*\n+")


class BaseTTSEngine(ABC):
    """Abstract base class for TTS engines"""

    def __init__(self, voice_config: VoiceConfig):
        self.voice_config = voice_config
        self.voices_dir = get_data_dir() / "voices"
        self.voices_dir.mkdir(parents=True, exist_ok=True)

    def update_config(self, voice_config: VoiceConfig) -> None:
        """Update voice configuration."""
        self.voice_config = voice_config

    def preprocess_text(self, text: str, language: Optional[str] = None) -> str:
        """Preprocess text to replace mathematical symbols, currency symbols, and dots in domains/filenames with words."""
        if not text:
            return text

        # Normalize typographical apostrophes, quotes, dashes and ellipsis
        text = text.translate(_TYPOGRAPHY_TABLE)

        lang_key = (language or "").split("-")[0].split("_")[0].lower() or "en"
        # Languages without a word table (e.g. Polish with a Piper voice) keep their
        # symbols untouched rather than having them read out in English.
        words = _SYMBOL_WORDS.get(lang_key)

        # Convert emojis to text in the requested language; drop them when the
        # language has no emoji names.
        if lang_key in emoji.LANGUAGES:
            try:
                demojized = emoji.demojize(text, language=lang_key)
            except (KeyError, ValueError, TypeError):
                demojized = emoji.replace_emoji(text, replace=" ")
        else:
            demojized = emoji.replace_emoji(text, replace=" ")
        text = _RE_EMOJI_COLON.sub(
            lambda m: " " + m.group(1).replace("_", " ") + " ", demojized
        )

        if words is None:
            return text

        # Mask dates to prevent their separators from being replaced by math operations
        date_placeholders: dict[str, str] = {}

        def _mask_date(match: re.Match) -> str:
            placeholder = f"__DATE_{len(date_placeholders)}__"
            date_placeholders[placeholder] = match.group(0)
            return placeholder

        for pattern in _RE_DATE_PATTERNS:
            text = pattern.sub(_mask_date, text)

        # Replace dots in domains/filenames
        text = _RE_DOT.sub(f" {words['dot']} ", text)

        def _replace_prefix_currency(match: re.Match) -> str:
            sym = match.group(1)
            num = match.group(2)
            scale = match.group(3)
            sym_key = _CURRENCY_SYMBOLS.get(sym, "")
            sym_name = words.get(sym_key, "")
            if not sym_name:
                return match.group(0)
            if scale:
                return f" {num} {scale} {sym_name} "
            return f" {num} {sym_name} "

        text = _RE_PREFIX_CURRENCY.sub(_replace_prefix_currency, text)

        for sym, key in _CURRENCY_SYMBOLS.items():
            if sym in text:
                sym_name = words.get(key, "")
                if sym_name:
                    text = text.replace(sym, f" {sym_name} ")

        if "@" in text:
            text = text.replace("@", f" {words['at']} ")
        if "%" in text:
            text = text.replace("%", f" {words['percent']} ")
        if "+" in text:
            text = text.replace("+", f" {words['plus']} ")

        if "-" in text:
            text = _RE_MINUS_SPACED.sub(f" {words['minus']} ", text)
            text = _RE_MINUS_NUMBER.sub(rf"\1{words['minus']} ", text)

        if "*" in text:
            text = _RE_TIMES_DIGIT.sub(f" {words['times']} ", text)
            text = _RE_TIMES_SPACED.sub(f" {words['times']} ", text)

        if "/" in text:
            text = _RE_DIVIDE_DIGIT.sub(f" {words['divide']} ", text)
            text = _RE_DIVIDE_SPACED.sub(f" {words['divide']} ", text)

        if "=" in text:
            text = text.replace("=", f" {words['equals']} ")
        if "<" in text:
            text = text.replace("<", f" {words['less']} ")
        if ">" in text:
            text = text.replace(">", f" {words['greater']} ")

        for placeholder, original_date in date_placeholders.items():
            spaced_date = _RE_DATE_SEP.sub(" ", original_date)
            text = text.replace(placeholder, spaced_date)

        return text

    def _sanitize_text(
        self,
        text: str,
        language: Optional[str] = None,
        already_preprocessed: bool = False,
    ) -> str:
        """Sanitize text for TTS processing."""
        if not already_preprocessed:
            text = self.preprocess_text(text, language)

        text = text.translate(_TYPOGRAPHY_TABLE)

        # Turn line breaks into periods or spaces with natural pauses
        text = _RE_NEWLINE_WITH_PUNCT.sub(r"\1 ", text)
        text = _RE_NEWLINE_NO_PUNCT.sub(r"\1. ", text)

        text = text.replace('"""', '"')
        text = text.replace("'''", "'")
        text = _RE_WHITESPACE.sub(" ", text)
        text = _RE_SANITIZE_CHARS.sub("", text)
        text = text.strip()
        logger.debug(f"Sanitized: '{text[:100]}{'...' if len(text) > 100 else ''}'")
        return text

    def _language_models(self) -> dict:
        """Language → voice map of the active engine."""
        active = getattr(self.voice_config, "active_language_models", None)
        if callable(active):
            models = active()
            if isinstance(models, dict):
                return models
        return getattr(self.voice_config, "language_models", {}) or {}

    def get_model_for_language(self, language: str) -> str:
        """Get the voice for a language, falling back to the default language's voice."""
        models = self._language_models()
        model = models.get(language)
        if model:
            return model
        default_lang = getattr(self.voice_config, "language", None)
        fallback = models.get(default_lang) if default_lang else None
        if not fallback:
            fallback = next((v for v in models.values() if v), "")
        logger.warning(
            f"No voice configured for language '{language}', using '{fallback}'"
        )
        return fallback

    def warmup(self) -> bool:
        """Pre-warm TTS model/buffers in background if supported."""
        return True

    @abstractmethod
    def synthesize_stream(
        self,
        text: str,
        language: Optional[str] = None,
        speed: float = 1.0,
        volume: float = 1.0,
        phoneme_lang: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Iterator[Tuple[bytes, int]]:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass


def _import_sherpa_onnx():
    """Import sherpa_onnx, or return None if it is missing or an unsupported version."""
    try:
        import sherpa_onnx
    except ImportError:
        logger.error(
            "Failed to import sherpa_onnx. Ensure sherpa-onnx and sherpa-onnx-core are installed.",
            exc_info=True,
        )
        return None

    sherpa_version = getattr(sherpa_onnx, "__version__", "")
    try:
        sherpa_major = int(sherpa_version.split(".")[0])
    except (ValueError, IndexError):
        sherpa_major = 0
    if sherpa_major >= 2:
        logger.error(
            "sherpa-onnx %s is not supported: starting from v2.0.0 espeak-ng G2P was removed, "
            "so non-English languages (e.g. Italian) cannot be phonemized and will be garbled. "
            "Install sherpa-onnx < 2.0.0.",
            sherpa_version or ">=2",
        )
        return None
    return sherpa_onnx


class _SherpaEngine(BaseTTSEngine):
    """Shared Sherpa-ONNX streaming synthesis for Kokoro and Piper.

    Subclasses implement :meth:`_prepare_generation`, returning the loaded
    ``OfflineTts`` and its ``GenerationConfig`` for a language.
    """

    def __init__(self, voice_config: VoiceConfig):
        super().__init__(voice_config)
        self._lock = threading.Lock()

    def _get_effective_threads(self) -> int:
        """Resolve effective number of inference threads (0 = auto-detect)."""
        cfg_threads = getattr(self.voice_config, "num_threads", 0)
        if cfg_threads > 0:
            return cfg_threads
        from .system_check import get_hardware_info

        return get_hardware_info().get("optimal_threads", 4)

    @abstractmethod
    def _prepare_generation(
        self,
        language: Optional[str],
        phoneme_lang: Optional[str],
        speed: float,
    ) -> Optional[Tuple[object, object, str]]:
        """Return ``(tts, gen_config, description)``, or None if no model is usable."""

    def synthesize_stream(
        self,
        text: str,
        language: Optional[str] = None,
        speed: float = 1.0,
        volume: float = 1.0,
        phoneme_lang: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Iterator[Tuple[Union[np.ndarray, bytes], int]]:
        if not text or not text.strip():
            return

        prepared = self._prepare_generation(language, phoneme_lang, speed)
        if prepared is None:
            return
        tts, gen_config, _desc = prepared
        sample_rate = tts.sample_rate

        # Queue to pass raw float32 audio chunks produced by Sherpa C++ callback to this generator
        audio_chunk_queue: queue.Queue[Optional[Tuple[np.ndarray, int]]] = queue.Queue(
            maxsize=16
        )
        synthesis_error: list[Optional[Exception]] = [None]

        def _on_samples(samples: np.ndarray, _progress: float) -> int:
            if stop_event is not None and stop_event.is_set():
                return 0  # Stop C++ generation immediately

            if len(samples) > 0:
                s = np.asarray(samples, dtype=np.float32)
                if volume != 1.0:
                    s = np.clip(s * volume, -1.0, 1.0)
                else:
                    s = s.copy()
                audio_chunk_queue.put((s, sample_rate))

            return 0 if (stop_event is not None and stop_event.is_set()) else 1

        def _worker():
            try:
                # Sanitize text without splitting into artificial small chunks
                clean_text = self._sanitize_text(
                    text, language=language, already_preprocessed=True
                )
                if not clean_text:
                    return

                with self._lock:
                    tts.generate(clean_text, gen_config, callback=_on_samples)
            except Exception as e:
                synthesis_error[0] = e
                logger.error(
                    f"Error in Sherpa-ONNX streaming generation: {e}", exc_info=True
                )
            finally:
                audio_chunk_queue.put(None)  # Signal EOF to generator

        worker_thread = threading.Thread(target=_worker, daemon=True)
        worker_thread.start()

        while True:
            if stop_event is not None and stop_event.is_set():
                break

            try:
                item = audio_chunk_queue.get(timeout=0.1)
            except queue.Empty:
                if not worker_thread.is_alive():
                    break
                continue

            if item is None:
                break

            yield item

        if synthesis_error[0] is not None:
            raise synthesis_error[0]

    def release_model(
        self, engine: str, model_id: str, precision: Optional[str] = None
    ) -> None:
        """Drop a loaded model whose files were deleted from disk."""

    def warmup(self) -> bool:
        """Pre-warm the default-language model so the first request starts fast."""
        try:
            if not self._is_default_model_installed():
                logger.debug(
                    "TTS model for the default language not downloaded yet, skipping warmup"
                )
                return False
            prepared = self._prepare_generation(self.voice_config.language, None, 1.0)
            if prepared is None:
                return False
            tts, gen_config, desc = prepared
            with self._lock:
                logger.info(f"Pre-warming Sherpa-ONNX TTS engine ({desc})...")
                tts.generate("a", gen_config)
            logger.info("Sherpa-ONNX TTS engine warmup completed.")
            return True
        except Exception as e:
            logger.warning(f"Sherpa TTS warmup failed (non-fatal): {e}")
        return False

    @abstractmethod
    def _is_default_model_installed(self) -> bool:
        """Whether the model the default language uses is on disk (no download on warmup)."""


class KokoroEngine(_SherpaEngine):
    """Text-to-Speech engine wrapper for Kokoro using Sherpa-ONNX."""

    def __init__(self, voice_config: VoiceConfig):
        super().__init__(voice_config)
        self.model_id = getattr(self.voice_config, "model", "kokoro-multi-lang-v1_0")
        if self.model_id not in KOKORO_MODELS:
            self.model_id = "kokoro-multi-lang-v1_0"

        self.model_dir = self.voices_dir / KOKORO_MODELS[self.model_id]["dir_name"]
        self.tts = None

    def update_config(self, voice_config: VoiceConfig) -> None:
        """Update voice configuration and reload Sherpa-ONNX model if changed."""
        new_model_id = getattr(voice_config, "model", "kokoro-multi-lang-v1_0")
        if new_model_id not in KOKORO_MODELS:
            new_model_id = "kokoro-multi-lang-v1_0"

        with self._lock:
            old_model_id = self.model_id
            old_threads = getattr(self.voice_config, "num_threads", 0)
            old_provider = getattr(self.voice_config, "provider", "cpu")
            self.voice_config = voice_config

            new_threads = getattr(voice_config, "num_threads", 0)
            new_provider = getattr(voice_config, "provider", "cpu")

            reload_needed = (
                new_model_id != old_model_id
                or new_threads != old_threads
                or new_provider != old_provider
            )

            if reload_needed:
                logger.info(
                    f"TTS configuration changed (model: '{old_model_id}'->'{new_model_id}', "
                    f"threads: {old_threads}->{new_threads}, provider: '{old_provider}'->'{new_provider}'). "
                    "Resetting Sherpa-ONNX session for lazy reload."
                )
                self.model_id = new_model_id
                self.model_dir = (
                    self.voices_dir / KOKORO_MODELS[self.model_id]["dir_name"]
                )
                self.tts = None
            else:
                logger.debug(
                    f"Kokoro voice config updated (session retained for '{self.model_id}')."
                )

    def ensure_model_downloaded(self) -> bool:
        """Download and extract Sherpa Kokoro model archive if missing."""
        from . import voice_manager

        if voice_manager.is_kokoro_installed(self.model_id):
            return True
        logger.info(f"Kokoro model missing — downloading {self.model_id}...")
        return voice_manager.download_kokoro(self.model_id)

    def _init_tts(self) -> bool:
        if self.tts is not None:
            return True

        if not self.ensure_model_downloaded():
            return False

        sherpa_onnx = _import_sherpa_onnx()
        if sherpa_onnx is None:
            return False

        with self._lock:
            if self.tts is None:
                info = KOKORO_MODELS[self.model_id]
                model_file = self.model_dir / info["model_file"]
                voices_bin = self.model_dir / "voices.bin"
                tokens_txt = self.model_dir / "tokens.txt"
                espeak_dir = self.model_dir / "espeak-ng-data"

                lexicons = []
                for lex_name in ("lexicon-us-en.txt", "lexicon-zh.txt"):
                    lex_file = self.model_dir / lex_name
                    if lex_file.exists():
                        lexicons.append(str(lex_file))
                lexicon_arg = ",".join(lexicons)

                threads = self._get_effective_threads()
                provider = getattr(self.voice_config, "provider", "cpu") or "cpu"

                logger.info(
                    f"Initializing Sherpa-ONNX Kokoro TTS from {model_file.name} "
                    f"({threads} threads, provider='{provider}')..."
                )
                kokoro_config = sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(model_file),
                    voices=str(voices_bin),
                    tokens=str(tokens_txt),
                    lexicon=lexicon_arg,
                    data_dir=str(espeak_dir),
                    dict_dir="",
                    length_scale=1.0,
                    lang="",
                )
                model_config = sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=kokoro_config,
                    num_threads=threads,
                    debug=False,
                    provider=provider,
                )
                tts_config = sherpa_onnx.OfflineTtsConfig(
                    model=model_config,
                    max_num_sentences=1,
                    silence_scale=0.2,
                )
                self.tts = sherpa_onnx.OfflineTts(tts_config)
                logger.info(
                    f"Sherpa-ONNX Kokoro TTS initialized successfully ({threads} threads)."
                )
        return True

    def _resolve_speaker_and_lang(
        self,
        language: Optional[str] = None,
        phoneme_lang: Optional[str] = None,
    ) -> Tuple[int, str]:
        """Resolve speaker integer ID and language code for sherpa GenerationConfig."""
        voice_name = self.get_model_for_language(
            language or getattr(self.voice_config, "language", "en")
        )

        speaker_id = SPEAKER_TO_ID.get(voice_name, 3)  # Default fallback 3 ('af_heart')

        effective_lang = phoneme_lang or language
        lang_code = (
            _KOKORO_LANG_CODES.get(effective_lang, "en-us")
            if effective_lang
            else "en-us"
        )

        return speaker_id, lang_code

    def _prepare_generation(self, language, phoneme_lang, speed):
        if not self._init_tts():
            return None
        import sherpa_onnx

        sid, lang_code = self._resolve_speaker_and_lang(language, phoneme_lang)
        gen_config = sherpa_onnx.GenerationConfig()
        gen_config.sid = sid
        gen_config.speed = speed
        gen_config.extra = {"lang": lang_code}
        return self.tts, gen_config, f"sid={sid}, lang={lang_code}"

    def _is_default_model_installed(self) -> bool:
        return is_kokoro_installed(self.model_id)

    def release_model(
        self, engine: str, model_id: str, precision: Optional[str] = None
    ) -> None:
        if engine == "kokoro" and model_id == self.model_id:
            with self._lock:
                self.tts = None

    def stop(self) -> None:
        self.tts = None
        logger.info("Sherpa Kokoro engine stopped")


class PiperEngine(_SherpaEngine):
    """Piper (VITS) voices through Sherpa-ONNX.

    Each Piper voice is its own model, so one ``OfflineTts`` is kept per voice; the
    least recently used one is dropped once more than ``MAX_LOADED_VOICES`` are loaded
    (mixed-language text then does not reload a model on every segment).
    """

    MAX_LOADED_VOICES = 3

    def __init__(self, voice_config: VoiceConfig):
        super().__init__(voice_config)
        self._models: OrderedDict[tuple[str, str], object] = OrderedDict()

    @property
    def precision(self) -> str:
        return (
            getattr(self.voice_config, "piper_precision", DEFAULT_PIPER_PRECISION)
            or DEFAULT_PIPER_PRECISION
        )

    def update_config(self, voice_config: VoiceConfig) -> None:
        with self._lock:
            old = self.voice_config
            self.voice_config = voice_config
            changed = (
                getattr(old, "num_threads", 0)
                != getattr(voice_config, "num_threads", 0)
                or getattr(old, "provider", "cpu")
                != getattr(voice_config, "provider", "cpu")
                or getattr(old, "piper_precision", None)
                != getattr(voice_config, "piper_precision", None)
            )
            if changed:
                logger.info(
                    "Piper threads/provider/precision changed — unloading cached voices."
                )
                self._models.clear()

    def _resolve_voice(self, language: Optional[str]) -> Optional[Tuple[str, int]]:
        ref = self.get_model_for_language(
            language or getattr(self.voice_config, "language", "en")
        )
        if not ref:
            return None
        key, sid = parse_voice_ref(ref)
        if key not in load_piper_catalog() and not is_piper_installed(
            key, self.precision
        ):
            logger.error(f"Unknown Piper voice '{key}'")
            return None
        return key, sid

    def _load_voice(self, key: str, precision: str):
        """Return the loaded ``OfflineTts`` of a voice, downloading it if missing."""
        precision = resolve_piper_precision(key, precision)
        cache_key = (key, precision)
        with self._lock:
            tts = self._models.get(cache_key)
            if tts is not None:
                self._models.move_to_end(cache_key)
                return tts

        if not is_piper_installed(key, precision):
            logger.info(f"Piper voice missing — downloading {key} ({precision})...")
            if not download_piper(key, precision):
                return None

        sherpa_onnx = _import_sherpa_onnx()
        if sherpa_onnx is None:
            return None

        model_dir = piper_model_dir(key, precision)
        model_file = piper_model_file(model_dir)
        if model_file is None:
            logger.error(f"No .onnx model found in {model_dir}")
            return None

        threads = self._get_effective_threads()
        provider = getattr(self.voice_config, "provider", "cpu") or "cpu"
        logger.info(
            f"Initializing Sherpa-ONNX Piper voice {key} ({precision}, {threads} threads, provider='{provider}')..."
        )
        vits_config = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(model_file),
            lexicon="",
            tokens=str(model_dir / "tokens.txt"),
            data_dir=str(model_dir / "espeak-ng-data"),
            dict_dir="",
        )
        model_config = sherpa_onnx.OfflineTtsModelConfig(
            vits=vits_config,
            num_threads=threads,
            debug=False,
            provider=provider,
        )
        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=model_config,
            max_num_sentences=1,
            silence_scale=0.2,
        )
        tts = sherpa_onnx.OfflineTts(tts_config)

        with self._lock:
            self._models[cache_key] = tts
            self._models.move_to_end(cache_key)
            while len(self._models) > self.MAX_LOADED_VOICES:
                evicted, _ = self._models.popitem(last=False)
                logger.info(f"Unloaded Piper voice {evicted[0]} ({evicted[1]})")
        return tts

    def _prepare_generation(self, language, phoneme_lang, speed):
        resolved = self._resolve_voice(language)
        if resolved is None:
            logger.error(f"No Piper voice configured for language '{language}'")
            return None
        key, sid = resolved
        tts = self._load_voice(key, self.precision)
        if tts is None:
            return None
        import sherpa_onnx

        num_speakers = getattr(tts, "num_speakers", 1) or 1
        if not 0 <= sid < num_speakers:
            sid = 0
        gen_config = sherpa_onnx.GenerationConfig()
        gen_config.sid = sid
        gen_config.speed = speed
        return tts, gen_config, f"piper={key}, sid={sid}"

    def _is_default_model_installed(self) -> bool:
        resolved = self._resolve_voice(self.voice_config.language)
        return resolved is not None and is_piper_installed(resolved[0], self.precision)

    def release_model(
        self, engine: str, model_id: str, precision: Optional[str] = None
    ) -> None:
        if engine != "piper":
            return
        with self._lock:
            for cache_key in [
                k
                for k in self._models
                if k[0] == model_id and (precision is None or k[1] == precision)
            ]:
                del self._models[cache_key]

    def stop(self) -> None:
        with self._lock:
            self._models.clear()
        logger.info("Sherpa Piper engine stopped")


def tts_engine_class(config: VoiceConfig) -> type[BaseTTSEngine]:
    """Engine class for the configured ``voice.engine``."""
    return (
        PiperEngine if getattr(config, "engine", "kokoro") == "piper" else KokoroEngine
    )


def get_tts_engine(config: VoiceConfig) -> BaseTTSEngine:
    """Factory function to get the configured TTS engine"""
    return tts_engine_class(config)(config)


def get_kokoro_voices(language: str | None = None) -> list[str]:
    """Return Kokoro voice names from the 54 supported speakers.

    If *language* is given, only voices whose prefix matches the language are
    returned (e.g. ``"it"`` → ``if_*``, ``im_*``).
    """
    all_voices = sorted(SPEAKER_TO_ID.keys())
    if language is None:
        return all_voices

    prefixes = _KOKORO_LANG_PREFIXES.get(language, ())
    if not prefixes:
        return []
    return [v for v in all_voices if v.startswith(prefixes)]


def kokoro_languages() -> list[str]:
    """Languages with at least one Kokoro voice."""
    return [lang for lang in _KOKORO_LANG_PREFIXES if get_kokoro_voices(lang)]
