from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterable
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.study import StudyStore


@dataclass
class CrossRefRow:
    source_book_id: int
    source_chapter: int
    source_verse: int
    target_book_id: int
    target_chapter: int
    target_verse: int
    weight: float = 1.0
    source_label: str = ""
    target_label: str = ""


BOOK_NAME_TO_ID = {
    "genesis": 1, "exodus": 2, "leviticus": 3, "numbers": 4, "deuteronomy": 5,
    "joshua": 6, "judges": 7, "ruth": 8, "1 samuel": 9, "2 samuel": 10,
    "1 kings": 11, "2 kings": 12, "1 chronicles": 13, "2 chronicles": 14,
    "ezra": 15, "nehemiah": 16, "esther": 17, "job": 18, "psalm": 19, "psalms": 19,
    "proverbs": 20, "ecclesiastes": 21, "song of songs": 22, "song of solomon": 22,
    "songs": 22, "isaiah": 23, "jeremiah": 24, "lamentations": 25, "ezekiel": 26,
    "daniel": 27, "hosea": 28, "joel": 29, "amos": 30, "obadiah": 31, "jonah": 32,
    "micah": 33, "nahum": 34, "habakkuk": 35, "zephaniah": 36, "haggai": 37,
    "zechariah": 38, "malachi": 39, "matthew": 40, "mark": 41, "luke": 42, "john": 43,
    "acts": 44, "romans": 45, "1 corinthians": 46, "2 corinthians": 47, "galatians": 48,
    "ephesians": 49, "philippians": 50, "colossians": 51, "1 thessalonians": 52,
    "2 thessalonians": 53, "1 timothy": 54, "2 timothy": 55, "titus": 56, "philemon": 57,
    "hebrews": 58, "james": 59, "1 peter": 60, "2 peter": 61, "1 john": 62, "2 john": 63,
    "3 john": 64, "jude": 65, "revelation": 66, "revelations": 66,
}


def _norm_book_name(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def _book_to_id(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return BOOK_NAME_TO_ID.get(_norm_book_name(text))


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]).lower() for r in rows}


def _pick_columns(cols: set[str]) -> dict[str, str] | None:
    aliases = {
        "source_book_id": ["source_book_id", "book_id", "from_book_id", "src_book", "book", "from_book"],
        "source_chapter": ["source_chapter", "chapter", "from_chapter", "src_chapter"],
        "source_verse": ["source_verse", "verse", "from_verse", "src_verse"],
        "target_book_id": ["target_book_id", "xref_book_id", "to_book_id", "ref_book_id", "to_book"],
        "target_chapter": ["target_chapter", "xref_chapter", "to_chapter", "ref_chapter"],
        "target_verse": ["target_verse", "xref_verse", "to_verse", "ref_verse", "to_verse_start"],
        "target_verse_end": ["target_verse_end", "to_verse_end"],
        "weight": ["weight", "votes", "score", "rank"],
    }
    out: dict[str, str] = {}
    for key, names in aliases.items():
        for name in names:
            if name in cols:
                out[key] = name
                break
    required = [
        "source_book_id",
        "source_chapter",
        "source_verse",
        "target_book_id",
        "target_chapter",
        "target_verse",
    ]
    if not all(key in out for key in required):
        return None
    return out


def _candidate_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(r[0]) for r in rows]


def iter_crossrefs(source_db: Path, table: str | None = None) -> Iterable[CrossRefRow]:
    with sqlite3.connect(source_db) as conn:
        tables = [table] if table else _candidate_tables(conn)
        for t in tables:
            cols = _table_columns(conn, t)
            mapping = _pick_columns(cols)
            if not mapping:
                continue
            select_cols = [
                f'{mapping["source_book_id"]} AS source_book_id',
                f'{mapping["source_chapter"]} AS source_chapter',
                f'{mapping["source_verse"]} AS source_verse',
                f'{mapping["target_book_id"]} AS target_book_id',
                f'{mapping["target_chapter"]} AS target_chapter',
                f'{mapping["target_verse"]} AS target_verse',
            ]
            if "target_verse_end" in mapping:
                select_cols.append(f'{mapping["target_verse_end"]} AS target_verse_end')
            else:
                select_cols.append("NULL AS target_verse_end")
            if "weight" in mapping:
                select_cols.append(f'{mapping["weight"]} AS weight')
            else:
                select_cols.append("1.0 AS weight")
            rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM {t}")
            count = 0
            for row in rows:
                count += 1
                source_book_id = _book_to_id(row[0])
                target_book_id = _book_to_id(row[3])
                if source_book_id is None or target_book_id is None:
                    continue
                target_verse_end = row[6]
                target_verse_start = int(row[5])
                target_label = ""
                if target_verse_end is not None and int(target_verse_end) != target_verse_start:
                    target_label = f'{target_book_id}:{int(row[4])}:{target_verse_start}-{int(target_verse_end)}'
                yield CrossRefRow(
                    source_book_id=int(source_book_id),
                    source_chapter=int(row[1]),
                    source_verse=int(row[2]),
                    target_book_id=int(target_book_id),
                    target_chapter=int(row[4]),
                    target_verse=target_verse_start,
                    weight=float(row[7] if row[7] is not None else 1.0),
                    target_label=target_label,
                )
            if count > 0:
                return
    raise ValueError("Nenhuma tabela compatível de referências cruzadas encontrada no SQLite de origem.")


def _iter_source_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    if source.is_dir():
        files = sorted(source.glob("cross_references_*.db"))
        if files:
            return files
        files = sorted(source.glob("*.db"))
        if files:
            return files
    raise FileNotFoundError(f"Origem de referências cruzadas não encontrada ou sem .db: {source}")


def import_crossrefs(
    source_db: Path,
    *,
    study_db: Path,
    table: str | None = None,
    limit: int | None = None,
) -> int:
    store = StudyStore(db_path=study_db)
    store.init()
    imported = 0
    for file in _iter_source_files(source_db):
        for ref in iter_crossrefs(file, table=table):
            store.add_cross_reference(
                source_book_id=ref.source_book_id,
                source_chapter=ref.source_chapter,
                source_verse=ref.source_verse,
                target_book_id=ref.target_book_id,
                target_chapter=ref.target_chapter,
                target_verse=ref.target_verse,
                weight=ref.weight,
                source_label=ref.source_label,
                target_label=ref.target_label,
            )
            imported += 1
            if limit is not None and imported >= int(limit):
                return imported
    return imported


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importa referências cruzadas (SQLite) para o study.db do BíbliaRoot."
    )
    parser.add_argument("--source", required=True, help="SQLite de origem ou pasta com cross_references_*.db")
    parser.add_argument("--study-db", default="data/user/study.db", help="Caminho do study.db destino")
    parser.add_argument("--table", help="Nome da tabela (opcional; tenta autodetectar)")
    parser.add_argument("--limit", type=int, help="Importa apenas N linhas (teste)")
    args = parser.parse_args()

    count = import_crossrefs(
        Path(args.source),
        study_db=Path(args.study_db),
        table=args.table,
        limit=args.limit,
    )
    print(f"Referências cruzadas importadas: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
