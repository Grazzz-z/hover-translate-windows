from __future__ import annotations

import logging
import math
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from config import Settings

try:
    from pynput import keyboard, mouse
except ImportError:  # pragma: no cover - dependency check at runtime
    keyboard = None
    mouse = None


class MouseTracker(QObject):
    translation_requested = pyqtSignal(int, int)
    sentence_requested = pyqtSignal(int, int)
    examples_visibility_toggled = pyqtSignal(bool)
    enabled_changed = pyqtSignal(bool)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._logger = logging.getLogger(__name__)
        self._settings = settings
        self._lock = threading.Lock()

        self._current_pos: tuple[int, int] = (0, 0)
        self._anchor_pos: tuple[int, int] = (0, 0)
        self._anchor_since = time.monotonic()
        self._last_word_hover_pos: tuple[int, int] | None = None
        self._last_sentence_hover_pos: tuple[int, int] | None = None
        self._pressed_keys: set[str] = set()
        self._translate_keys = self._parse_hotkey(settings.translate_hotkey)
        self._sentence_keys = self._parse_hotkey(settings.sentence_hotkey)
        self._examples_keys = self._parse_hotkey(settings.examples_hotkey)
        self._last_trigger_at = 0.0
        self._last_action_at: dict[str, float] = {}
        self._last_key_event_at = 0.0
        self._trigger_cooldown_s = 0.35
        self._show_examples_state = settings.show_examples
        self._enabled = True
        self._running = False

        self._mouse_listener: mouse.Listener | None = None
        self._keyboard_listener: keyboard.Listener | None = None
        self._hover_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        if self._running:
            return

        if mouse is None or keyboard is None:
            raise RuntimeError("pynput is required for global mouse and keyboard hooks.")

        self._running = True
        self._stop_event.clear()
        self._current_pos = tuple(int(value) for value in mouse.Controller().position)
        self._anchor_pos = self._current_pos
        self._anchor_since = time.monotonic()

        self._mouse_listener = mouse.Listener(on_move=self._on_move)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._keyboard_listener.daemon = True
        self._keyboard_listener.start()

        self._hover_thread = threading.Thread(
            target=self._hover_loop,
            name="hover-watch",
            daemon=True,
        )
        self._hover_thread.start()

        self._logger.info(
            "Input tracker started; translate hotkey=%s sentence hotkey=%s examples hotkey=%s",
            self._settings.translate_hotkey,
            self._settings.sentence_hotkey,
            self._settings.examples_hotkey,
        )

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        if self._hover_thread and self._hover_thread.is_alive():
            self._hover_thread.join(timeout=0.5)
        self._logger.info("Input tracker stopped")

    def update_settings(self, settings: Settings) -> None:
        with self._lock:
            self._settings = settings
            self._translate_keys = self._parse_hotkey(settings.translate_hotkey)
            self._sentence_keys = self._parse_hotkey(settings.sentence_hotkey)
            self._examples_keys = self._parse_hotkey(settings.examples_hotkey)
            self._show_examples_state = settings.show_examples
            self._pressed_keys.clear()
            self._last_action_at.clear()
            self._last_key_event_at = time.monotonic()
            self._last_word_hover_pos = None
            self._last_sentence_hover_pos = None
        self._logger.info(
            "Input settings updated; translate=%s continuous=%s sentence=%s examples=%s",
            settings.translate_hotkey,
            settings.continuous_mode,
            settings.sentence_hotkey,
            settings.examples_hotkey,
        )

    def set_enabled(self, enabled: bool) -> None:
        changed = self._enabled != enabled
        self._enabled = enabled
        with self._lock:
            self._pressed_keys.clear()
            self._last_key_event_at = time.monotonic()
        if changed:
            self.enabled_changed.emit(enabled)

    def toggle_enabled(self) -> None:
        self.set_enabled(not self._enabled)

    def _on_move(self, x: int, y: int) -> None:
        with self._lock:
            position = (int(x), int(y))
            self._current_pos = position
            if self._distance(position, self._anchor_pos) > self._settings.hover_radius_px:
                self._anchor_pos = position
                self._anchor_since = time.monotonic()
                self._last_word_hover_pos = None
                self._last_sentence_hover_pos = None

    def _on_key_press(self, key: object) -> None:
        key_name = self._normalize_key(key)
        if not key_name:
            return

        with self._lock:
            now = time.monotonic()
            if now - self._last_key_event_at > 4.0:
                self._pressed_keys.clear()
            self._last_key_event_at = now
            self._pressed_keys.add(key_name)
            action = self._matching_hotkey_action(now)
            if action is None:
                return

            self._last_trigger_at = now
            self._last_action_at[action] = now
            position = self._current_pos
            if action == "examples":
                self._show_examples_state = not self._show_examples_state
                show_examples = self._show_examples_state
            else:
                show_examples = self._show_examples_state

        if action == "word":
            self.translation_requested.emit(position[0], position[1])
        elif action == "sentence":
            self.sentence_requested.emit(position[0], position[1])
        elif action == "examples":
            self.examples_visibility_toggled.emit(show_examples)

    def _on_key_release(self, key: object) -> None:
        key_name = self._normalize_key(key)
        if not key_name:
            return

        with self._lock:
            self._last_key_event_at = time.monotonic()
            self._pressed_keys.discard(key_name)

    def _normalize_key(self, key: object) -> str | None:
        char = getattr(key, "char", None)
        if isinstance(char, str) and char:
            if len(char) == 1 and 1 <= ord(char) <= 26:
                return chr(ord(char) + 96)
            return self._canonical_key(char.lower())

        name = getattr(key, "name", None)
        if isinstance(name, str) and name:
            return self._canonical_key(name.lower())
        return None

    def _parse_hotkey(self, hotkey: str) -> frozenset[str]:
        keys = {
            self._canonical_key(part.strip().lower())
            for part in hotkey.replace("<", "").replace(">", "").replace("+", ",").split(",")
            if part.strip()
        }
        if not keys:
            return frozenset({"ctrl", "shift"})
        return frozenset(keys)

    def _canonical_key(self, key_name: str) -> str:
        aliases = {
            "control": "ctrl",
            "ctrl_l": "ctrl",
            "ctrl_r": "ctrl",
            "control_l": "ctrl",
            "control_r": "ctrl",
            "shift_l": "shift",
            "shift_r": "shift",
            "alt_l": "alt",
            "alt_r": "alt",
            "menu": "alt",
            "option": "alt",
            "return": "enter",
            "esc": "escape",
        }
        return aliases.get(key_name, key_name)

    def _matching_hotkey_action(self, now: float) -> str | None:
        actions = [
            ("examples", self._examples_keys, True),
            ("sentence", self._sentence_keys, self._settings.sentence_hotkey_enabled),
            ("word", self._translate_keys, True),
        ]
        actions.sort(key=lambda item: len(item[1]), reverse=True)

        for action, keys, allowed in actions:
            if not allowed or not keys.issubset(self._pressed_keys):
                continue
            if action != "examples" and not self._enabled:
                continue
            if (now - self._last_action_at.get(action, 0.0)) < self._trigger_cooldown_s:
                return None
            return action
        return None

    def _hover_loop(self) -> None:
        while not self._stop_event.wait(0.05):
            emit_word = False
            emit_sentence = False
            with self._lock:
                if not self._running or not self._enabled:
                    continue

                now = time.monotonic()
                stable_ms = (now - self._anchor_since) * 1000.0
                position = self._current_pos
                settings = self._settings

                if (
                    settings.sentence_hover_enabled
                    and stable_ms >= settings.sentence_hover_ms
                    and self._should_emit_sentence_hover(position, settings)
                ):
                    emit_sentence = True
                    self._last_sentence_hover_pos = position
                elif (
                    settings.continuous_mode
                    and stable_ms >= settings.hover_delay_ms
                    and self._should_emit_word_hover(position, settings)
                ):
                    emit_word = True
                    self._last_word_hover_pos = position

            if emit_sentence:
                self.sentence_requested.emit(position[0], position[1])
            elif emit_word:
                self.translation_requested.emit(position[0], position[1])

    def _should_emit_word_hover(self, position: tuple[int, int], settings: Settings) -> bool:
        return (
            self._last_word_hover_pos is None
            or self._distance(position, self._last_word_hover_pos) > settings.processed_radius_px
        )

    def _should_emit_sentence_hover(self, position: tuple[int, int], settings: Settings) -> bool:
        return (
            self._last_sentence_hover_pos is None
            or self._distance(position, self._last_sentence_hover_pos) > settings.processed_radius_px
        )

    def _distance(self, a: tuple[int, int], b: tuple[int, int]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])
