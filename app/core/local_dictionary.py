from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CSV_PATH = DATA_DIR / "ecdict.csv"
DB_PATH = DATA_DIR / "ecdict.sqlite"


@dataclass(slots=True, frozen=True)
class DictionaryEntry:
    word: str
    phonetic: str
    translation: str
    definition: str


class LocalDictionary:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    @property
    def is_available(self) -> bool:
        return self._db_path.exists()

    def lookup(self, word: str) -> DictionaryEntry | None:
        normalized = word.strip().lower()
        if not normalized or not self._db_path.exists():
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
