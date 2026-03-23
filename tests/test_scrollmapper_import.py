from __future__ import annotations

from pathlib import Path
import sqlite3

from app.models.bible_db import BibleDB
from scripts.import_scrollmapper_sqlite import export_many, list_translations


def _build_scrollmapper_fixture(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE translations (
                translation TEXT PRIMARY KEY,
                title TEXT,
                license TEXT,
                language TEXT
            );
            CREATE TABLE TST_books (
                id INTEGER PRIMARY KEY,
                name TEXT
            );
            CREATE TABLE TST_verses (
                book_id INTEGER,
                chapter INTEGER,
                verse INTEGER,
                text TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO translations (translation, title, license, language) VALUES (?, ?, ?, ?)",
            ("TST", "Test Translation", "CC-BY", "en"),
        )
        conn.executemany(
            "INSERT INTO TST_books (id, name) VALUES (?, ?)",
            [(1, "Genesis"), (2, "Exodus")],
        )
        conn.executemany(
            "INSERT INTO TST_verses (book_id, chapter, verse, text) VALUES (?, ?, ?, ?)",
            [
                (1, 1, 1, "In the beginning"),
                (1, 1, 2, "The earth was formless"),
                (2, 1, 1, "These are the names"),
            ],
        )
        conn.commit()


def test_scrollmapper_import_exports_bibliaapp_sqlite(tmp_path: Path) -> None:
    source = tmp_path / "scrollmapper.sqlite"
    out_dir = tmp_path / "bibles"
    _build_scrollmapper_fixture(source)

    catalog = list_translations(source)
    assert len(catalog) == 1
    assert catalog[0].code == "TST"
    assert catalog[0].language == "en"

    outputs = export_many(source, out_dir, ["TST"])
    assert len(outputs) == 1
    assert outputs[0].name == "TST.sqlite"

    db = BibleDB(data_dir=out_dir)
    db.set_translation("TST")
    payload = db.get_chapter(1, 1)
    assert payload is not None
    assert payload["book"]["name"] == "Genesis"
    assert len(payload["verses"]) == 2

    meta = db.get_metadata()
    assert meta["translation"] == "TST"
    assert meta["name"] == "Test Translation"
    assert meta["language"] == "en"
    assert meta["source"] == "scrollmapper"
