from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from config import Settings, save_settings, with_updated_settings


class SettingsWindow(QDialog):
    settings_saved = pyqtSignal(object)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

        self.setWindowTitle("Hover Translate 设置")
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self._translate_hotkey = QLineEdit()
        self._continuous_mode = QCheckBox("不按快捷键，鼠标停留后自动翻译单词")

        self._sentence_hover_enabled = QCheckBox("鼠标停留超过阈值后自动翻译整句")
        self._sentence_hotkey_enabled = QCheckBox("启用整句翻译快捷键")
        self._sentence_hotkey = QLineEdit()
        self._sentence_hover_ms = QSpinBox()
        self._sentence_hover_ms.setRange(500, 10000)
        self._sentence_hover_ms.setSingleStep(250)
        self._sentence_hover_ms.setSuffix(" ms")

        self._font_size = QSpinBox()
        self._font_size.setRange(10, 28)
        self._font_size.setSuffix(" px")

        self._show_examples = QCheckBox("显示例句")
        self._examples_hotkey = QLineEdit()

        self._wallpaper_path = QLineEdit()
        self._wallpaper_path.setPlaceholderText("可选：选择一张图片作为翻译卡片背景")
        browse_button = QPushButton("选择图片")
        browse_button.clicked.connect(self._browse_wallpaper)

        wallpaper_layout = QHBoxLayout()
        wallpaper_layout.addWidget(self._wallpaper_path, 1)
        wallpaper_layout.addWidget(browse_button)

        self._debug_overlay = QCheckBox("显示 OCR 调试窗口")
        self._backend = QComboBox()
        self._backend.addItems(["local", "argos", "openai", "auto"])

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("单词快捷键", self._translate_hotkey)
        form.addRow("", self._continuous_mode)
        form.addRow("整句快捷键", self._sentence_hotkey)
        form.addRow("", self._sentence_hotkey_enabled)
        form.addRow("", self._sentence_hover_enabled)
        form.addRow("整句停留阈值", self._sentence_hover_ms)
        form.addRow("翻译字号", self._font_size)
        form.addRow("", self._show_examples)
        form.addRow("例句快捷键", self._examples_hotkey)
        form.addRow("翻译后端", self._backend)
        form.addRow("卡片壁纸", wallpaper_layout)
        form.addRow("", self._debug_overlay)

        hint = QLabel(
            "快捷键格式示例：control+shift、control+alt+s、control+alt+e。"
            "建议不要让两个快捷键互相包含，避免按键先后触发冲突。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")

        save_button = QPushButton("保存并应用")
        save_button.clicked.connect(self._save)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        buttons.addWidget(close_button)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        root.addLayout(form)
        root.addWidget(hint)
        root.addLayout(buttons)

        self.setStyleSheet(
            """
            QDialog {
                background: #fff8df;
                color: #3d2f1f;
                font-family: "Microsoft YaHei UI", "Segoe UI";
                font-size: 13px;
            }
            QLineEdit, QSpinBox, QComboBox {
                background: rgba(255, 255, 255, 210);
                border: 2px solid #ffd166;
                border-radius: 8px;
                padding: 6px 8px;
            }
            QCheckBox {
                padding: 4px 0;
            }
            QPushButton {
                background: #7bdff2;
                border: 0;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #b2f7ef;
            }
            QLabel#hint {
                color: #7c5e33;
                background: rgba(255, 236, 173, 150);
                border-radius: 10px;
                padding: 8px;
            }
            """
        )

        self.update_settings(settings)

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._translate_hotkey.setText(settings.translate_hotkey)
        self._continuous_mode.setChecked(settings.continuous_mode)
        self._sentence_hover_enabled.setChecked(settings.sentence_hover_enabled)
        self._sentence_hotkey_enabled.setChecked(settings.sentence_hotkey_enabled)
        self._sentence_hotkey.setText(settings.sentence_hotkey)
        self._sentence_hover_ms.setValue(settings.sentence_hover_ms)
        self._font_size.setValue(settings.translation_font_size)
        self._show_examples.setChecked(settings.show_examples)
        self._examples_hotkey.setText(settings.examples_hotkey)
        self._wallpaper_path.setText(settings.wallpaper_path)
        self._debug_overlay.setChecked(settings.debug_overlay)
        backend_index = self._backend.findText(settings.translation_backend)
        self._backend.setCurrentIndex(max(0, backend_index))

    def _save(self) -> None:
        settings = with_updated_settings(
            self._settings,
            translate_hotkey=self._translate_hotkey.text() or "control+shift",
            continuous_mode=self._continuous_mode.isChecked(),
            sentence_hover_enabled=self._sentence_hover_enabled.isChecked(),
            sentence_hotkey_enabled=self._sentence_hotkey_enabled.isChecked(),
            sentence_hotkey=self._sentence_hotkey.text() or "control+alt+s",
            sentence_hover_ms=self._sentence_hover_ms.value(),
            translation_font_size=self._font_size.value(),
            show_examples=self._show_examples.isChecked(),
            examples_hotkey=self._examples_hotkey.text() or "control+alt+e",
            wallpaper_path=self._wallpaper_path.text().strip(),
            debug_overlay=self._debug_overlay.isChecked(),
            translation_backend=self._backend.currentText().strip().lower(),
        )
        save_settings(settings)
        self.update_settings(settings)
        self.settings_saved.emit(settings)

    def _browse_wallpaper(self) -> None:
        start_dir = str(Path(self._wallpaper_path.text()).parent) if self._wallpaper_path.text() else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择翻译卡片壁纸",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*.*)",
        )
        if path:
            self._wallpaper_path.setText(path)
