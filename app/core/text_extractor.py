from __future__ import annotations

import logging
from collections.abc import Iterator

from app.core.types import WordHit
from app.utils.text_utils import choose_sentence_from_text, choose_word_from_text, normalize_text

try:
    import uiautomation as auto
except ImportError:  # pragma: no cover - dependency check at runtime
    auto = None


class TextExtractor:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def extract_word_at(self, x: int, y: int) -> WordHit | None:
        candidates = self._collect_candidates_at(x, y)
        candidates.sort(key=len)
        for candidate in candidates:
            word, context = choose_word_from_text(candidate)
            if word:
                return WordHit(
                    word=word,
                    context=context,
                    raw_text=candidate,
                    source="uia",
                    confidence=1.0,
                )

        return None

    def extract_sentence_at(self, x: int, y: int, focus_word: str | None = None) -> WordHit | None:
        candidates = self._collect_candidates_at(x, y)
        candidates.sort(key=len)
        for candidate in candidates:
            sentence = choose_sentence_from_text(candidate, focus_word=focus_word)
            if sentence:
                return WordHit(
                    word=sentence,
                    context=candidate,
                    raw_text=candidate,
                    source="uia-sentence",
                    confidence=1.0,
                )

        return None

    def _collect_candidates_at(self, x: int, y: int) -> list[str]:
        if auto is None:
            return []

        try:
            control = auto.ControlFromPoint(x, y)
        except Exception:
            self._logger.exception("Failed to inspect UI Automation control at %s,%s", x, y)
            return []

        if control is None:
            return []

        candidates = []
        for current in self._iter_control_chain(control, max_depth=2):
            for candidate in self._iter_candidate_texts(current):
                normalized = normalize_text(candidate)
                if normalized and normalized not in candidates:
                    candidates.append(normalized)
        return candidates

    def _iter_control_chain(self, control: object, max_depth: int) -> Iterator[object]:
        current = control
        depth = 0
        while current is not None and depth <= max_depth:
            yield current
            parent_getter = getattr(current, "GetParentControl", None)
            if not callable(parent_getter):
                return
            try:
                current = parent_getter()
            except Exception:
                return
            depth += 1

    def _iter_candidate_texts(self, control: object) -> Iterator[str]:
        for attr_name in ("Name", "HelpText"):
            value = getattr(control, attr_name, None)
            if isinstance(value, str) and value.strip():
                yield value

        get_window_text = getattr(control, "GetWindowText", None)
        if callable(get_window_text):
            try:
                value = get_window_text()
            except Exception:
                value = None
            if isinstance(value, str) and value.strip():
                yield value

        yield from self._extract_pattern_text(control, "GetValuePattern", ("Value",))
        yield from self._extract_pattern_text(
            control,
            "GetLegacyIAccessiblePattern",
            ("Value", "Name", "Description"),
        )
        yield from self._extract_document_text(control)

    def _extract_pattern_text(
        self,
        control: object,
        getter_name: str,
        attributes: tuple[str, ...],
    ) -> Iterator[str]:
        getter = getattr(control, getter_name, None)
        if not callable(getter):
            return
        try:
            pattern = getter()
        except Exception:
            return
        if pattern is None:
            return

        for attribute in attributes:
            value = getattr(pattern, attribute, None)
            if isinstance(value, str) and value.strip():
                yield value

    def _extract_document_text(self, control: object) -> Iterator[str]:
        getter = getattr(control, "GetTextPattern", None)
        if not callable(getter):
            return
        try:
            pattern = getter()
        except Exception:
            return
        if pattern is None:
            return

        document_range = getattr(pattern, "DocumentRange", None)
        get_text = getattr(document_range, "GetText", None)
        if callable(get_text):
            try:
                text = get_text(64)
            except Exception:
                return
            if isinstance(text, str) and text.strip():
                yield text
