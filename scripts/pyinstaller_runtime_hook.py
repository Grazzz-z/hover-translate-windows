from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))


root = _bundle_root()

paddlex_cache = root / "paddlex_cache"
if paddlex_cache.exists():
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(paddlex_cache))

argos_packages = root / "argos_packages"
if argos_packages.exists():
    os.environ.setdefault("ARGOS_PACKAGES_DIR", str(argos_packages))

os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_mkldnn_bfloat16", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
