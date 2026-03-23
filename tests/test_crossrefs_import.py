from pathlib import Path
import sqlite3

from app.models.study import StudyStore
from scripts.import_scrollmapper_crossrefs import import_crossrefs


def _build_crossrefs_fixture(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE cross_references (
                id INTEGER PRIMARY KEY,
                book_id INTEGER,
                chapter INTEGER,
                verse INTEGER,
                xref_book_id INTEGER,
                xref_chapter INTEGER,
                xref_verse INTEGER,
                votes REAL
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO cross_references (
                book_id, chapter, verse, xref_book_id, xref_chapter, xref_verse, votes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (43, 3, 16, 1, 1, 1, 0.9),
                (43, 3, 16, 45, 5, 8, 0.7),
            ],
        )
        conn.commit()


def test_import_crossrefs_into_study_db(tmp_path: Path) -> None:
    source = tmp_path / "crossrefs.sqlite"
    study_db = tmp_path / "study.db"
    _build_crossrefs_fixture(source)

    count = import_crossrefs(source, study_db=study_db)
    assert count == 2

    store = StudyStore(db_path=study_db)
    refs = store.list_cross_references(source_book_id=43, source_chapter=3, source_verse=16, limit=10)
    assert len(refs) == 2
    assert refs[0]["weight"] >= refs[1]["weight"]


def test_import_crossrefs_scrollmapper_real_shape_with_book_names(tmp_path: Path) -> None:
    source = tmp_path / "crossrefs_scrollmapper.db"
    study_db = tmp_path / "study.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(
            """
            CREATE TABLE cross_references (
                id INTEGER PRIMARY KEY,
                from_book TEXT,
                from_chapter INTEGER,
                from_verse INTEGER,
                to_book TEXT,
                to_chapter INTEGER,
                to_verse_start INTEGER,
                to_verse_end INTEGER,
                votes INTEGER
            );
            """
        )
        conn.execute(
            """
            INSERT INTO cross_references
            (from_book, from_chapter, from_verse, to_book, to_chapter, to_verse_start, to_verse_end, votes)
            VALUES ('Genesis', 1, 1, 'John', 1, 1, 3, 42)
            """
        )
        conn.commit()

    count = import_crossrefs(source, study_db=study_db)
    assert count == 1
    store = StudyStore(db_path=study_db)
    refs = store.list_cross_references(source_book_id=1, source_chapter=1, source_verse=1, limit=10)
    assert len(refs) == 1
    assert refs[0]["target_book_id"] == 43
    assert refs[0]["target_verse"] == 1
