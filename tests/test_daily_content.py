from datetime import date
from pathlib import Path

from app.models.bible_db import BibleDB
from app.services.daily_content import DailyContentService
from tests.helpers import create_sample_bible_sqlite


def test_daily_content_generates_modes(tmp_path: Path) -> None:
    bibles_dir = tmp_path / "bibles"
    create_sample_bible_sqlite(bibles_dir / "TST.sqlite", translation="TST")
    db = BibleDB(data_dir=bibles_dir)
    db.set_translation("TST")
    service = DailyContentService(db)

    verse = service.generate(mode="verse", on_date=date(2026, 2, 26))
    study = service.generate(mode="study", on_date=date(2026, 2, 26))
    outline = service.generate(mode="outline", on_date=date(2026, 2, 26))

    assert verse.reference
    assert "Reflexão:" in study.body
    assert "Pontos:" in outline.body
