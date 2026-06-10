from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields, replace
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(slots=True, frozen=True)
class Settings:
    hover_delay_ms: int = 300
    hover_radius_px: int = 5
    processed_radius_px: int = 18
    translate_hotkey: str = "control+shift"
    continuous_mode: bool = False
    capture_width: int = 140
    capture_height: int = 48
    max_capture_width: int = 460
    max_capture_height: int = 160
    capture_growth_factor: float = 1.65
    capture_attempts: int = 4
    sentence_hover_enabled: bool = False
    sentence_hotkey_enabled: bool = True
    sentence_hotkey: str = "control+alt+s"
    sentence_hover_ms: int = 3000
    sentence_capture_width: int = 760
    sentence_capture_height: int = 220
    examples_hotkey: str = "control+alt+e"
    show_examples: bool = False
    translation_font_size: int = 14
    wallpaper_path: str = ""
    ui_auto_hide_ms: int = 2000
    cache_size: int = 100
    max_workers: int = 4
    toggle_hotkey: str = "<ctrl>+<alt>+t"
    translation_backend: str = "local"
    openai_model: str = "gpt-4o-mini"
    openai_timeout_s: float = 8.0
    ocr_confidence_threshold: float = 0.45
    debug_logging: bool = False
    debug_overlay: bool = True


PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = PROJECT_ROOT / "settings.json"


def load_settings() -> Settings:
    defaults = Settings(
        hover_delay_ms=_env_int("HOVER_DELAY_MS", 300),
        hover_radius_px=_env_int("HOVER_RADIUS_PX", 5),
        processed_radius_px=_env_int("PROCESSED_RADIUS_PX", 18),
        translate_hotkey=os.getenv("TRANSLATE_HOTKEY", "control+shift"),
        continuous_mode=_env_bool("CONTINUOUS_MODE", False),
        capture_width=_env_int("CAPTURE_WIDTH", 140),
        capture_height=_env_int("CAPTURE_HEIGHT", 48),
        max_capture_width=_env_int("MAX_CAPTURE_WIDTH", 460),
        max_capture_height=_env_int("MAX_CAPTURE_HEIGHT", 160),
        capture_growth_factor=_env_float("CAPTURE_GROWTH_FACTOR", 1.65),
        capture_attempts=_env_int("CAPTURE_ATTEMPTS", 4),
        sentence_hover_enabled=_env_bool("SENTENCE_HOVER_ENABLED", False),
        sentence_hotkey_enabled=_env_bool("SENTENCE_HOTKEY_ENABLED", True),
        sentence_hotkey=os.getenv("SENTENCE_HOTKEY", "control+alt+s"),
        sentence_hover_ms=_env_int("SENTENCE_HOVER_MS", 3000),
        sentence_capture_width=_env_int("SENTENCE_CAPTURE_WIDTH", 760),
        sentence_capture_height=_env_int("SENTENCE_CAPTURE_HEIGHT", 220),
        examples_hotkey=os.getenv("EXAMPLES_HOTKEY", "control+alt+e"),
        show_examples=_env_bool("SHOW_EXAMPLES", False),
        translation_font_size=_env_int("TRANSLATION_FONT_SIZE", 14),
        wallpaper_path=os.getenv("WALLPAPER_PATH", ""),
        ui_auto_hide_ms=_env_int("UI_AUTO_HIDE_MS", 2000),
        cache_size=_env_int("CACHE_SIZE", 100),
        max_workers=_env_int("MAX_WORKERS", 4),
        toggle_hotkey=os.getenv("TOGGLE_HOTKEY", "<ctrl>+<alt>+t"),
        translation_backend=os.getenv("TRANSLATION_BACKEND", "local").strip().lower(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_timeout_s=_env_float("OPENAI_TIMEOUT_S", 8.0),
        ocr_confidence_threshold=_env_float("OCR_CONFIDENCE_THRESHOLD", 0.45),
        debug_logging=_env_bool("DEBUG_LOGGING", False),
        debug_overlay=_env_bool("DEBUG_OVERLAY", True),
    )
    return _load_user_settings(defaults)


def save_settings(settings: Settings) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def with_updated_settings(settings: Settings, **changes: object) -> Settings:
    return replace(settings, **_coerce_settings_values(changes))


def _load_user_settings(defaults: Settings) -> Settings:
    if not SETTINGS_FILE.exists():
        return defaults

    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults

    if not isinstance(raw, dict):
        return defaults

    values = {field.name: getattr(defaults, field.name) for field in fields(Settings)}
    values.update(_coerce_settings_values(raw))
    return Settings(**values)


def _coerce_settings_values(raw: dict[str, object]) -> dict[str, object]:
    defaults = Settings()
    field_names = {field.name for field in fields(Settings)}
    coerced: dict[str, object] = {}

    for key, value in raw.items():
        if key not in field_names:
            continue
        default = getattr(defaults, key)
        if isinstance(default, bool):
            coerced[key] = _coerce_bool(value, default)
        elif isinstance(default, int) and not isinstance(default, bool):
            coerced[key] = _coerce_int(value, default)
        elif isinstance(default, float):
            coerced[key] = _coerce_float(value, default)
        elif isinstance(default, str):
            coerced[key] = str(value).strip()
        else:
            coerced[key] = value
    return coerced


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def setup_logging(settings: Settings) -> None:
    log_level = logging.DEBUG if settings.debug_logging else logging.INFO
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "hover_translate.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(threadName)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
