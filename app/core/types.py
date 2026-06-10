from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class WordHit:
    word: str
    source: str
    context: str | None = None
    raw_text: str | None = None
    confidence: float = 1.0


@dataclass(slots=True, frozen=True)
class OcrDebugBox:
    text: str
    confidence: float
    polygon: tuple[tuple[float, float], ...]
    selected: bool = False
    raw_text: str | None = None


@dataclass(slots=True, frozen=True)
class OcrDebugInfo:
    image: Any
    region_left: int
    region_top: int
    region_width: int
    region_height: int
    cursor_x: int
    cursor_y: int
    selected_word: str | None
    selected_polygon: tuple[tuple[float, float], ...] | None
    boxes: tuple[OcrDebugBox, ...]
    elapsed_ms: float


@dataclass(slots=True, frozen=True)
class OcrTextLine:
    text: str
    confidence: float
    polygon: tuple[tuple[float, float], ...]


@dataclass(slots=True, frozen=True)
class OcrResult:
    word_hit: WordHit | None
    debug_info: OcrDebugInfo
    lines: tuple[OcrTextLine, ...] = ()


@dataclass(slots=True, frozen=True)
class TranslationResult:
    word: str
    translation: str
    phonetic: str
    explanation: str
    source: str = "openai"
    context: str | None = None
    examples: tuple[str, ...] = ()
    is_sentence: bool = False
