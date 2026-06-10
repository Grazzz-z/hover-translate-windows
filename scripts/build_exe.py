from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
APP_DIR = DIST_DIR / "HoverTranslate"
ZIP_PATH = DIST_DIR / "HoverTranslate-portable.zip"


def main() -> int:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "HoverTranslate.spec",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    if not APP_DIR.exists():
        raise FileNotFoundError(f"Build output not found: {APP_DIR}")

    (APP_DIR / "使用说明.txt").write_text(
        "\n".join(
            [
                "Hover Translate",
                "",
                "1. 双击 HoverTranslate.exe 启动。",
                "2. 默认单词翻译快捷键：Control+Shift。",
                "3. 默认整句翻译快捷键：Control+Alt+S。",
                "4. 默认例句显示切换：Control+Alt+E。",
                "5. 右键系统托盘图标，点击 Settings... 可以修改快捷键、字号、壁纸和翻译模式。",
                "6. 如果 Windows SmartScreen 提示未知发布者，请选择更多信息后继续运行；当前 exe 未做代码签名。",
                "",
            ]
        ),
        encoding="utf-8",
    )

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    shutil.make_archive(str(ZIP_PATH.with_suffix("")), "zip", APP_DIR)

    print(f"EXE: {APP_DIR / 'HoverTranslate.exe'}")
    print(f"ZIP: {ZIP_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
