from __future__ import annotations

import math
import re

WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
    )
    return re.sub(r"\s+", " ", text).strip()


def clean_word(word: str | None) -> str:
    if not word:
        return ""
    return word.strip(" \t\r\n.,;:!?()[]{}<>\"'")


def english_token_spans(text: str | None) -> list[tuple[str, int, int]]:
    normalized = normalize_text(text)
    return [(match.group(0), match.start(), match.end()) for match in WORD_RE.finditer(normalized)]


def is_probable_english_word(word: str | None) -> bool:
    cleaned = clean_word(word)
    return bool(cleaned) and len(cleaned) <= 32 and WORD_RE.fullmatch(cleaned) is not None


def choose_word_from_text(
    text: str | None,
    *,
    max_tokens: int = 4,
    max_chars: int = 64,
) -> tuple[str | None, str | None]:
    normalized = normalize_text(text)
    if not normalized:
        return None, None

    tokens = english_token_spans(normalized)
    if not tokens:
        return None, normalized
    if len(tokens) > max_tokens or len(normalized) > max_chars:
        return None, normalized

    word = clean_word(tokens[0][0]).lower()
    if not is_probable_english_word(word):
        return None, normalized
    return word, normalized


def choose_sentence_from_text(
    text: str | None,
    *,
    focus_word: str | None = None,
    max_chars: int = 260,
) -> str | None:
    normalized = normalize_text(text)
    if not normalized:
        return None

    pieces = [
        piece.strip(" \t\r\n|•·")
        for piece in re.split(r"(?<=[.!?])\s+|[|•·]+", normalized)
        if piece.strip(" \t\r\n|•·")
    ]
    if not pieces:
        pieces = [normalized]

    focus = clean_word(focus_word).lower()
    candidates = [
        piece
        for piece in pieces
        if len(english_token_spans(piece)) >= 2 and len(piece) <= max_chars
    ]
    if not candidates and len(english_token_spans(normalized)) >= 2:
        candidates = [normalized[:max_chars].strip()]

    if not candidates:
        return None

    if focus:
        focused = [
            piece
            for piece in candidates
            if any(clean_word(token).lower() == focus for token, _, _ in english_token_spans(piece))
        ]
        if focused:
            return min(focused, key=len)

    return max(candidates, key=lambda piece: len(english_token_spans(piece)))


def distance(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
