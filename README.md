# Hotkey Translate for Windows

Hotkey Translate is a lightweight Windows desktop app that translates the English word under your mouse when you press a hotkey. It uses a dual-channel pipeline:

- Windows UI Automation for fast text-first extraction from native controls
- PaddleOCR on a tiny capture region as a fallback for images, videos, canvases, and non-accessible UI

## Features

- Global `Control+Shift` translate hotkey
- Runtime settings window for hotkeys, continuous mode, font size, examples, wallpaper, and debug overlay
- Optional continuous word translation when the mouse stays still
- Optional sentence translation after a configurable hover threshold, with a separate hotkey
- Tiny OCR region for lower CPU cost and better responsiveness
- Threaded OCR and translation pipeline so the PyQt UI stays responsive
- LRU cache for the last 100 translated words
- Cartoon-style floating, non-focus-stealing tooltip UI
- Local offline ECDICT dictionary backend by default
- Local offline Argos sentence translation when the English-to-Chinese package is installed
- Optional OpenAI backend for richer explanations
- System tray menu for enable/disable and quit
- Structured translation output: word, translation, phonetic, explanation, examples

## Project Layout

```text
app/
  core/
    cache.py
    mouse_tracker.py
    ocr_engine.py
    text_extractor.py
    translator.py
    types.py
  ui/
    floating_window.py
    settings_window.py
    debug_window.py
    tray_icon.py
  utils/
    screen_capture.py
    text_utils.py
scripts/
  download_local_models.py
config.py
main.py
requirements.txt
```

## Prerequisites

- Windows 10 or newer
- Python 3.10+
- Optional: an OpenAI API key in `OPENAI_API_KEY` if you choose the OpenAI backend

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts\download_local_models.py
```

## Run

```powershell
python main.py
```

Move the mouse over an English word, then press `Control+Shift` at the same time.

Right-click the tray icon and choose `Settings...` to adjust:

- Single-word hotkey, default `control+shift`
- Sentence hotkey, default `control+alt+s`
- Example toggle hotkey, default `control+alt+e`
- Continuous word translation mode
- Sentence hover mode and threshold, default `3000 ms`
- Floating card font size
- Optional wallpaper image for the translation card
- OCR debug window visibility

## Optional Environment Variables

- `TRANSLATION_BACKEND` default: `local`; supported: `local`, `openai`, `auto`
- `TRANSLATE_HOTKEY` default: `control+shift`
- `CONTINUOUS_MODE` default: `false`
- `SENTENCE_HOTKEY` default: `control+alt+s`
- `SENTENCE_HOVER_ENABLED` default: `false`
- `SENTENCE_HOVER_MS` default: `3000`
- `SHOW_EXAMPLES` default: `false`
- `EXAMPLES_HOTKEY` default: `control+alt+e`
- `TRANSLATION_FONT_SIZE` default: `14`
- `WALLPAPER_PATH` default: empty
- `OPENAI_MODEL` default: `gpt-4o-mini`
- `CAPTURE_WIDTH` default: `140`
- `CAPTURE_HEIGHT` default: `48`
- `MAX_CAPTURE_WIDTH` default: `460`
- `MAX_CAPTURE_HEIGHT` default: `160`
- `CAPTURE_GROWTH_FACTOR` default: `1.65`
- `CAPTURE_ATTEMPTS` default: `4`
- `DEBUG_LOGGING` default: `false`
- `DEBUG_OVERLAY` default: `true`

OpenAI mode:

```powershell
$env:TRANSLATION_BACKEND = "openai"
$env:OPENAI_API_KEY = "your_api_key_here"
python main.py
```

## Build Windows EXE

```powershell
.venv\Scripts\python.exe scripts\build_exe.py
```

The build creates:

- `dist\HoverTranslate\HoverTranslate.exe`
- `dist\HoverTranslate-portable.zip`

The portable zip includes the local dictionary, PaddleOCR mobile models, and the installed Argos English-to-Chinese package when available.

## Notes

- The first OCR request can be slower because PaddleOCR loads its CPU models lazily. Run `python scripts\download_local_models.py` once to prepare local models.
- UI Automation is attempted first for lower latency. OCR is only used when the control under the mouse does not expose useful text.
- Continuous screenshot/translation is disabled by default. If enabled, it still uses hover debounce and position caching to avoid repeated work at the same cursor location.
- Argos Translate is installed as an optional local neural translation library. The default word backend is the local ECDICT dictionary because it is faster and more reliable for single-word lookup; sentence mode uses Argos locally when available.
- The OCR debug window shows each screenshot region, cursor position, detected token boxes, and the selected word box. Set `DEBUG_OVERLAY=false` to hide it.
- OCR starts with a small capture region and expands it up to the configured maximum if no word is found or the selected word touches the screenshot edge.
- Sentence OCR first detects the focused word, then expands horizontally and vertically to collect the nearest line or sentence around the cursor.
