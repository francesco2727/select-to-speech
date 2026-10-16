"""Text-to-Speech engine implementations using Sherpa-ONNX."""

import io
import logging
import queue
import re
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator, Optional, Tuple

import emoji
import numpy as np
import soundfile as sf

from .config import VoiceConfig, get_data_dir
from .voice_manager import (
    ID_TO_SPEAKER,
    KOKORO_MODELS,
    SPEAKER_TO_ID,
    is_kokoro_installed,
)

logger = logging.getLogger(__name__)


def _retry_synthesis(func, max_retries: int = 3, base_delay: float = 0.5):
    """Call func() up to max_retries times with exponential backoff. Re-raises on final failure."""
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), 4.0)
                logger.warning(
                    f"TTS synthesis attempt {attempt + 1}/{max_retries} failed, "
                    f"retrying in {delay:.1f}s: {exc}"
                )
                time.sleep(delay)
    raise last_exc


# Kokoro voice-name prefixes by language
_KOKORO_LANG_PREFIXES: dict[str, list[str]] = {
    "en": ["af_", "am_", "bf_", "bm_"],
    "es": ["ef_", "em_"],
    "fr": ["ff_"],
    "hi": ["hf_", "hm_"],
    "it": ["if_", "im_"],
    "ja": ["jf_", "jm_"],
    "ko": [],
    "pt": ["pf_", "pm_"],
    "zh": ["zf_", "zm_"],
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
    },
}


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

        lang_key = (language or "").split("-")[0].split("_")[0].lower()
        if lang_key not in _SYMBOL_WORDS:
            lang_key = "en"
        words = _SYMBOL_WORDS[lang_key]

        # Convert emojis to text in the requested language
        try:
            demojized = emoji.demojize(text, language=lang_key)
        except (KeyError, ValueError, TypeError):
            demojized = emoji.demojize(text, language="en")
        text = re.sub(r":([^:]+):", lambda m: " " + m.group(1).replace("_", " ") + " ", demojized)

        # Mask dates to prevent their separators from being replaced by math operations
        date_patterns = [
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2}\b",
            r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
            r"\b\d{1,2}[/-]\d{4}\b",
        ]

        date_placeholders = {}
        for pattern in date_patterns:
            def repl(match):
                placeholder = f"__DATE_{len(date_placeholders)}__"
                date_placeholders[placeholder] = match.group(0)
                return placeholder
            text = re.sub(pattern, repl, text)

        # Replace dots in domains/filenames
        dot_pattern = r"(?<=[a-zA-Z_-])\.(?=[a-zA-Z0-9_-])|(?<=[a-zA-Z0-9_-])\.(?=[a-zA-Z_-])"
        text = re.sub(dot_pattern, f" {words['dot']} ", text)

        # Replace currency symbols
        scale_words = (
            r"(?:thousand|thousands|million|millions|billion|billions|trillion|trillions|"
            r"mila|milione|milioni|miliardo|miliardi|mil|millón|millones|billón|billones|"
            r"mille|millier|milliers|milliard|milliards|Tausend|Million|Millionen|Milliarde|Milliarden|"
            r"milhão|milhões|bilhão|bilhões|bilião|biliões)"
        )
        pattern_prefix = rf"([$€£¥₹₽₩¢฿₺₴])\s*(\d+(?:[.,]\d+)*)(?:\s+({scale_words})\b)?"

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

        text = re.sub(pattern_prefix, _replace_prefix_currency, text, flags=re.IGNORECASE)

        for sym, key in _CURRENCY_SYMBOLS.items():
            if sym in text:
                sym_name = words.get(key, "")
                if sym_name:
                    text = text.replace(sym, f" {sym_name} ")

        text = text.replace("%", f" {words['percent']} ")
        text = text.replace("+", f" {words['plus']} ")

        text = re.sub(r"\s+-\s+", f" {words['minus']} ", text)
        text = re.sub(r"(^|\s)-(?=\d)", rf"\1{words['minus']} ", text)

        text = re.sub(r"(?<=\d)\s*\*\s*(?=\d)", f" {words['times']} ", text)
        text = re.sub(r"\s+\*\s+", f" {words['times']} ", text)

        text = re.sub(r"(?<=\d)\s*/\s*(?=\d)", f" {words['divide']} ", text)
        text = re.sub(r"\s+/\s+", f" {words['divide']} ", text)

        text = text.replace("=", f" {words['equals']} ")
        text = text.replace("<", f" {words['less']} ")
        text = text.replace(">", f" {words['greater']} ")

        for placeholder, original_date in date_placeholders.items():
            spaced_date = re.sub(r"[/-]", " ", original_date)
            text = text.replace(placeholder, spaced_date)

        return text

    def _sanitize_text(self, text: str, language: Optional[str] = None, already_preprocessed: bool = False) -> str:
        """Sanitize text for TTS processing."""
        if not already_preprocessed:
            text = self.preprocess_text(text, language)
        text = text.replace('"""', '"')
        text = text.replace("'''", "'")
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^\w\s.,!?;:\'\"/-]", "", text)
        text = text.strip()
        logger.debug(f"Sanitized: '{text[:100]}{'...' if len(text) > 100 else ''}'")
        return text

    def _chunk_text(self, text: str, max_chars: int = 80, language: Optional[str] = None, already_preprocessed: bool = False) -> list[str]:
        """Split text into logical, speakable chunks for streaming TTS."""
        text = re.sub(r"([^.!?])\n+", r"\1. ", text)
        text = re.sub(r"([.!?])\n+", r"\1 ", text)

        text = self._sanitize_text(text, language=language, already_preprocessed=already_preprocessed)

        raw_sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []

        def _split_and_add_weak(sentence: str):
            if len(sentence) <= max_chars:
                if sentence:
                    chunks.append(sentence)
                return

            weak_parts = re.split(r"(?<=[,;:—])\s+", sentence)
            current_chunk = ""

            def _add_piece(piece: str):
                nonlocal current_chunk
                piece = piece.strip()
                if not piece:
                    return
                if len(piece) <= max_chars:
                    if len(current_chunk) + len(piece) + 1 <= max_chars:
                        current_chunk = f"{current_chunk} {piece}".strip()
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = piece
                else:
                    words = piece.split()
                    for w in words:
                        if len(current_chunk) + len(w) + 1 <= max_chars:
                            current_chunk = f"{current_chunk} {w}".strip()
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            while len(w) > max_chars:
                                chunks.append(w[:max_chars])
                                w = w[max_chars:]
                            current_chunk = w

            for part in weak_parts:
                _add_piece(part)

            if current_chunk:
                chunks.append(current_chunk)

        for sentence in raw_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            _split_and_add_weak(sentence)

        return chunks

    def get_model_for_language(self, language: str) -> str:
        """Get voice name for a specific language."""
        model = self.voice_config.language_models.get(language)
        if model:
            return model
        logger.warning(f"No voice model configured for language '{language}', using default: {self.voice_config.model}")
        return self.voice_config.model

    def warmup(self) -> bool:
        """Pre-warm TTS model/buffers in background if supported."""
        return True

    @abstractmethod
    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Optional[Tuple[bytes, int]]:
        pass

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


class KokoroEngine(BaseTTSEngine):
    """Text-to-Speech engine wrapper for Kokoro using Sherpa-ONNX."""

    def __init__(self, voice_config: VoiceConfig):
        super().__init__(voice_config)
        self.model_id = getattr(self.voice_config, "model", "kokoro-multi-lang-v1_0")
        if self.model_id not in KOKORO_MODELS:
            self.model_id = "kokoro-multi-lang-v1_0"

        self.model_dir = self.voices_dir / KOKORO_MODELS[self.model_id]["dir_name"]
        self.tts = None
        self._lock = threading.Lock()

    def _get_effective_threads(self) -> int:
        """Resolve effective number of inference threads (0 = auto-detect)."""
        cfg_threads = getattr(self.voice_config, "num_threads", 0)
        if cfg_threads > 0:
            return cfg_threads
        from .system_check import get_hardware_info
        return get_hardware_info().get("optimal_threads", 4)

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
                self.model_dir = self.voices_dir / KOKORO_MODELS[self.model_id]["dir_name"]
                self.tts = None
            else:
                logger.debug(f"Kokoro voice config updated (session retained for '{self.model_id}').")

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

        try:
            import sherpa_onnx
        except ImportError:
            logger.error(
                "Failed to import sherpa_onnx. Ensure sherpa-onnx and sherpa-onnx-core are installed.",
                exc_info=True,
            )
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
                logger.info(f"Sherpa-ONNX Kokoro TTS initialized successfully ({threads} threads).")
        return True

    def _resolve_speaker_and_lang(
        self,
        language: Optional[str] = None,
        phoneme_lang: Optional[str] = None,
    ) -> Tuple[int, str]:
        """Resolve speaker integer ID and language code for sherpa GenerationConfig."""
        voice_name = self.voice_config.model
        if language:
            voice_name = self.get_model_for_language(language)

        speaker_id = SPEAKER_TO_ID.get(voice_name, 3)  # Default fallback 3 ('af_heart')

        effective_lang = phoneme_lang or language
        lang_code = _KOKORO_LANG_CODES.get(effective_lang, "en-us") if effective_lang else "en-us"

        return speaker_id, lang_code

    def synthesize(
        self,
        text: str,
        language: Optional[str] = None,
        speed: float = 1.0,
        volume: float = 1.0,
        phoneme_lang: Optional[str] = None,
    ) -> Optional[Tuple[bytes, int]]:
        if not text or not text.strip():
            return None

        if not self._init_tts():
            return None

        import sherpa_onnx

        text = self._sanitize_text(text, language=language)
        if not text:
            return None

        sid, lang_code = self._resolve_speaker_and_lang(language, phoneme_lang)
        gen_config = sherpa_onnx.GenerationConfig()
        gen_config.sid = sid
        gen_config.speed = speed
        gen_config.extra = {"lang": lang_code}

        all_samples = []
        sample_rate = 24000

        for chunk in self._chunk_text(text, language=language, already_preprocessed=True):
            if not chunk.strip():
                continue
            with self._lock:
                audio = self.tts.generate(chunk, gen_config)
            if audio and len(audio.samples) > 0:
                all_samples.append(np.array(audio.samples, dtype=np.float32))
                sample_rate = audio.sample_rate

        if not all_samples:
            return None

        samples = np.concatenate(all_samples)
        if volume != 1.0:
            samples = np.clip(samples * volume, -1.0, 1.0)

        with io.BytesIO() as output:
            sf.write(output, samples, sample_rate, format="WAV", subtype="PCM_16")
            audio_bytes = output.getvalue()

        logger.info(f"Synthesized {len(text)} chars to {len(audio_bytes)} bytes at {sample_rate}Hz (sid={sid}, lang={lang_code})")
        return audio_bytes, sample_rate

    def synthesize_stream(
        self,
        text: str,
        language: Optional[str] = None,
        speed: float = 1.0,
        volume: float = 1.0,
        phoneme_lang: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Iterator[Tuple[bytes, int]]:
        if not text or not text.strip():
            return

        if not self._init_tts():
            return

        import sherpa_onnx

        sid, lang_code = self._resolve_speaker_and_lang(language, phoneme_lang)
        gen_config = sherpa_onnx.GenerationConfig()
        gen_config.sid = sid
        gen_config.speed = speed
        gen_config.extra = {"lang": lang_code}

        # Queue to pass audio chunks produced by Sherpa C++ callback to this generator
        audio_chunk_queue: queue.Queue[Optional[Tuple[bytes, int]]] = queue.Queue(maxsize=16)
        synthesis_error: list[Optional[Exception]] = [None]

        def _on_samples(samples: np.ndarray, progress: float) -> int:
            if stop_event is not None and stop_event.is_set():
                return 0  # Stop C++ generation immediately

            if len(samples) > 0:
                s = np.array(samples, dtype=np.float32)
                if volume != 1.0:
                    s = np.clip(s * volume, -1.0, 1.0)
                with io.BytesIO() as out:
                    sf.write(out, s, self.tts.sample_rate, format="WAV", subtype="PCM_16")
                    audio_chunk_queue.put((out.getvalue(), self.tts.sample_rate))

            return 0 if (stop_event is not None and stop_event.is_set()) else 1

        def _worker():
            try:
                # Sanitize text without splitting into artificial small chunks
                clean_text = self._sanitize_text(text, language=language, already_preprocessed=True)
                if not clean_text:
                    return

                with self._lock:
                    if self.tts is None:
                        return
                    self.tts.generate(clean_text, gen_config, callback=_on_samples)
            except Exception as e:
                synthesis_error[0] = e
                logger.error(f"Error in Sherpa-ONNX streaming generation: {e}", exc_info=True)
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

    def stop(self) -> None:
        self.tts = None
        logger.info("Sherpa Kokoro engine stopped")

    def warmup(self) -> bool:
        """Pre-warm Kokoro model in Sherpa-ONNX."""
        try:
            if not is_kokoro_installed(self.model_id):
                logger.debug("Kokoro model not downloaded yet, skipping warmup")
                return False
            if not self._init_tts():
                return False

            import sherpa_onnx
            sid, lang_code = self._resolve_speaker_and_lang(self.voice_config.language)
            gen_config = sherpa_onnx.GenerationConfig()
            gen_config.sid = sid
            gen_config.speed = 1.0
            gen_config.extra = {"lang": lang_code}

            with self._lock:
                if self.tts is not None:
                    logger.info("Pre-warming Sherpa-ONNX Kokoro TTS engine...")
                    self.tts.generate("a", gen_config)
                    logger.info("Sherpa-ONNX Kokoro TTS engine warmup completed.")
                    return True
        except Exception as e:
            logger.warning(f"Sherpa Kokoro warmup failed (non-fatal): {e}")
        return False


def get_tts_engine(config: VoiceConfig) -> BaseTTSEngine:
    """Factory function to get the configured TTS engine"""
    return KokoroEngine(config)


def get_available_models(engine: str = "kokoro") -> list[str]:
    """Scan the data directory for installed models."""
    voices_dir = get_data_dir() / "voices"
    if not voices_dir.exists():
        return []

    return [
        m_id
        for m_id, info in KOKORO_MODELS.items()
        if (voices_dir / info["dir_name"]).is_dir()
    ]


def get_kokoro_voices(language: str | None = None) -> list[str]:
    """Return Kokoro voice names from the 54 supported speakers.

    If *language* is given, only voices whose prefix matches the language are
    returned (e.g. ``"it"`` → ``if_*``, ``im_*``).
    """
    all_voices = sorted(SPEAKER_TO_ID.keys())
    if language is None:
        return all_voices

    prefixes = _KOKORO_LANG_PREFIXES.get(language, [])
    if not prefixes:
        return []
    return [v for v in all_voices if any(v.startswith(p) for p in prefixes)]


def get_voices_for_language(engine: str, language: str) -> list[str]:
    """Return the voice/model names available for *language*."""
    return get_kokoro_voices(language)
