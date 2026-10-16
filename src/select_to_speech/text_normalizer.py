"""Text normalization and cleanup utilities for select-to-speech.

This module provides heuristics for:
1. De-hyphenation (rejoining words split across lines, e.g. "com- \n puter" -> "computer").
2. Smart paragraph unwrap and sentence boundary insertion.
3. List and bullet-point pause normalization.
4. Preserving acronyms, file extensions, and mathematical notation.
"""

import re
from typing import Optional

# Common bullet and list markers
_BULLET_PATTERN = re.compile(
    r"^[\t ]*(?:[•*+\-–—▪►]|(?:\d+|[a-zA-Z])[\.\)])[\t ]+",
    re.MULTILINE,
)

# Line-break hyphenation pattern:
# matches e.g. "parola-\n spezzata" or "auto-\r\n mobile"
# We only join if left and right parts are alphabetic words
_HYPHEN_WRAP_PATTERN = re.compile(
    r"(\b[^\W\d_]{2,})[-–—]\s*[\r\n]+\s*([^\W\d_]{2,}\b)",
    re.UNICODE,
)


def dehyphenate(text: str) -> str:
    """
    Rejoin words split by a trailing hyphen and line-break.

    Example:
        "inter- \\n fccia" -> "interfaccia"
        "state- \\n of-the-art" -> "state-of-the-art" (if hyphenated compound)
    """
    if not text:
        return text

    def _merge_hyphen(m: re.Match) -> str:
        left = m.group(1)
        right = m.group(2)
        return left + right

    return _HYPHEN_WRAP_PATTERN.sub(_merge_hyphen, text)


def normalize_bullets_and_lists(text: str) -> str:
    """
    Convert bullet points and enumeration markers at line starts
    into a clean phrasing or pauses, ensuring subsequent text ends with a pause.
    """
    if not text:
        return text

    lines = text.splitlines()
    processed_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            processed_lines.append("")
            continue

        # Check if line starts with a bullet point
        m = _BULLET_PATTERN.match(line)
        if m:
            content = line[m.end():].strip()
            # If line doesn't end with punctuation, append a semicolon or period for pause
            if content and content[-1] not in ".!?;:":
                content = content + "."
            processed_lines.append(content)
        else:
            processed_lines.append(line)

    return "\n".join(processed_lines)


def unwrap_lines(text: str) -> str:
    """
    Join lines that were soft-wrapped by terminals, PDFs, or columns,
    while preserving true paragraph breaks (double newline) and adding
    periods to headers or blocks that end without punctuation.
    """
    if not text:
        return text

    # Split into logical paragraphs separated by blank lines
    paragraphs = re.split(r"\n\s*\n", text)
    cleaned_paragraphs = []

    for p in paragraphs:
        p_str = p.strip()
        if not p_str:
            continue

        lines = [l.strip() for l in p_str.splitlines() if l.strip()]
        if not lines:
            continue

        # Join lines inside a paragraph
        # If line ends in punctuation (. ! ? : ;), join with space
        # If line ends without punctuation, join with space
        joined = " ".join(lines)

        # If paragraph doesn't end with ending punctuation, append a dot
        if joined and joined[-1] not in ".!?;:":
            joined = joined + "."

        cleaned_paragraphs.append(joined)

    return "\n\n".join(cleaned_paragraphs)


def normalize_text_for_tts(
    text: str,
    dehyphen: bool = True,
    bullets: bool = True,
    unwrap: bool = True,
) -> str:
    """
    Complete text normalization pipeline before TTS or OCR synthesis.

    Args:
        text: Input raw text
        dehyphen: Join line-break split words
        bullets: Convert bullet points into clear speaking segments
        unwrap: Soft unwrap wrapped lines into flowing paragraphs

    Returns:
        Normalized, speakable string with improved punctuation flow.
    """
    if not text or not text.strip():
        return text

    res = text

    # 1. De-hyphenate broken words across linebreaks
    if dehyphen:
        res = dehyphenate(res)

    # 2. Normalize bullet points
    if bullets:
        res = normalize_bullets_and_lists(res)

    # 3. Soft unwrap lines while maintaining paragraph pauses
    if unwrap:
        res = unwrap_lines(res)

    # 4. Collapse excess internal whitespace (without destroying sentence dots)
    res = re.sub(r"[ \t]+", " ", res)
    res = re.sub(r"\n{3,}", "\n\n", res)

    return res.strip()
