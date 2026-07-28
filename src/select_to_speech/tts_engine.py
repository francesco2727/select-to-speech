"""Text-to-Speech engine implementations"""

import io
import logging
import re
import time
import wave
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Dict, Iterator
import threading

import soundfile as sf
import numpy as np

from .config import get_data_dir, VoiceConfig

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
    "fr": ["ff_", "fm_"],
    "hi": ["hf_", "hm_"],
    "it": ["if_", "im_"],
    "ja": ["jf_", "jm_"],
    "ko": ["kf_"],
    "pt": ["pf_", "pm_"],
    "zh": ["zf_", "zm_"],
}

# Kokoro lang_code used by kokoro.create(lang=...)
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

    def preprocess_text(self, text: str, language: Optional[str] = None) -> str:
        """Preprocess text to replace mathematical symbols, currency symbols, and dots in domains/filenames with words."""
        if not text:
            return text

        # Normalize language code (e.g. "en-us" -> "en", "it_IT" -> "it")
        lang_key = (language or "").split("-")[0].split("_")[0].lower()
        if lang_key not in _SYMBOL_WORDS:
            lang_key = "en"
        words = _SYMBOL_WORDS[lang_key]

        # 1. Replace dots in domains/filenames
        # Matches dots preceded by a letter/hyphen/underscore and followed by alphanumeric/hyphen/underscore,
        # or preceded by alphanumeric/hyphen/underscore and followed by a letter/hyphen/underscore.
        # This excludes decimal numbers like 3.14 or versions like 1.0.
        dot_pattern = r'(?<=[a-zA-Z_-])\.(?=[a-zA-Z0-9_-])|(?<=[a-zA-Z0-9_-])\.(?=[a-zA-Z_-])'
        text = re.sub(dot_pattern, f" {words['dot']} ", text)

        # 2. Replace currency symbols
        # Handle prefix currency symbols before numbers (e.g., $100, € 50,25, $100 million),
        # placing the currency word after the number or after scale words if present.
        scale_words = r'(?:thousand|thousands|million|millions|billion|billions|trillion|trillions|mila|milione|milioni|miliardo|miliardi|mil|millón|millones|billón|billones|mille|millier|milliers|milliard|milliards|Tausend|Million|Millionen|Milliarde|Milliarden|milhão|milhões|bilhão|bilhões|bilião|biliões)'
        pattern_prefix = rf'([$€£¥₹₽₩¢฿₺₴])\s*(\d+(?:[.,]\d+)*)(?:\s+({scale_words})\b)?'

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

        # Replace any remaining currency symbols (e.g., suffix currencies like 100$ or standalone symbols)
        for sym, key in _CURRENCY_SYMBOLS.items():
            if sym in text:
                sym_name = words.get(key, "")
                if sym_name:
                    text = text.replace(sym, f" {sym_name} ")

        # 3. Replace percent symbol (%)
        text = text.replace('%', f" {words['percent']} ")

        # 4. Replace plus symbol (+)
        text = text.replace('+', f" {words['plus']} ")

        # 5. Replace minus symbol (-) when used mathematically
        # Surrounded by spaces: " - "
        text = re.sub(r'\s+-\s+', f" {words['minus']} ", text)
        # Negative sign before a digit: "-5" (must be preceded by whitespace or start of string)
        text = re.sub(r'(^|\s)-(?=\d)', rf'\1{words["minus"]} ', text)

        # 6. Replace times symbol (*) when used mathematically (between digits or surrounded by spaces)
        text = re.sub(r'(?<=\d)\s*\*\s*(?=\d)', f" {words['times']} ", text)
        text = re.sub(r'\s+\*\s+', f" {words['times']} ", text)

        # 7. Replace division symbol (/) when used mathematically (between digits or surrounded by spaces)
        text = re.sub(r'(?<=\d)\s*/\s*(?=\d)', f" {words['divide']} ", text)
        text = re.sub(r'\s+/\s+', f" {words['divide']} ", text)

        # 8. Replace equals symbol (=)
        text = text.replace('=', f" {words['equals']} ")

        # 9. Replace less than (<) and greater than (>)
        text = text.replace('<', f" {words['less']} ")
        text = text.replace('>', f" {words['greater']} ")

        return text

    def _sanitize_text(self, text: str, language: Optional[str] = None) -> str:
        """Sanitize text for TTS processing."""
        text = self.preprocess_text(text, language)
        text = text.replace('"""', '"')
        text = text.replace("'''", "'")
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s.,!?;:\'\"-]', '', text)
        text = text.strip()
        logger.debug(f"Sanitized: '{text[:100]}{'...' if len(text) > 100 else ''}'")
        return text

    def _chunk_text(self, text: str, max_chars: int = 180, language: Optional[str] = None) -> list[str]:
        """Split text into logical, speakable chunks for streaming TTS."""
        # Normalize newlines to sentence boundaries before sanitization so that
        # paragraph/line breaks produce natural TTS pauses.
        # Lines not ending with sentence punctuation get a period appended.
        text = re.sub(r'([^.!?])\n+', r'\1. ', text)
        text = re.sub(r'([.!?])\n+', r'\1 ', text)

        text = self._sanitize_text(text, language=language)

        # 1. Split by strong sentence boundaries (. ! ?) keeping the punctuation attached
        raw_sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
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
                # 3. Fallback: split by words if a segment has no punctuation and exceeds max_chars
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

        for sentence in raw_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # 2. If a sentence is still too long, break it by weak boundaries (, ; : —)
            if len(sentence) > max_chars:
                weak_parts = re.split(r'(?<=[,;:—])\s+', sentence)
                for part in weak_parts:
                    _add_piece(part)
            else:
                _add_piece(sentence)

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def get_model_for_language(self, language: str) -> str:
        """Get model name for a specific language."""
        model = self.voice_config.language_models.get(language)
        if model:
            return model
        logger.warning(f"No voice model configured for language '{language}', using default: {self.voice_config.model}")
        return self.voice_config.model

    @abstractmethod
    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Optional[Tuple[bytes, int]]:
        """Synthesize text to speech.

        Args:
            phoneme_lang: If set, overrides the phonemization language without
                changing the voice.
        """
        pass

    @abstractmethod
    def synthesize_stream(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Iterator[Tuple[bytes, int]]:
        """Synthesize text to speech as a stream.

        Args:
            phoneme_lang: If set, overrides the phonemization language without
                changing the voice.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the TTS engine and cleanup"""
        pass



class KokoroEngine(BaseTTSEngine):
    """Text-to-Speech engine wrapper for Kokoro ONNX"""

    def __init__(self, voice_config: VoiceConfig):
        super().__init__(voice_config)
        self.model_path = self.voices_dir / "kokoro-v1.0.onnx"
        self.voices_bin_path = self.voices_dir / "voices-v1.0.bin"
        
        self.kokoro = None
        self._lock = threading.Lock()
        
    def ensure_model_downloaded(self) -> bool:
        """Download kokoro model and voices.bin if they don't exist."""
        from . import voice_manager
        if voice_manager.is_kokoro_installed():
            return True
        logger.info("Kokoro models missing — downloading (~350 MB)…")
        return voice_manager.download_kokoro()

    @staticmethod
    def _ensure_kokoro_config_json() -> None:
        """Ensure kokoro_onnx/config.json exists before importing the module.

        In Nuitka --onefile bundles, the extraction of data files to the temp
        directory can intermittently skip config.json. Since kokoro_onnx.config
        reads it at import time (module-level ``DEFAULT_VOCAB = get_vocab()``),
        a missing file causes a FileNotFoundError that prevents Kokoro from
        initializing.

        This method locates the kokoro_onnx package directory and, if
        config.json is absent, writes a minimal copy containing only the
        ``vocab`` mapping that ``get_vocab()`` actually needs.
        """
        import importlib.util
        import json

        spec = importlib.util.find_spec("kokoro_onnx")
        if spec is None or spec.origin is None:
            return  # package not installed — let the normal ImportError path handle it

        config_path = Path(spec.origin).parent / "config.json"
        if config_path.exists():
            return  # all good

        logger.warning(
            "kokoro_onnx/config.json missing from bundle — "
            "writing embedded fallback to %s",
            config_path,
        )

        # Minimal config.json — only the ``vocab`` key is used at import time.
        # Sourced from kokoro-onnx 0.5.2.
        fallback_vocab = {
            ";": 1, ":": 2, ",": 3, ".": 4, "!": 5, "?": 6, "\u2014": 9,
            "\u2026": 10, "\"": 11, "(": 12, ")": 13, "\u201c": 14, "\u201d": 15,
            " ": 16, "\u0303": 17, "\u02a3": 18, "\u02a5": 19, "\u02a6": 20,
            "\u02a8": 21, "\u1d5d": 22, "\uab67": 23, "A": 24, "I": 25,
            "O": 31, "Q": 33, "S": 35, "T": 36, "W": 39, "Y": 41,
            "\u1d4a": 42, "a": 43, "b": 44, "c": 45, "d": 46, "e": 47,
            "f": 48, "h": 50, "i": 51, "j": 52, "k": 53, "l": 54,
            "m": 55, "n": 56, "o": 57, "p": 58, "q": 59, "r": 60,
            "s": 61, "t": 62, "u": 63, "v": 64, "w": 65, "x": 66,
            "y": 67, "z": 68, "\u0251": 69, "\u0250": 70, "\u0252": 71,
            "\u00e6": 72, "\u03b2": 75, "\u0254": 76, "\u0255": 77,
            "\u00e7": 78, "\u0256": 80, "\u00f0": 81, "\u02a4": 82,
            "\u0259": 83, "\u025a": 85, "\u025b": 86, "\u025c": 87,
            "\u025f": 90, "\u0261": 92, "\u0265": 99, "\u0268": 101,
            "\u026a": 102, "\u029d": 103, "\u026f": 110, "\u0270": 111,
            "\u014b": 112, "\u0273": 113, "\u0272": 114, "\u0274": 115,
            "\u00f8": 116, "\u0278": 118, "\u03b8": 119, "\u0153": 120,
            "\u0279": 123, "\u027e": 125, "\u027b": 126, "\u0281": 128,
            "\u027d": 129, "\u0282": 130, "\u0283": 131, "\u0288": 132,
            "\u02a7": 133, "\u028a": 135, "\u028b": 136, "\u028c": 138,
            "\u0263": 139, "\u0264": 140, "\u03c7": 142, "\u028e": 143,
            "\u0292": 147, "\u0294": 148, "\u02c8": 156, "\u02cc": 157,
            "\u02d0": 158, "\u02b0": 162, "\u02b2": 164, "\u2193": 169,
            "\u2192": 171, "\u2197": 172, "\u2198": 173, "\u1d7b": 177,
        }
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps({"vocab": fallback_vocab}, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Successfully wrote fallback config.json")
        except OSError as exc:
            logger.error("Could not write fallback config.json: %s", exc)

    def _init_kokoro(self) -> bool:
        if self.kokoro is not None:
            return True
            
        if not self.ensure_model_downloaded():
            return False
            
        try:
            # Workaround: In Nuitka --onefile bundles, kokoro_onnx/config.json may
            # intermittently not be extracted to the temp directory. The file is
            # required at import time (config.py → get_vocab() → opens config.json).
            # We detect this and restore the file before importing.
            self._ensure_kokoro_config_json()
            from kokoro_onnx import Kokoro
            with self._lock:
                if self.kokoro is None:
                    logger.info("Initializing Kokoro ONNX model...")
                    self.kokoro = Kokoro(str(self.model_path), str(self.voices_bin_path))
                    
                    # Intercept tokenizer.phonemize to strip espeak-ng language tags.
                    # espeak-ng outputs language switch tags (e.g., '(en)', '(it)') when it
                    # automatically detects foreign words during phonemization.
                    # Because these tags' characters are in Kokoro's vocabulary, Kokoro
                    # otherwise literally tokenizes and pronounces them (e.g., saying 'it'
                    # at the end of 'team' when processing in Italian).
                    original_phonemize = self.kokoro.tokenizer.phonemize
                    
                    def patched_phonemize(text: str, lang: str = "en-us", norm: bool = True) -> str:
                        phonemes = original_phonemize(text, lang=lang, norm=norm)
                        # Remove language switch tags like (en), (it), (fr), (es), etc.
                        return re.sub(r'\([a-z]{2}\)', '', phonemes)
                        
                    self.kokoro.tokenizer.phonemize = patched_phonemize

                    # Intercept tokenizer.tokenize to ensure tokens never exceed 509.
                    # Kokoro ONNX voice style matrices have shape (510, 1, 256). When
                    # kokoro_onnx truncates tokens to MAX_PHONEME_LENGTH (510), accessing
                    # voice[len(tokens)] causes index 510 out of bounds. Truncating to 509
                    # guarantees voice[len(tokens)] is always in bounds [0..509].
                    original_tokenize = self.kokoro.tokenizer.tokenize

                    def patched_tokenize(phonemes: str) -> list[int]:
                        tokens = original_tokenize(phonemes)
                        if len(tokens) > 509:
                            logger.warning(
                                f"Phoneme sequence too long ({len(tokens)} tokens), "
                                "truncating to 509 to avoid Kokoro ONNX IndexError."
                            )
                            tokens = tokens[:509]
                        return tokens

                    self.kokoro.tokenizer.tokenize = patched_tokenize
            return True
        except ImportError as e:
            logger.error(
                "Failed to import kokoro-onnx (or one of its dependencies: "
                "misaki, phonemizer, dlinfo, onnxruntime). "
                "KokoroEngine cannot be used.",
                exc_info=True,
            )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Kokoro: {e}", exc_info=True)
            return False

    def synthesize(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Optional[Tuple[bytes, int]]:
        if not text:
            return None

        target_voice = self.voice_config.model
        if language:
            target_voice = self.get_model_for_language(language)

        if not self._init_kokoro():
            return None

        try:
            if not text.strip():
                logger.warning("Empty text provided for synthesis")
                return None

            text = self._sanitize_text(text, language=language)
            if not text:
                return None

            logger.debug(f"Synthesizing text with voice {target_voice}: '{text[:100]}{'...' if len(text) > 100 else ''}'")

            # phoneme_lang overrides the phonemization language while keeping the same voice
            effective_lang = phoneme_lang or language
            lang_code = _KOKORO_LANG_CODES.get(effective_lang, "en-us") if effective_lang else "en-us"

            all_samples = []
            sample_rate = 22050
            for chunk in self._chunk_text(text, language=language):
                if not chunk.strip():
                    continue
                with self._lock:
                    # Kokoro returns samples in [-1, 1] range, and sample_rate
                    samples, sample_rate = self.kokoro.create(
                        chunk,
                        voice=target_voice,
                        speed=speed,
                        lang=lang_code
                    )
                all_samples.append(samples)

            if not all_samples:
                return None
            samples = np.concatenate(all_samples)
            
            # Apply volume scaling
            if volume != 1.0:
                samples = samples * volume
                # Clip to prevent overflow
                samples = np.clip(samples, -1.0, 1.0)
                
            # Convert to WAV bytes using soundfile
            with io.BytesIO() as output:
                sf.write(output, samples, sample_rate, format='WAV', subtype='PCM_16')
                audio_bytes = output.getvalue()

            logger.info(f"Synthesized {len(text)} chars to {len(audio_bytes)} bytes at {sample_rate}Hz using {target_voice}")
            
            return audio_bytes, sample_rate

        except Exception as e:
            logger.error(f"Kokoro Engine failed to synthesize text. Error: {e}", exc_info=True)
            return None

    def synthesize_stream(self, text: str, language: Optional[str] = None, speed: float = 1.0, volume: float = 1.0, phoneme_lang: Optional[str] = None) -> Iterator[Tuple[bytes, int]]:
        if not text:
            return

        target_voice = self.voice_config.model
        if language:
            target_voice = self.get_model_for_language(language)

        if not self._init_kokoro():
            return

        # phoneme_lang overrides the phonemization language while keeping the same voice
        effective_lang = phoneme_lang or language
        lang_code = _KOKORO_LANG_CODES.get(effective_lang, "en-us") if effective_lang else "en-us"

        for chunk in self._chunk_text(text, language=language):
            if not chunk.strip():
                continue
            logger.debug(f"Synthesizing stream chunk with voice {target_voice}: '{chunk[:100]}{'...' if len(chunk) > 100 else ''}'")
            try:
                def _synth(c=chunk):
                    with self._lock:
                        # Kokoro returns samples in [-1, 1] range, and sample_rate
                        samples, sample_rate = self.kokoro.create(
                            c,
                            voice=target_voice,
                            speed=speed,
                            lang=lang_code
                        )
                    # Apply volume scaling
                    if volume != 1.0:
                        samples = np.clip(samples * volume, -1.0, 1.0)
                    # Convert to WAV bytes using soundfile
                    with io.BytesIO() as output:
                        sf.write(output, samples, sample_rate, format='WAV', subtype='PCM_16')
                        return output.getvalue(), sample_rate

                audio_bytes, sample_rate = _retry_synthesis(_synth)
                logger.debug(f"Synthesized streaming chunk: {len(chunk)} chars")
                yield audio_bytes, sample_rate

            except Exception as e:
                logger.error(f"Failed synthesising chunk after retries. Error: {e}", exc_info=True)

    def stop(self) -> None:
        self.kokoro = None
        logger.info("Kokoro engine stopped")


def get_tts_engine(config: VoiceConfig) -> BaseTTSEngine:
    """Factory function to get the configured TTS engine"""
    return KokoroEngine(config)


def get_available_models(engine: str = "kokoro") -> list[str]:
    """Scan the data directory for installed models."""
    voices_dir = get_data_dir() / "voices"
    if not voices_dir.exists():
        return []

    return sorted(
        p.stem for p in voices_dir.glob("kokoro*.onnx")
    )


def get_kokoro_voices(language: str | None = None) -> list[str]:
    """Return Kokoro voice names from the installed voices-v1.0.bin file.

    If *language* is given, only voices whose prefix matches the language are
    returned (e.g. ``"it"`` → ``if_*``, ``im_*``).
    """
    voices_bin = get_data_dir() / "voices" / "voices-v1.0.bin"
    if not voices_bin.exists():
        return []
    try:
        data = np.load(str(voices_bin), allow_pickle=False)
        all_voices: list[str] = sorted(data.files)
    except Exception:
        logger.warning("Failed to read Kokoro voices from %s", voices_bin)
        return []

    if language is None:
        return all_voices

    prefixes = _KOKORO_LANG_PREFIXES.get(language, [])
    if not prefixes:
        return []  # unsupported language → empty list
    return [v for v in all_voices if any(v.startswith(p) for p in prefixes)]


def get_voices_for_language(engine: str, language: str) -> list[str]:
    """Return the voice/model names available for *language*."""
    return get_kokoro_voices(language)


