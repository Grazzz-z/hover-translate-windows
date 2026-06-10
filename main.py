from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from config import load_settings, setup_logging


def configure_bundled_runtime() -> None:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

    paddlex_cache = base_dir / "paddlex_cache"
    if paddlex_cache.exists():
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(paddlex_cache))

    argos_packages = base_dir / "argos_packages"
    if argos_packages.exists():
        os.environ.setdefault("ARGOS_PACKAGES_DIR", str(argos_packages))

    os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_enable_mkldnn_bfloat16", "0")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def main() -> int:
    configure_bundled_runtime()

    from app.application import HoverTranslateController

    settings = load_settings()
    setup_logging(settings)

    logging.getLogger(__name__).info("Starting hover translate desktop app")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Hover Translate")

    controller = HoverTranslateController(settings, app)
    controller.start()

    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
