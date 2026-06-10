from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from app.core.types import OcrDebugBox, OcrDebugInfo


class OcrDebugWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("OCR Debug")
        self.resize(620, 460)

        self._image_label = QLabel("No OCR screenshot yet")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(220)
        self._image_label.setStyleSheet("background: #111827; color: #d1d5db;")

        self._info = QPlainTextEdit()
        self._info.setReadOnly(True)
        self._info.setMaximumBlockCount(200)
        self._info.setStyleSheet(
            "background: #0b1220; color: #dbeafe; font-family: Consolas; font-size: 12px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self._image_label)
        layout.addWidget(self._info)

    def show_ocr_debug(self, debug_info: OcrDebugInfo) -> None:
        pixmap = self._make_pixmap(debug_info)
        self._image_label.setPixmap(pixmap)
        self._info.setPlainText(self._format_info(debug_info))
        if not self.isVisible():
            self.show()
        self.raise_()

    def _make_pixmap(self, debug_info: OcrDebugInfo) -> QPixmap:
        image = np.asarray(debug_info.image)
        if image.ndim != 3 or image.shape[2] < 3:
            return QPixmap()

        rgb = np.ascontiguousarray(image[:, :, :3][:, :, ::-1])
        height, width, channels = rgb.shape
        qimage = QImage(
            rgb.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()

        scale = max(2, min(5, 520 // max(width, 1)))
        pixmap = QPixmap.fromImage(qimage).scaled(
            width * scale,
            height * scale,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._draw_boxes(painter, debug_info.boxes, scale)
        self._draw_cursor(painter, debug_info.cursor_x * scale, debug_info.cursor_y * scale)
        painter.end()
        return pixmap

    def _draw_boxes(
        self,
        painter: QPainter,
        boxes: tuple[OcrDebugBox, ...],
        scale: int,
    ) -> None:
        for box in boxes:
            color = QColor("#22c55e") if box.selected else QColor("#facc15")
            pen_width = 3 if box.selected else 1
            painter.setPen(QPen(color, pen_width))
            points = [QPointF(point[0] * scale, point[1] * scale) for point in box.polygon]
            for index, point in enumerate(points):
                painter.drawLine(point, points[(index + 1) % len(points)])

    def _draw_cursor(self, painter: QPainter, x: int, y: int) -> None:
        painter.setPen(QPen(QColor("#ef4444"), 2))
        painter.drawLine(x - 8, y, x + 8, y)
        painter.drawLine(x, y - 8, x, y + 8)

    def _format_info(self, debug_info: OcrDebugInfo) -> str:
        lines = [
            f"capture: left={debug_info.region_left}, top={debug_info.region_top}, "
            f"size={debug_info.region_width}x{debug_info.region_height}",
            f"cursor in capture: x={debug_info.cursor_x}, y={debug_info.cursor_y}",
            f"elapsed: {debug_info.elapsed_ms:.1f} ms",
            f"selected: {debug_info.selected_word or '<none>'}",
            "",
            "boxes:",
        ]
        for box in debug_info.boxes[:40]:
            mark = "*" if box.selected else "-"
            lines.append(
                f"{mark} {box.text} | conf={box.confidence:.2f}"
                + (f" | raw={box.raw_text}" if box.raw_text and box.raw_text != box.text else "")
            )
        return "\n".join(lines)
