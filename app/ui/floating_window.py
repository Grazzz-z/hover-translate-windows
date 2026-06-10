from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtGui import QCursor, QFont, QFontMetrics, QGuiApplication
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.core.types import TranslationResult
from config import Settings


class FloatingWindow(QWidget):
    def __init__(
        self,
        auto_hide_ms: int = 2000,
        font_size: int = 14,
        show_examples: bool = False,
        wallpaper_path: str = "",
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._auto_hide_ms = auto_hide_ms
        self._font_size = font_size
        self._show_examples = show_examples
        self._wallpaper_path = wallpaper_path
        self._min_content_width = 300
        self._max_content_width = 620

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self._card = QFrame(self)
        self._card.setObjectName("card")

        self._word_label = QLabel()
        self._word_label.setObjectName("word")
        self._word_label.setWordWrap(True)

        self._translation_label = QLabel()
        self._translation_label.setObjectName("translation")
        self._translation_label.setWordWrap(True)

        self._phonetic_label = QLabel()
        self._phonetic_label.setObjectName("phonetic")

        self._explanation_label = QLabel()
        self._explanation_label.setObjectName("explanation")
        self._explanation_label.setWordWrap(True)

        self._examples_label = QLabel()
        self._examples_label.setObjectName("examples")
        self._examples_label.setWordWrap(True)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(18, 15, 18, 15)
        card_layout.setSpacing(6)
        card_layout.addWidget(self._word_label)
        card_layout.addWidget(self._translation_label)
        card_layout.addWidget(self._phonetic_label)
        card_layout.addWidget(self._explanation_label)
        card_layout.addWidget(self._examples_label)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self._card)

        self._apply_fonts()
        self._apply_style()

    def apply_settings(self, settings: Settings) -> None:
        self._auto_hide_ms = settings.ui_auto_hide_ms
        self._font_size = settings.translation_font_size
        self._show_examples = settings.show_examples
        self._wallpaper_path = settings.wallpaper_path
        self._apply_fonts()
        self._apply_style()

    def set_show_examples(self, show_examples: bool) -> None:
        self._show_examples = show_examples
        self._examples_label.setVisible(show_examples and bool(self._examples_label.text()))
        self.adjustSize()

    def show_loading(self, word: str, anchor: tuple[int, int]) -> None:
        self._hide_timer.stop()
        self._apply_content(
            word=word,
            translation="Translating...",
            phonetic="",
            explanation="",
            examples=(),
        )
        self._show_near(anchor)

    def show_translation(self, result: TranslationResult, anchor: tuple[int, int]) -> None:
        self._apply_content(
            word=result.word,
            translation=result.translation,
            phonetic=result.phonetic,
            explanation=result.explanation,
            examples=result.examples,
        )
        self._show_near(anchor)
        self._hide_timer.start(max(self._auto_hide_ms, 3200) if result.examples else self._auto_hide_ms)

    def show_status(self, message: str, anchor: tuple[int, int] | None = None) -> None:
        self._hide_timer.stop()
        self._apply_content(
            word="Hover Translate",
            translation=message,
            phonetic="",
            explanation="",
            examples=(),
        )
        self._show_near(anchor or self._cursor_tuple())
        self._hide_timer.start(1200)

    def _apply_content(
        self,
        word: str,
        translation: str,
        phonetic: str,
        explanation: str,
        examples: tuple[str, ...],
    ) -> None:
        examples_text = "\n".join(f"例句 {index + 1}: {example}" for index, example in enumerate(examples))
        content_width = self._measure_content_width(
            word,
            translation,
            phonetic,
            explanation,
            examples_text,
        )
        for label in (
            self._word_label,
            self._translation_label,
            self._phonetic_label,
            self._explanation_label,
            self._examples_label,
        ):
            label.setFixedWidth(content_width)

        self._word_label.setText(word)
        self._translation_label.setText(translation)
        self._phonetic_label.setVisible(bool(phonetic))
        self._phonetic_label.setText(phonetic)
        self._explanation_label.setVisible(bool(explanation))
        self._explanation_label.setText(explanation)
        self._examples_label.setVisible(self._show_examples and bool(examples_text))
        self._examples_label.setText(examples_text)
        self.adjustSize()

    def _measure_content_width(
        self,
        word: str,
        translation: str,
        phonetic: str,
        explanation: str,
        examples: str,
    ) -> int:
        measured = self._min_content_width
        for text, label in (
            (word, self._word_label),
            (translation, self._translation_label),
            (phonetic, self._phonetic_label),
            (explanation, self._explanation_label),
            (examples, self._examples_label),
        ):
            if not text:
                continue
            metrics = QFontMetrics(label.font())
            for line in text.splitlines() or [text]:
                measured = max(measured, metrics.horizontalAdvance(line) + 12)
        return max(self._min_content_width, min(self._max_content_width, measured))

    def _show_near(self, anchor: tuple[int, int]) -> None:
        position = QPoint(anchor[0], anchor[1])
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen else None

        self.adjustSize()
        size = self.sizeHint().expandedTo(self.minimumSizeHint())
        self.resize(size)

        margin = 10
        x = anchor[0] + 14
        y = anchor[1] + 14

        if geometry is not None:
            if x + size.width() > geometry.right() - margin:
                x = anchor[0] - size.width() - 14
            if y + size.height() > geometry.bottom() - margin:
                y = anchor[1] - size.height() - 14
            x = min(max(geometry.left() + margin, x), geometry.right() - size.width() - margin)
            y = min(max(geometry.top() + margin, y), geometry.bottom() - size.height() - margin)

        self.move(x, y)
        self.show()
        self.raise_()

    def _cursor_tuple(self) -> tuple[int, int]:
        cursor = QCursor.pos()
        return cursor.x(), cursor.y()

    def _apply_fonts(self) -> None:
        base = max(10, min(28, self._font_size))
        self._word_label.setFont(QFont("Comic Sans MS", base + 2, QFont.Weight.Bold))
        self._translation_label.setFont(QFont("Microsoft YaHei UI", base, QFont.Weight.Bold))
        self._phonetic_label.setFont(QFont("Consolas", max(9, base - 2)))
        self._explanation_label.setFont(QFont("Microsoft YaHei UI", max(9, base - 3)))
        self._examples_label.setFont(QFont("Microsoft YaHei UI", max(9, base - 2)))

    def _apply_style(self) -> None:
        wallpaper = Path(self._wallpaper_path).expanduser() if self._wallpaper_path else None
        if wallpaper and wallpaper.exists():
            image_path = str(wallpaper.resolve()).replace("\\", "/")
            card_background = (
                f'border-image: url("{image_path}") 0 0 0 0 stretch stretch;'
                "background-color: rgba(255, 248, 222, 230);"
            )
        else:
            card_background = (
                "background-color: qlineargradient("
                "x1:0, y1:0, x2:1, y2:1, "
                "stop:0 #fff2b8, stop:0.52 #b2f7ef, stop:1 #ffd6a5"
                ");"
            )

        self.setStyleSheet(
            f"""
            QWidget {{
                background: transparent;
            }}
            QFrame#card {{
                {card_background}
                border: 3px solid #ffb703;
                border-radius: 18px;
            }}
            QLabel#word {{
                color: #2f2a1f;
                letter-spacing: 0.5px;
            }}
            QLabel#translation {{
                color: #095d68;
            }}
            QLabel#phonetic {{
                color: #2d6a4f;
                background: rgba(255, 255, 255, 90);
                border-radius: 8px;
                padding: 2px 6px;
            }}
            QLabel#explanation {{
                color: #6d4c41;
            }}
            QLabel#examples {{
                color: #374151;
                background: rgba(255, 255, 255, 130);
                border: 1px dashed rgba(255, 183, 3, 180);
                border-radius: 10px;
                padding: 6px 8px;
            }}
            """
        )
