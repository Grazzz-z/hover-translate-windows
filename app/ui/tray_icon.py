from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon


class AppTrayIcon(QSystemTrayIcon):
    toggle_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    examples_toggle_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self) -> None:
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        super().__init__(icon)

        self._menu = QMenu()
        self._settings_action = QAction("Settings...")
        self._settings_action.triggered.connect(self.settings_requested.emit)

        self._toggle_action = QAction("Disable hotkey translation")
        self._toggle_action.triggered.connect(self.toggle_requested.emit)

        self._examples_action = QAction("Toggle examples")
        self._examples_action.triggered.connect(self.examples_toggle_requested.emit)

        self._quit_action = QAction("Quit")
        self._quit_action.triggered.connect(self.quit_requested.emit)

        self._menu.addAction(self._settings_action)
        self._menu.addSeparator()
        self._menu.addAction(self._toggle_action)
        self._menu.addAction(self._examples_action)
        self._menu.addSeparator()
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def set_enabled_state(self, enabled: bool) -> None:
        self._toggle_action.setText(
            "Disable hotkey translation" if enabled else "Enable hotkey translation"
        )
        self.setToolTip("Hover Translate (Enabled)" if enabled else "Hover Translate (Paused)")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_requested.emit()
