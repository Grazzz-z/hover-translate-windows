from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "kaikki_terms.csv"
DEFAULT_KAIKKI_URL = "https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz"

FIELDNAMES = (
    "term",
    "translation",
    "phonetic",
    "definition",
    "examples",
    "tags",
    "case_sensitive",
)

CHINESE_LANG_CODES = {"zh", "zho", "cmn", "zh-cn", "zh-hans", "zh-hant"}
CHINESE_LANG_MARKERS = ("chinese", "mandarin")
TERM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'\-()/+]*$")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import Chinese translations from a Kaikki/Wiktextract JSONL dump "
            "into data/kaikki_terms.csv."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="Local .jsonl/.jsonl.gz file or URL. Use --download to stream Kaikki's raw dump.",
    )
    parser.add_argument("--download", action="store_true", help="Stream the official Kaikki raw JSONL.GZ dump.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="CSV output path.")
    parser.add_argument("--max-terms", type=int, default=30000, help="Stop after this many unique terms. Use 0 for no limit.")
    parser.add_argument("--append", action="store_true", help="Merge into the existing output instead of replacing it.")
    parser.add_argument("--phrases-only", action="store_true", help="Only import terms containing spaces, hyphens, or dots.")
    parser.add_argument("--progress-every", type=int, default=100000, help="Print progress after N JSON records.")
    args = parser.parse_args()

    source = args.source
    if args.download:
        source = source or DEFAULT_KAIKKI_URL
    if not source:
        parser.error("provide a Kaikki JSONL path/URL, or pass --download")

    rows: dict[str, dict[str, str]] = {}
    if args.append and args.output.exists():
        rows.update(_read_existing_rows(args.output))

    records_seen = 0
    imported = 0
    max_terms = args.max_terms if args.max_terms > 0 else None

    with _open_text_stream(source) as stream:
        for record in _iter_json_lines(stream):
            records_seen += 1
            if args.progress_every > 0 and records_seen % args.progress_every == 0:
                print(
                    f"Scanned {records_seen:,} records; imported {len(rows):,} unique terms",
                    file=sys.stderr,
                )

            row = _record_to_row(record, phrases_only=args.phrases_only)
            if row is None:
                continue

            key = _normalize_term(row["term"])
            before = len(rows)
            _merge_row(rows, key, row)
            if len(rows) > before:
                imported += 1
            if max_terms is not None and len(rows) >= max_terms:
                break

    _write_rows(args.output, rows.values())
    print(f"Scanned records: {records_seen:,}")
    print(f"Imported new rows: {imported:,}")
    print(f"Total unique terms written: {len(rows):,}")
    print(f"Output: {args.output}")
    return 0


@contextmanager
def _open_text_stream(source: str) -> Iterator[TextIO]:
    if source.startswith(("http://", "https://")):
        response = urllib.request.urlopen(source, timeout=30)
        try:
            binary_stream = response
            if source.endswith(".gz"):
                binary_stream = gzip.GzipFile(fileobj=response)
            text_stream = io.TextIOWrapper(binary_stream, encoding="utf-8")
            with text_stream:
                yield text_stream
        finally:
            response.close()
        return

    path = Path(source)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as file:
            yield file
    else:
        with path.open("r", encoding="utf-8") as file:
            yield file


def _iter_json_lines(stream: TextIO) -> Iterator[dict[str, object]]:
    for line_number, line in enumerate(stream, start=1):
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            print(f"Skipping malformed JSON at line {line_number}", file=sys.stderr)
            continue
        if isinstance(value, dict):
            yield value


def _record_to_row(record: dict[str, object], *, phrases_only: bool) -> dict[str, str] | None:
    if str(record.get("lang_code") or "").lower() != "en":
        return None

    term = str(record.get("word") or "").strip()
    if not _is_reasonable_english_term(term):
        return None
    if phrases_only and not any(separator in term for separator in (" ", "-", ".")):
        return None

    translations = _extract_chinese_translations(record)
    if not translations:
        return None

    return {
        "term": term,
        "translation": "；".join(translations[:6]),
        "phonetic": _extract_ipa(record),
        "definition": _extract_definition(record),
        "examples": _extract_example(record),
        "tags": "kaikki",
        "case_sensitive": "false",
    }


def _is_reasonable_english_term(term: str) -> bool:
    return 1 < len(term) <= 80 and TERM_RE.fullmatch(term) is not None


def _extract_chinese_translations(record: dict[str, object]) -> list[str]:
    values: list[str] = []
    for item in _translation_items(record):
        lang_code = str(item.get("lang_code") or item.get("code") or "").lower()
        lang = str(item.get("lang") or "").lower()
        if lang_code not in CHINESE_LANG_CODES and not any(marker in lang for marker in CHINESE_LANG_MARKERS):
            continue

        for value in _as_strings(item.get("word") or item.get("alt")):
            cleaned = _clean_translation(value)
            if cleaned and (CJK_RE.search(cleaned) or lang_code in CHINESE_LANG_CODES):
                values.append(cleaned)

    return _unique(values)


def _translation_items(record: dict[str, object]) -> Iterator[dict[str, object]]:
    for item in _as_dicts(record.get("translations")):
        yield item
    for sense in _as_dicts(record.get("senses")):
        for item in _as_dicts(sense.get("translations")):
            yield item


def _extract_ipa(record: dict[str, object]) -> str:
    for sound in _as_dicts(record.get("sounds")):
        ipa = str(sound.get("ipa") or "").strip().strip("/")
        if ipa:
            return ipa
    return ""


def _extract_definition(record: dict[str, object]) -> str:
    for sense in _as_dicts(record.get("senses")):
        for field in ("glosses", "raw_glosses"):
            for gloss in _as_strings(sense.get(field)):
                cleaned = _clean_plain_text(gloss)
                if cleaned:
                    return cleaned[:240]
    return ""


def _extract_example(record: dict[str, object]) -> str:
    for sense in _as_dicts(record.get("senses")):
        for example in _as_dicts(sense.get("examples")):
            text = _clean_plain_text(str(example.get("text") or ""))
            if 12 <= len(text) <= 180 and re.search(r"[A-Za-z]", text):
                return text
    return ""


def _read_existing_rows(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            term = (row.get("term") or "").strip()
            translation = (row.get("translation") or "").strip()
            if not term or not translation:
                continue
            rows[_normalize_term(term)] = {field: row.get(field, "") or "" for field in FIELDNAMES}
    return rows


def _write_rows(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    sorted_rows = sorted(rows, key=lambda row: _normalize_term(row["term"]))
    with temp_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(sorted_rows)
    temp_path.replace(path)


def _merge_row(rows: dict[str, dict[str, str]], key: str, incoming: dict[str, str]) -> None:
    existing = rows.get(key)
    if existing is None:
        rows[key] = incoming
        return

    existing["translation"] = _merge_text(existing["translation"], incoming["translation"], separator="；", limit=8)
    existing["definition"] = _merge_text(existing["definition"], incoming["definition"], separator=" | ", limit=2)
    existing["examples"] = _merge_text(existing["examples"], incoming["examples"], separator=" | ", limit=2)
    if not existing["phonetic"]:
        existing["phonetic"] = incoming["phonetic"]


def _merge_text(left: str, right: str, *, separator: str, limit: int) -> str:
    values = _unique([*_split_values(left, separator), *_split_values(right, separator)])
    return separator.join(values[:limit])


def _split_values(text: str, separator: str) -> list[str]:
    return [item.strip() for item in text.split(separator) if item.strip()]


def _clean_translation(text: str) -> str:
    text = _clean_plain_text(text)
    return re.sub(r"\s+", "", text)


def _clean_plain_text(text: str) -> str:
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().lower())


def _as_dicts(value: object) -> Iterator[dict[str, object]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _as_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield item


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
