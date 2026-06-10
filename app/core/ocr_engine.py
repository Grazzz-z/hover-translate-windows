from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from collections.abc import Iterator
from inspect import signature
from math import hypot
from typing import Any

from app.core.types import OcrDebugBox, OcrDebugInfo, OcrResult, OcrTextLine, WordHit
from app.utils.screen_capture import CaptureFrame
from app.utils.text_utils import clean_word, english_token_spans, is_probable_english_word

# Paddle 3.x can route some CPU graphs through oneDNN by default, which is
# fragile with PaddleOCR 2.x exported inference models on Windows.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_mkldnn_bfloat16", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

try:
    from paddleocr import PaddleOCR
except ImportError:  # pragma: no cover - dependency check at runtime
    PaddleOCR = None


class OCREngine:
    def __init__(self, confidence_threshold: float = 0.45) -> None:
        self._logger = logging.getLogger(__name__)
        self._confidence_threshold = confidence_threshold
        self._engine: PaddleOCR | None = None
        self._lock = threading.Lock()
        self._uses_modern_api = False

    def warm_up(self) -> None:
        self._get_engine()

    def extract_word_from_capture(
        self,
        capture: CaptureFrame,
        cursor_position: tuple[int, int],
    ) -> WordHit | None:
        return self.analyze_capture(capture, cursor_position).word_hit

    def analyze_capture(
        self,
        capture: CaptureFrame,
        cursor_position: tuple[int, int],
    ) -> OcrResult:
        started_at = time.perf_counter()
        engine = self._get_engine()
        relative_cursor = (
            cursor_position[0] - capture.region.left,
            cursor_position[1] - capture.region.top,
        )

        result = engine.predict(capture.image) if self._uses_modern_api else engine.ocr(capture.image, cls=False)
        candidates: list[_TokenCandidate] = []
        debug_boxes: list[OcrDebugBox] = []
        text_lines: list[OcrTextLine] = []

        for box, text, confidence in self._iter_ocr_entries(result):
            if confidence < self._confidence_threshold:
                continue

            text_lines.append(
                OcrTextLine(
                    text=text,
                    confidence=confidence,
                    polygon=self._to_tuple_polygon(box),
                )
            )

            token_candidates = list(self._iter_token_candidates(text, box, relative_cursor, confidence))
            if token_candidates:
                candidates.extend(token_candidates)
                continue

            debug_boxes.append(
                OcrDebugBox(
                    text=text,
                    confidence=confidence,
                    polygon=self._to_tuple_polygon(box),
                    raw_text=text,
                )
            )

        selected = min(candidates, key=lambda item: item.score, default=None)
        word_hit = selected.word_hit if selected else None
        selected_polygon = self._to_tuple_polygon(selected.polygon) if selected else None

        debug_boxes.extend(
            OcrDebugBox(
                text=candidate.word_hit.word,
                confidence=candidate.word_hit.confidence,
                polygon=self._to_tuple_polygon(candidate.polygon),
                selected=candidate is selected,
                raw_text=candidate.word_hit.raw_text,
            )
            for candidate in candidates
        )

        if word_hit:
            self._logger.debug("OCR extraction succeeded: %s", word_hit)

        debug_info = OcrDebugInfo(
            image=capture.image.copy(),
            region_left=capture.region.left,
            region_top=capture.region.top,
            region_width=capture.region.width,
            region_height=capture.region.height,
            cursor_x=int(relative_cursor[0]),
            cursor_y=int(relative_cursor[1]),
            selected_word=word_hit.word if word_hit else None,
            selected_polygon=selected_polygon,
            boxes=tuple(debug_boxes),
            elapsed_ms=(time.perf_counter() - started_at) * 1000.0,
        )
        return OcrResult(word_hit=word_hit, debug_info=debug_info, lines=tuple(text_lines))

    def _get_engine(self) -> PaddleOCR:
        if PaddleOCR is None:
            raise RuntimeError("paddleocr is not installed.")

        with self._lock:
            if self._engine is None:
                self._logger.info("Initializing PaddleOCR in CPU mode")
                params = signature(PaddleOCR).parameters
                self._uses_modern_api = "use_doc_orientation_classify" in params
                self._engine = (
                    self._create_modern_engine()
                    if self._uses_modern_api
                    else self._create_legacy_engine()
                )
            return self._engine

    def _create_modern_engine(self) -> PaddleOCR:
        return PaddleOCR(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="en_PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_det_limit_side_len=320,
            text_recognition_batch_size=1,
            enable_mkldnn=False,
            device="cpu",
        )

    def _create_legacy_engine(self) -> PaddleOCR:
        return PaddleOCR(
            use_angle_cls=False,
            lang="en",
            use_gpu=False,
            enable_mkldnn=False,
            cpu_threads=2,
            show_log=False,
            det_limit_side_len=320,
            rec_batch_num=1,
        )

    def _iter_ocr_entries(self, result: Any) -> Iterator[tuple[list[list[float]], str, float]]:
        if not result:
            return

        if isinstance(result, list) and result and isinstance(result[0], dict):
            for page in result:
                texts = page.get("rec_texts") or []
                scores = page.get("rec_scores") or []
                polys = page.get("rec_polys")
                boxes = page.get("rec_boxes")

                for index, text in enumerate(texts):
                    box = self._get_indexed_box(polys, index) or self._box_to_poly(
                        self._get_indexed_box(boxes, index)
                    )
                    if not box:
                        continue
                    try:
                        confidence = float(scores[index])
                    except (IndexError, TypeError, ValueError):
                        confidence = 1.0
                    yield box, str(text), confidence
            return

        entries = result[0] if isinstance(result, list) and result else []
        for entry in entries:
            try:
                box, payload = entry
                text = str(payload[0])
                confidence = float(payload[1])
            except (IndexError, TypeError, ValueError):
                continue

            normalized_box = self._normalize_box(box)
            if normalized_box:
                yield normalized_box, text, confidence

    def _get_indexed_box(self, boxes: Any, index: int) -> list[list[float]] | None:
        if boxes is None:
            return None
        try:
            if len(boxes) <= index:
                return None
            return self._normalize_box(boxes[index])
        except TypeError:
            return None

    def _normalize_box(self, box: Any) -> list[list[float]] | None:
        if box is None:
            return None
        if hasattr(box, "tolist"):
            box = box.tolist()
        if not isinstance(box, list) or not box:
            return None

        if len(box) == 4 and all(isinstance(point, (int, float)) for point in box):
            left, top, right, bottom = [float(value) for value in box]
            return [[left, top], [right, top], [right, bottom], [left, bottom]]

        points = []
        for point in box:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                return None
            points.append([float(point[0]), float(point[1])])
        return points if len(points) >= 4 else None

    def _box_to_poly(self, box: list[list[float]] | None) -> list[list[float]] | None:
        return box

    def _iter_token_candidates(
        self,
        text: str,
        box: list[list[float]],
        cursor: tuple[int, int],
        confidence: float,
    ) -> Iterator[_TokenCandidate]:
        spans = english_token_spans(text)
        if not spans:
            return

        left = min(point[0] for point in box)
        right = max(point[0] for point in box)
        top = min(point[1] for point in box)
        bottom = max(point[1] for point in box)
        width = max(right - left, 1.0)
        height = max(bottom - top, 1.0)
        total_length = max(len(text), 1)

        for token, start, end in spans:
            word = clean_word(token).lower()
            if not is_probable_english_word(word):
                continue

            start_ratio = start / total_length
            end_ratio = end / total_length
            token_left = left + width * start_ratio
            token_right = left + width * end_ratio
            token_width = max(token_right - token_left, 1.0)
            token_polygon = [
                [token_left, top],
                [token_right, top],
                [token_right, bottom],
                [token_left, bottom],
            ]

            token_center_x = token_left + (token_width / 2.0)
            token_center_y = top + (height / 2.0)
            edge_distance, is_inside = self._distance_to_token_box(cursor, token_polygon)
            center_distance = hypot(token_center_x - cursor[0], token_center_y - cursor[1])
            threshold = max(8.0, min(20.0, height * 1.05))
            if not is_inside and edge_distance > threshold:
                continue

            score = edge_distance + (center_distance * 0.12) + (0.0 if is_inside else 8.0) - (confidence * 4.0)
            yield _TokenCandidate(
                score=score,
                polygon=token_polygon,
                word_hit=WordHit(
                    word=word,
                    context=text,
                    raw_text=text,
                    source="ocr",
                    confidence=confidence,
                ),
            )

    def _distance_to_token_box(
        self,
        cursor: tuple[int, int],
        polygon: list[list[float]],
    ) -> tuple[float, bool]:
        left = min(point[0] for point in polygon)
        right = max(point[0] for point in polygon)
        top = min(point[1] for point in polygon)
        bottom = max(point[1] for point in polygon)
        padding = min(10.0, max(4.0, (bottom - top) * 0.35))

        is_inside = (
            (left - padding) <= cursor[0] <= (right + padding)
            and (top - padding) <= cursor[1] <= (bottom + padding)
        )
        dx = max(left - cursor[0], 0.0, cursor[0] - right)
        dy = max(top - cursor[1], 0.0, cursor[1] - bottom)
        return hypot(dx, dy), is_inside

    def _to_tuple_polygon(self, polygon: list[list[float]]) -> tuple[tuple[float, float], ...]:
        return tuple((float(point[0]), float(point[1])) for point in polygon)


@dataclass(slots=True, frozen=True)
class _TokenCandidate:
    score: float
    polygon: list[list[float]]
    word_hit: WordHit
