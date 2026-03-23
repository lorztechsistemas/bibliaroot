from pathlib import Path

from app.models.bible_db import BibleDB
from tests.helpers import create_sample_bible_sqlite


def test_bible_db_search_and_navigation(tmp_path: Path) -> None:
    bibles_dir = tmp_path / "bibles"
    create_sample_bible_sqlite(bibles_dir / "TST.sqlite", translation="TST")

    db = BibleDB(data_dir=bibles_dir)
    db.set_translation("TST")

    metadata = db.get_metadata()
    assert metadata["name"] == "TST"

    joao = db.find_book("Joao")
    assert joao is not None
    assert joao["name"] == "João"

    chapter = db.get_chapter(int(joao["id"]), 3)
    assert chapter is not None
    assert chapter["chapter"] == 3
    assert len(chapter["verses"]) == 3

    results = db.search("amou", limit=10)
    assert len(results) == 1
    assert results[0]["verse"] == 16
