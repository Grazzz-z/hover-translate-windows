# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


project_root = Path(SPECPATH)
home = Path.home()

datas = []
binaries = []
hiddenimports = []


def add_package(package_name: str) -> None:
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)


for package in (
    "PyQt6",
    "Cython",
    "bidi",
    "cv2",
    "imagesize",
    "mss",
    "numpy",
    "pyclipper",
    "pypdfium2",
    "pynput",
    "shapely",
    "uiautomation",
    "paddle",
    "paddleocr",
    "paddlex",
    "argostranslate",
    "ctranslate2",
    "sentencepiece",
    "stanza",
    "spacy",
):
    add_package(package)


for distribution in (
    "imagesize",
    "opencv-contrib-python",
    "pyclipper",
    "pypdfium2",
    "python-bidi",
    "shapely",
):
    datas.extend(copy_metadata(distribution))


def add_data_path(source: Path, target: str) -> None:
    if source.exists():
        datas.append((str(source), target))


add_data_path(project_root / "data" / "ecdict.sqlite", "data")
add_data_path(project_root / "data" / "tech_academic_terms.csv", "data")
add_data_path(project_root / "data" / "user_terms.example.csv", "data")
add_data_path(project_root / "README.md", ".")

add_data_path(
    home / ".paddlex" / "official_models" / "PP-OCRv5_mobile_det",
    "paddlex_cache/official_models/PP-OCRv5_mobile_det",
)
add_data_path(
    home / ".paddlex" / "official_models" / "en_PP-OCRv5_mobile_rec",
    "paddlex_cache/official_models/en_PP-OCRv5_mobile_rec",
)
add_data_path(
    home / ".local" / "share" / "argos-translate" / "packages" / "translate-en_zh-1_9",
    "argos_packages/translate-en_zh-1_9",
)


a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "scripts" / "pyinstaller_runtime_hook.py")],
    excludes=[
        "IPython",
        "jupyter",
        "matplotlib",
        "notebook",
        "pytest",
        "tensorflow",
        "torch",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HoverTranslate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HoverTranslate",
)
