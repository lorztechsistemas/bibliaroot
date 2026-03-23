from pathlib import Path

import pytest

from app.models.bible_db import BibleDB


def test_bible_db_reads_real_sqlite_when_present() -> None:
    data_dir = Path("data/bibles")
    if not (data_dir / "ARA.sqlite").exists():
        pytest.skip("ARA.sqlite nao encontrado em data/bibles")

    db = BibleDB(data_dir=data_dir)
    db.set_translation("ARA")

    books = db.get_books()
    assert len(books) >= 66

    joao = next((b for b in books if b["name"] == "João"), None)
    assert joao is not None

    chapter_count = db.get_chapter_count(int(joao["id"]))
    assert chapter_count >= 21

    verses = db.get_verses(int(joao["id"]), 3)
    assert len(verses) >= 16
    assert any(int(v["verse"]) == 16 for v in verses)
