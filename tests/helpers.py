from __future__ import annotations

import sqlite3
from pathlib import Path


def create_sample_bible_sqlite(
    path: Path,
    translation: str = "TST",
    *,
    language: str = "pt-BR",
    books: list[tuple[int, int, int, str]] | None = None,
    verses: list[tuple[int, int, int, int, str]] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    books = books or [
        (1, 1, 1, "Gênesis"),
        (43, 43, 2, "João"),
    ]
    verses = verses or [
        (1, 43, 3, 1, "Havia, entre os fariseus, um homem chamado Nicodemos."),
        (2, 43, 3, 16, "Porque Deus amou ao mundo de tal maneira..."),
        (3, 43, 3, 17, "Deus enviou o Filho para salvar o mundo."),
        (4, 1, 1, 1, "No principio criou Deus os ceus e a terra."),
    ]
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE metadata (key TEXT, value TEXT);
            CREATE TABLE testament (id INTEGER, name TEXT);
            CREATE TABLE book (
                id INTEGER PRIMARY KEY,
                book_reference_id INTEGER,
                testament_reference_id INTEGER,
                name TEXT
            );
            CREATE TABLE verse (
                id INTEGER PRIMARY KEY,
                book_id INTEGER,
                chapter INTEGER,
                verse INTEGER,
                text TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            [("name", translation), ("language", language)],
        )
        conn.executemany(
            "INSERT INTO book (id, book_reference_id, testament_reference_id, name) VALUES (?, ?, ?, ?)",
            books,
        )
        conn.executemany(
            "INSERT INTO verse (id, book_id, chapter, verse, text) VALUES (?, ?, ?, ?, ?)",
            verses,
        )
    return path
