from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

from app.core.cache import LRUCache
from app.core.mouse_tracker import MouseTracker
from app.core.ocr_engine import OCREngine
from app.core.text_extractor import TextExtractor
from app.core.translator import Translator
from app.core.types import OcrTextLine, TranslationResult, WordHit
from app.ui.debug_window import OcrDebugWindow
from app.ui.floating_window import FloatingWindow
from app.ui.settings_window import SettingsWindow
from app.ui.tray_icon import AppTrayIcon
from app.utils.screen_capture import ScreenCapture
from app.utils.text_utils import choose_sentence_from_text, english_token_spans, normalize_text
from config import Settings, save_settings, with_updated_settings


class HoverTranslateController(QObject):
    lookup_started = pyqtSignal(int, str, tuple)
    word_resolved = pyqtSignal(int, object, tuple)
    sentence_resolved = pyqtSignal(int, object, tuple)
    translation_ready = pyqtSignal(int, object, tuple)
    background_error = pyqtSignal(int, str, tuple)
    ocr_debug_ready = pyqtSignal(object)

    def __init__(self, settings: Settings, qt_app: QApplication) -> None:
        super().__init__()
        self._logger = logging.getLogger(__name__)
        self._settings = settings
        self._qt_app = qt_app

        self._window = FloatingWindow(
            auto_hide_ms=settings.ui_auto_hide_ms,
            font_size=settings.translation_font_size,
            show_examples=settings.show_examples,
            wallpaper_path=settings.wallpaper_path,
        )
        self._debug_window = OcrDebugWindow() if settings.debug_overlay else None
        self._settings_window: SettingsWindow | None = None
        self._tray = AppTrayIcon()
        self._cache: LRUCache[str, TranslationResult] = LRUCache(settings.cache_size)
        self._mouse_tracker = MouseTracker(settings)
        self._text_extractor = TextExtractor()
        self._screen_capture = ScreenCapture()
        self._ocr_engine = OCREngine(settings.ocr_confidence_threshold)
        self._translator = Translator(
            settings.openai_model,
            settings.openai_timeout_s,
            settings.translation_backend,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_workers,
            thread_name_prefix="hover-worker",
        )

        self._latest_request_id = 0
        self._shutdown = False
        self._last_shown_position: tuple[int, int] | None = None
        self._last_shown_word: str | None = None
        self._missing_backend_logged = False

        self._mouse_tracker.translation_requested.connect(self._on_translation_requested)
        self._mouse_tracker.sentence_requested.connect(self._on_sentence_requested)
        self._mouse_tracker.examples_visibility_toggled.connect(self._on_examples_visibility_toggled)
        self._mouse_tracker.enabled_changed.connect(self._on_enabled_changed)

        self.lookup_started.connect(self._on_lookup_started)
        self.word_resolved.connect(self._on_word_resolved)
        self.sentence_resolved.connect(self._on_sentence_resolved)
        self.translation_ready.connect(self._on_translation_ready)
        self.background_error.connect(self._on_background_error)
        self.ocr_debug_ready.connect(self._on_ocr_debug_ready)

        self._tray.toggle_requested.connect(self.toggle_enabled)
        self._tray.settings_requested.connect(self.open_settings)
        self._tray.examples_toggle_requested.connect(self.toggle_examples)
        self._tray.quit_requested.connect(self._qt_app.quit)

    def start(self) -> None:
        self._logger.info("Starting controller")
        self._window.hide()
        if self._debug_window:
            self._debug_window.show()
        self._tray.show()
        self._tray.set_enabled_state(self._mouse_tracker.enabled)
        self._mouse_tracker.start()
        self._executor.submit(self._warm_up_ocr)

    def shutdown(self) -> None:
        if self._shutdown:
            return

        self._shutdown = True
        self._logger.info("Shutting down controller")

        self._mouse_tracker.stop()
        self._screen_capture.close()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._tray.hide()
        self._window.hide()
        if self._debug_window:
            self._debug_window.hide()

    def toggle_enabled(self) -> None:
        self._mouse_tracker.toggle_enabled()

    def open_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self._settings)
            self._settings_window.settings_saved.connect(self._on_settings_saved)
        else:
            self._settings_window.update_settings(self._settings)

        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def toggle_examples(self) -> None:
        self._set_examples_visible(not self._settings.show_examples)

    def _warm_up_ocr(self) -> None:
        try:
            self._ocr_engine.warm_up()
        except Exception:
            self._logger.exception("OCR warmup failed")

    def _on_translation_requested(self, x: int, y: int) -> None:
        if self._shutdown:
            return

        position = (x, y)
        self._latest_request_id += 1
        request_id = self._latest_request_id
        self._logger.info("Processing translate request %s at %s", request_id, position)
        self._window.show_status("Reading...", position)

        future = self._executor.submit(self._resolve_word_at_position, position)
        future.add_done_callback(
            lambda resolved_future, rid=request_id, pos=position: self._handle_word_resolution(
                resolved_future, rid, pos
            )
        )

    def _on_sentence_requested(self, x: int, y: int) -> None:
        if self._shutdown:
            return

        position = (x, y)
        self._latest_request_id += 1
        request_id = self._latest_request_id
        self._logger.info("Processing sentence request %s at %s", request_id, position)
        self._window.show_status("Reading sentence...", position)

        future = self._executor.submit(self._resolve_sentence_at_position, position)
        future.add_done_callback(
            lambda resolved_future, rid=request_id, pos=position: self._handle_sentence_resolution(
                resolved_future, rid, pos
            )
        )

    def _resolve_word_at_position(self, position: tuple[int, int]) -> WordHit | None:
        x, y = position

        word_hit = self._text_extractor.extract_word_at(x, y)
        if word_hit:
            self._logger.debug("Text-first extraction succeeded: %s", word_hit)
            return word_hit

        last_hit: WordHit | None = None
        for width, height in self._iter_capture_sizes():
            capture = self._screen_capture.capture_region(
                center_x=x,
                center_y=y,
                width=width,
                height=height,
            )
            ocr_result = self._ocr_engine.analyze_capture(capture, position)
            debug_info = ocr_result.debug_info
            edge_touching = self._selected_touches_capture_edge(debug_info)
            self._logger.info(
                "OCR capture region left=%s top=%s size=%sx%s cursor_rel=(%s,%s) selected=%s edge=%s",
                capture.region.left,
                capture.region.top,
                capture.region.width,
                capture.region.height,
                debug_info.cursor_x,
                debug_info.cursor_y,
                debug_info.selected_word or "<none>",
                edge_touching,
            )
            self.ocr_debug_ready.emit(debug_info)

            if ocr_result.word_hit:
                last_hit = ocr_result.word_hit
                if not edge_touching:
                    return ocr_result.word_hit

        return last_hit

    def _resolve_sentence_at_position(self, position: tuple[int, int]) -> WordHit | None:
        x, y = position

        focus_hit = self._resolve_word_at_position(position)
        focus_word = focus_hit.word if focus_hit else None

        sentence_hit = self._text_extractor.extract_sentence_at(x, y, focus_word)
        if sentence_hit:
            self._logger.debug("Text-first sentence extraction succeeded: %s", sentence_hit.word)
            return sentence_hit

        for width, height in self._iter_sentence_capture_sizes():
            capture = self._screen_capture.capture_region(
                center_x=x,
                center_y=y,
                width=width,
                height=height,
            )
            ocr_result = self._ocr_engine.analyze_capture(capture, position)
            debug_info = ocr_result.debug_info
            self._logger.info(
                "Sentence OCR capture left=%s top=%s size=%sx%s cursor_rel=(%s,%s) lines=%s selected=%s",
                capture.region.left,
                capture.region.top,
                capture.region.width,
                capture.region.height,
                debug_info.cursor_x,
                debug_info.cursor_y,
                len(ocr_result.lines),
                debug_info.selected_word or "<none>",
            )
            self.ocr_debug_ready.emit(debug_info)

            sentence = self._sentence_from_ocr_lines(
                ocr_result.lines,
                capture.region.top,
                position[1],
                focus_word,
            )
            if sentence:
                return WordHit(
                    word=sentence,
                    context=sentence,
                    raw_text=sentence,
                    source="ocr-sentence",
                    confidence=1.0,
                )

        if focus_hit and focus_hit.context:
            sentence = choose_sentence_from_text(focus_hit.context, focus_word=focus_word)
            if sentence:
                return WordHit(
                    word=sentence,
                    context=focus_hit.context,
                    raw_text=focus_hit.raw_text,
                    source=f"{focus_hit.source}-sentence",
                    confidence=focus_hit.confidence,
                )

        return None

    def _iter_capture_sizes(self) -> list[tuple[int, int]]:
        sizes: list[tuple[int, int]] = []
        width = float(self._settings.capture_width)
        height = float(self._settings.capture_height)
        attempts = max(1, self._settings.capture_attempts)
        growth = max(1.1, self._settings.capture_growth_factor)

        for _ in range(attempts):
            bounded_width = min(int(round(width)), self._settings.max_capture_width)
            bounded_height = min(int(round(height)), self._settings.max_capture_height)
            size = (bounded_width, bounded_height)
            if size not in sizes:
                sizes.append(size)
            if (
                bounded_width >= self._settings.max_capture_width
                and bounded_height >= self._settings.max_capture_height
            ):
                break
            width *= growth
            height *= growth
        return sizes

    def _iter_sentence_capture_sizes(self) -> list[tuple[int, int]]:
        base_height = min(self._settings.capture_height, self._settings.max_capture_height)
        sizes = [
            (self._settings.max_capture_width, base_height),
            (self._settings.sentence_capture_width, base_height),
            (self._settings.sentence_capture_width, self._settings.max_capture_height),
            (self._settings.sentence_capture_width, self._settings.sentence_capture_height),
        ]

        unique: list[tuple[int, int]] = []
        for width, height in sizes:
            size = (
                max(self._settings.capture_width, int(width)),
                max(self._settings.capture_height, int(height)),
            )
            if size not in unique:
                unique.append(size)
        return unique

    def _sentence_from_ocr_lines(
        self,
        lines: tuple[OcrTextLine, ...],
        region_top: int,
        cursor_y: int,
        focus_word: str | None,
    ) -> str | None:
        if not lines:
            return None

        relative_y = cursor_y - region_top
        scored_lines = []
        for line in lines:
            tokens = english_token_spans(line.text)
            if len(tokens) < 2 and not focus_word:
                continue
            top = min(point[1] for point in line.polygon)
            bottom = max(point[1] for point in line.polygon)
            left = min(point[0] for point in line.polygon)
            height = max(bottom - top, 1.0)
            center_distance = abs(((top + bottom) / 2.0) - relative_y)
            near_cursor = (top - height * 1.5) <= relative_y <= (bottom + height * 1.5)
            scored_lines.append((0 if near_cursor else 1, center_distance, top, left, line))

        if not scored_lines:
            return None

        scored_lines.sort(key=lambda item: (item[0], item[1]))
        selected = [item[-1] for item in scored_lines if item[0] == scored_lines[0][0]][:3]
        selected.sort(
            key=lambda line: (
                min(point[1] for point in line.polygon),
                min(point[0] for point in line.polygon),
            )
        )
        raw_text = normalize_text(" ".join(line.text for line in selected))
        return choose_sentence_from_text(raw_text, focus_word=focus_word)

    def _selected_touches_capture_edge(self, debug_info: object) -> bool:
        selected_polygon = getattr(debug_info, "selected_polygon", None)
        if not selected_polygon:
            return False

        margin = 4.0
        width = float(getattr(debug_info, "region_width", 0))
        height = float(getattr(debug_info, "region_height", 0))
        xs = [point[0] for point in selected_polygon]
        return (
            min(xs) <= margin
            or max(xs) >= width - margin
        )

    def _handle_word_resolution(
        self,
        future: Future[WordHit | None],
        request_id: int,
        position: tuple[int, int],
    ) -> None:
        try:
            result = future.result()
        except Exception as exc:
            self._logger.exception("Word resolution failed")
            self.background_error.emit(request_id, str(exc), position)
            return

        self.word_resolved.emit(request_id, result, position)

    def _handle_sentence_resolution(
        self,
        future: Future[WordHit | None],
        request_id: int,
        position: tuple[int, int],
    ) -> None:
        try:
            result = future.result()
        except Exception as exc:
            self._logger.exception("Sentence resolution failed")
            self.background_error.emit(request_id, str(exc), position)
            return

        self.sentence_resolved.emit(request_id, result, position)

    def _on_word_resolved(
        self,
        request_id: int,
        word_hit: WordHit | None,
        position: tuple[int, int],
    ) -> None:
        if not self._is_request_current(request_id):
            return

        if not word_hit:
            self._logger.debug("No word resolved for request %s", request_id)
            self._window.show_status("No word found", position)
            return

        self._translate_hit(request_id, word_hit, position, is_sentence=False)

    def _on_sentence_resolved(
        self,
        request_id: int,
        word_hit: WordHit | None,
        position: tuple[int, int],
    ) -> None:
        if not self._is_request_current(request_id):
            return

        if not word_hit:
            self._logger.debug("No sentence resolved for request %s", request_id)
            self._window.show_status("No sentence found", position)
            return

        self._translate_hit(request_id, word_hit, position, is_sentence=True)

    def _translate_hit(
        self,
        request_id: int,
        word_hit: WordHit,
        position: tuple[int, int],
        *,
        is_sentence: bool,
    ) -> None:
        cache_key = ("sentence:" if is_sentence else "word:") + normalize_text(word_hit.word).lower()
        cached = self._cache.get(cache_key)
        if cached:
            self._logger.debug("Cache hit for %s", cache_key)
            self.translation_ready.emit(request_id, cached, position)
            return

        if not self._translator.is_configured():
            if not self._missing_backend_logged:
                self._logger.warning(
                    "No translation backend is configured; backend=%s",
                    self._settings.translation_backend,
                )
                self._missing_backend_logged = True
            self._last_shown_word = cache_key
            self._last_shown_position = position
            self._window.show_status("Install local model or set API key", position)
            return

        self.lookup_started.emit(request_id, word_hit.word, position)
        translate_fn = self._translator.translate_sentence if is_sentence else self._translator.translate
        translation_future = self._executor.submit(translate_fn, word_hit.word, word_hit.context)
        translation_future.add_done_callback(
            lambda done_future, rid=request_id, pos=position, hit=word_hit, sentence=is_sentence: self._handle_translation(
                done_future, rid, pos, hit, sentence
            )
        )

    def _handle_translation(
        self,
        future: Future[TranslationResult],
        request_id: int,
        position: tuple[int, int],
        word_hit: WordHit,
        is_sentence: bool,
    ) -> None:
        try:
            translation = future.result()
        except Exception as exc:
            self._logger.exception("Translation failed for %s", word_hit.word)
            self.background_error.emit(request_id, str(exc), position)
            return

        cache_key = ("sentence:" if is_sentence else "word:") + normalize_text(translation.word).lower()
        self._cache.put(cache_key, translation)
        self.translation_ready.emit(request_id, translation, position)

    def _on_lookup_started(self, request_id: int, word: str, position: tuple[int, int]) -> None:
        if not self._is_request_current(request_id):
            return
        self._window.show_loading(word, position)

    def _on_translation_ready(
        self,
        request_id: int,
        result: TranslationResult,
        position: tuple[int, int],
    ) -> None:
        if not self._is_request_current(request_id):
            return

        self._logger.info(
            "Showing %s translation result for %s",
            result.source,
            result.word,
        )
        self._window.show_translation(result, position)
        self._last_shown_word = result.word.lower()
        self._last_shown_position = position

    def _on_background_error(self, request_id: int, message: str, position: tuple[int, int]) -> None:
        if not self._is_request_current(request_id):
            return

        self._logger.warning("Background task error: %s", message)
        self._window.show_status("Translation unavailable", position)

    def _on_ocr_debug_ready(self, debug_info: object) -> None:
        if self._debug_window:
            self._debug_window.show_ocr_debug(debug_info)

    def _on_settings_saved(self, settings: Settings) -> None:
        self._apply_settings(settings, persist=False)
        self._window.show_status("Settings applied", self._cursor_position())

    def _on_examples_visibility_toggled(self, show_examples: bool) -> None:
        self._set_examples_visible(show_examples)

    def _set_examples_visible(self, show_examples: bool) -> None:
        settings = with_updated_settings(self._settings, show_examples=show_examples)
        self._apply_settings(settings, persist=True)
        self._window.show_status(
            "Examples shown" if show_examples else "Examples hidden",
            self._cursor_position(),
        )

    def _apply_settings(self, settings: Settings, *, persist: bool) -> None:
        old_settings = self._settings
        self._settings = settings
        if persist:
            save_settings(settings)

        self._mouse_tracker.update_settings(settings)
        self._window.apply_settings(settings)
        if self._settings_window:
            self._settings_window.update_settings(settings)

        if settings.cache_size != old_settings.cache_size:
            self._cache = LRUCache(settings.cache_size)

        translator_changed = (
            settings.translation_backend != old_settings.translation_backend
            or settings.openai_model != old_settings.openai_model
            or settings.openai_timeout_s != old_settings.openai_timeout_s
        )
        if translator_changed:
            self._translator = Translator(
                settings.openai_model,
                settings.openai_timeout_s,
                settings.translation_backend,
            )
            self._missing_backend_logged = False

        if settings.debug_overlay and self._debug_window is None:
            self._debug_window = OcrDebugWindow()
            self._debug_window.show()
        elif not settings.debug_overlay and self._debug_window is not None:
            self._debug_window.hide()
            self._debug_window = None

    def _on_enabled_changed(self, enabled: bool) -> None:
        self._logger.info("Hotkey translation enabled=%s", enabled)
        self._tray.set_enabled_state(enabled)
        self._last_shown_position = None
        self._last_shown_word = None
        anchor = (QCursor.pos().x(), QCursor.pos().y())
        if not enabled:
            self._window.hide()
        self._window.show_status(
            "Hotkey translate enabled" if enabled else "Hotkey translate paused",
            anchor,
        )

    def _is_request_current(self, request_id: int) -> bool:
        return not self._shutdown and self._mouse_tracker.enabled and request_id == self._latest_request_id

    def _cursor_position(self) -> tuple[int, int]:
        cursor = QCursor.pos()
        return cursor.x(), cursor.y()
