from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CSV_PATH = DATA_DIR / "ecdict.csv"
DB_PATH = DATA_DIR / "ecdict.sqlite"
BUILTIN_TERMS_PATH = DATA_DIR / "tech_academic_terms.csv"
USER_TERMS_PATH = DATA_DIR / "user_terms.csv"


@dataclass(slots=True, frozen=True)
class DictionaryEntry:
    word: str
    phonetic: str
    translation: str
    definition: str
    source: str = "ecdict"
    examples: tuple[str, ...] = ()
    tags: str = ""


class LocalDictionary:
    def __init__(
        self,
        db_path: Path = DB_PATH,
        builtin_terms_path: Path = BUILTIN_TERMS_PATH,
        user_terms_path: Path = USER_TERMS_PATH,
    ) -> None:
        self._db_path = db_path
        self._builtin_terms_path = builtin_terms_path
        self._user_terms_path = user_terms_path
        self._term_cache_signature: tuple[tuple[str, int, int], ...] | None = None
        self._terms_exact: dict[str, DictionaryEntry] = {}
        self._terms_folded: dict[str, DictionaryEntry] = {}

    @property
    def is_available(self) -> bool:
        return self._db_path.exists() or self._builtin_terms_path.exists() or self._user_terms_path.exists()

    def lookup(self, word: str) -> DictionaryEntry | None:
        normalized = _normalize_term(word)
        if not normalized:
            return None

        term_entry = self._lookup_term_file(word)
        if term_entry is not None:
            return term_entry

        if not self._db_path.exists():
            return None

        with sqlite3.connect(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT word, phonetic, translation, definition
                FROM entries
                WHERE word = ?
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()

        if row is None:
            return None
        return DictionaryEntry(
            word=row[0],
            phonetic=row[1] or "",
            translation=row[2] or "",
            definition=row[3] or "",
        )

    def lookup_terms_in_text(self, text: str, *, max_terms: int = 12) -> list[DictionaryEntry]:
        normalized_text = f" {_normalize_term(text)} "
        if not normalized_text.strip():
            return []

        self._refresh_term_cache()
        matches: list[DictionaryEntry] = []
        seen: set[str] = set()
        terms = sorted(
            self._terms_folded.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )

        for normalized_term, entry in terms:
            if entry.word.lower() in seen:
                continue
            if f" {normalized_term} " in normalized_text:
                matches.append(entry)
                seen.add(entry.word.lower())
            if len(matches) >= max_terms:
                break
        return matches

    def add_user_term(
        self,
        term: str,
        translation: str,
        *,
        phonetic: str = "",
        definition: str = "",
        examples: Iterable[str] = (),
        tags: str = "custom",
        case_sensitive: bool = False,
    ) -> None:
        term = term.strip()
        translation = translation.strip()
        if not term or not translation:
            raise ValueError("Both term and translation are required.")

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        file_exists = self._user_terms_path.exists()
        with self._user_terms_path.open("a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=_TERM_FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "term": term,
                    "translation": translation,
                    "phonetic": phonetic,
                    "definition": definition,
                    "examples": " | ".join(example.strip() for example in examples if example.strip()),
                    "tags": tags,
                    "case_sensitive": "true" if case_sensitive else "false",
                }
            )
        self._term_cache_signature = None

    def ensure_user_terms_file(self) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self._user_terms_path.exists():
            with self._user_terms_path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=_TERM_FIELDNAMES)
                writer.writeheader()
        return self._user_terms_path

    def _lookup_term_file(self, raw_term: str) -> DictionaryEntry | None:
        self._refresh_term_cache()
        stripped = raw_term.strip()
        return self._terms_exact.get(stripped) or self._terms_folded.get(_normalize_term(stripped))

    def _refresh_term_cache(self) -> None:
        signature = _term_file_signature((self._user_terms_path, self._builtin_terms_path))
        if signature == self._term_cache_signature:
            return

        exact: dict[str, DictionaryEntry] = {}
        folded: dict[str, DictionaryEntry] = {}
        for path, source in (
            (self._builtin_terms_path, "builtin-terms"),
            (self._user_terms_path, "user-terms"),
        ):
            for entry, case_sensitive in _read_term_entries(path, source):
                if case_sensitive:
                    exact[entry.word] = entry
                else:
                    folded[_normalize_term(entry.word)] = entry

        self._terms_exact = exact
        self._terms_folded = folded
        self._term_cache_signature = signature


def build_dictionary(
    csv_path: Path = CSV_PATH,
    db_path: Path = DB_PATH,
    *,
    force: bool = False,
) -> Path:
    if db_path.exists() and not force:
        return db_path
    if not csv_path.exists():
        raise FileNotFoundError(f"Dictionary CSV not found: {csv_path}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = db_path.with_suffix(".sqlite.tmp")
    if temp_path.exists():
        temp_path.unlink()

    connection = sqlite3.connect(temp_path)
    try:
        connection.execute(
            """
            CREATE TABLE entries (
                word TEXT PRIMARY KEY,
                phonetic TEXT,
                translation TEXT,
                definition TEXT
            )
            """
        )

        with csv_path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            batch = []
            for row in reader:
                word = (row.get("word") or "").strip().lower()
                if not word:
                    continue
                batch.append(
                    (
                        word,
                        (row.get("phonetic") or "").strip(),
                        _compact_text(row.get("translation") or ""),
                        _compact_text(row.get("definition") or ""),
                    )
                )
                if len(batch) >= 5000:
                    _insert_batch(connection, batch)
                    batch.clear()
            if batch:
                _insert_batch(connection, batch)

        connection.execute("CREATE INDEX idx_entries_word ON entries(word)")
        connection.commit()
    finally:
        connection.close()

    temp_path.replace(db_path)
    return db_path


def _insert_batch(connection: sqlite3.Connection, batch: list[tuple[str, str, str, str]]) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO entries (word, phonetic, translation, definition)
        VALUES (?, ?, ?, ?)
        """,
        batch,
    )


def _compact_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\\n", "\n").splitlines()]
    return "\n".join(line for line in lines if line)


_TERM_FIELDNAMES = (
    "term",
    "translation",
    "phonetic",
    "definition",
    "examples",
    "tags",
    "case_sensitive",
)


def _normalize_term(text: str | None) -> str:
    if not text:
        return ""
    normalized = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2013", "-")
    normalized = re.sub(r"[^0-9A-Za-z'\-]+", " ", normalized)
    return " ".join(normalized.strip().lower().split())


def _term_file_signature(paths: Iterable[Path]) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            signature.append((str(path), 0, 0))
            continue
        signature.append((str(path), int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(signature)


def _read_term_entries(path: Path, source: str) -> Iterable[tuple[DictionaryEntry, bool]]:
    if not path.exists():
        return

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            term = (row.get("term") or "").strip()
            translation = _compact_text(row.get("translation") or "")
            if not term or not translation:
                continue
            examples = tuple(
                item.strip()
                for item in (row.get("examples") or "").replace("；", "|").split("|")
                if item.strip()
            )
            entry = DictionaryEntry(
                word=term,
                phonetic=(row.get("phonetic") or "").strip(),
                translation=translation,
                definition=_compact_text(row.get("definition") or ""),
                source=source,
                examples=examples,
                tags=(row.get("tags") or "").strip(),
            )
            case_sensitive = (row.get("case_sensitive") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            yield entry, case_sensitive
