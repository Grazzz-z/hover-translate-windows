from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def download_dictionary(force: bool = False) -> None:
    from app.core.local_dictionary import CSV_PATH, build_dictionary

    if force or not CSV_PATH.exists():
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
            CSV_PATH,
        )
        print(f"Downloaded ECDICT CSV: {CSV_PATH}")

    db_path = build_dictionary(force=force)
    print(f"Built local dictionary database: {db_path}")


def install_argos_model() -> None:
    import argostranslate.package as package

    package.update_package_index()
    available_packages = package.get_available_packages()
    model = next(
        item
        for item in available_packages
        if item.from_code == "en" and item.to_code == "zh"
    )
    path = model.download()
    package.install_from_path(path)
    print(f"Installed Argos model: {model.from_code}->{model.to_code} {model.package_version}")


def warm_paddle_ocr() -> None:
    from app.core.ocr_engine import OCREngine
    from app.utils.screen_capture import CaptureFrame, CaptureRegion

    frame = CaptureFrame(
        image=np.zeros((48, 140, 3), dtype=np.uint8),
        region=CaptureRegion(left=0, top=0, width=140, height=48),
    )
    OCREngine().extract_word_from_capture(frame, (70, 24))
    print("PaddleOCR local models are ready")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-dictionary", action="store_true")
    parser.add_argument("--skip-dictionary", action="store_true")
    parser.add_argument("--with-argos", action="store_true")
    parser.add_argument("--skip-argos", action="store_true")
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args()

    if not args.skip_dictionary:
        download_dictionary(force=args.force_dictionary)
    if args.with_argos and not args.skip_argos:
        install_argos_model()
    if not args.skip_ocr:
        warm_paddle_ocr()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
