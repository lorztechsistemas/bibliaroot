from pathlib import Path

from app.services.backend import BibleBackend
from tests.helpers import create_sample_bible_sqlite


def test_backend_initialization_search_and_favorites(tmp_path: Path) -> None:
    bibles_dir = tmp_path / "data" / "bibles"
    create_sample_bible_sqlite(bibles_dir / "TST.sqlite", translation="TST")

    backend = BibleBackend(
        bibles_dir=bibles_dir,
        favorites_db=tmp_path / "data" / "user" / "favorites.db",
        settings_file=tmp_path / "data" / "user" / "settings.json",
        study_db=tmp_path / "data" / "user" / "study.db",
    )
    state = backend.initialize()
    assert state.translation == "TST"
    assert state.translations == ["TST"]

    books = backend.list_books()
    joao = next(b for b in books if b["name"] == "João")

    chapter = backend.open_chapter(book_id=int(joao["id"]), chapter=3)
    assert chapter is not None
    assert chapter["translation"] == "TST"

    results = backend.search("mundo")
    assert len(results) == 2
    assert all(r["is_favorite"] is False for r in results)

    r = results[0]
    added = backend.toggle_favorite(
        translation=r["translation"],
        book=r["book_name"],
        chapter=int(r["chapter"]),
        verse=int(r["verse"]),
        text=r["text"],
        book_id=int(r["book_id"]),
    )
    assert added is True

    results2 = backend.search("mundo")
    assert any(item["is_favorite"] for item in results2)

    favorites = backend.list_favorites()
    assert len(favorites) == 1

    settings = backend.get_settings()
    assert settings.last_book == "João"
    assert settings.last_chapter == 3

    updated = backend.set_daily_content_settings(
        enabled=True,
        mode="study",
        time_str="07:30",
        end_time_str="11:30",
        messages_per_day=3,
        interval_minutes=120,
        persistent_notification=False,
        delivery_mode="popup",
        sound_enabled=True,
    )
    assert updated.daily_content_enabled is True
    assert updated.daily_content_mode == "study"
    assert updated.daily_content_time == "07:30"
    assert updated.daily_content_end_time == "11:30"
    assert updated.daily_messages_per_day == 3
    assert updated.daily_interval_minutes == 120
    assert updated.daily_notification_persistent is False
    assert updated.daily_delivery_mode == "popup"
    assert updated.daily_sound_enabled is True
    assert backend.compute_daily_schedule_times(updated) == ["07:30", "09:30", "11:30"]
    settings2 = backend.set_reading_layout("continuous")
    assert settings2.reading_layout == "continuous"
    settings3 = backend.set_tts_voice_language("pt-br")
    assert settings3.tts_voice_language == "pt-br"
    settings4 = backend.set_tts_engine("piper")
    assert settings4.tts_engine == "piper"
    settings5 = backend.set_tts_engine("auto")
    assert settings5.tts_engine == "auto"


def test_backend_schedule_window_does_not_truncate_to_24(tmp_path: Path) -> None:
    bibles_dir = tmp_path / "data" / "bibles"
    create_sample_bible_sqlite(bibles_dir / "TST.sqlite", translation="TST")
    backend = BibleBackend(
        bibles_dir=bibles_dir,
        favorites_db=tmp_path / "data" / "user" / "favorites.db",
        settings_file=tmp_path / "data" / "user" / "settings.json",
        study_db=tmp_path / "data" / "user" / "study.db",
    )
    backend.initialize()
    settings = backend.set_daily_content_settings(
        enabled=True,
        time_str="08:00",
        end_time_str="10:00",
        interval_minutes=5,
        messages_per_day=25,
    )
    times = backend.compute_daily_schedule_times(settings)
    assert len(times) == 25
    assert times[:3] == ["08:00", "08:05", "08:10"]
    assert times[-1] == "10:00"


def test_backend_translation_catalog_includes_language_metadata(tmp_path: Path) -> None:
    bibles_dir = tmp_path / "data" / "bibles"
    create_sample_bible_sqlite(bibles_dir / "TST.sqlite", translation="TST")
    backend = BibleBackend(
        bibles_dir=bibles_dir,
        favorites_db=tmp_path / "data" / "user" / "favorites.db",
        settings_file=tmp_path / "data" / "user" / "settings.json",
        study_db=tmp_path / "data" / "user" / "study.db",
    )
    backend.initialize()
    # Simula metadata de idioma no banco de teste
    import sqlite3

    with sqlite3.connect(bibles_dir / "TST.sqlite") as conn:
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("language", "en"),
        )
        conn.commit()

    catalog = backend.list_translation_catalog()
    assert catalog[0]["code"] == "TST"
    assert catalog[0]["language"] == "en"
    assert "[en]" in catalog[0]["label"]


def test_backend_finds_translation_for_language_and_switches_book_locale(tmp_path: Path) -> None:
    bibles_dir = tmp_path / "data" / "bibles"
    create_sample_bible_sqlite(
        bibles_dir / "ARA.sqlite",
        translation="ARA",
        language="pt-BR",
        books=[(1, 1, 1, "Gênesis"), (43, 43, 2, "João")],
        verses=[
            (1, 43, 3, 16, "Porque Deus amou ao mundo de tal maneira..."),
            (2, 1, 1, 1, "No princípio criou Deus os céus e a terra."),
        ],
    )
    create_sample_bible_sqlite(
        bibles_dir / "KJV.sqlite",
        translation="KJV",
        language="en",
        books=[(1, 1, 1, "Genesis"), (43, 43, 2, "John")],
        verses=[
            (1, 43, 3, 16, "For God so loved the world..."),
            (2, 1, 1, 1, "In the beginning God created the heaven and the earth."),
        ],
    )
    backend = BibleBackend(
        bibles_dir=bibles_dir,
        favorites_db=tmp_path / "data" / "user" / "favorites.db",
        settings_file=tmp_path / "data" / "user" / "settings.json",
        study_db=tmp_path / "data" / "user" / "study.db",
    )
    state = backend.initialize()
    assert state.translation == "ARA"
    assert backend.find_translation_for_language("en") == "KJV"

    backend.set_translation("KJV")
    books = backend.list_books()
    john = next(book for book in books if int(book["id"]) == 43)
    assert john["name"] == "John"
    chapter = backend.open_chapter(book_id=43, chapter=3)
    assert chapter is not None
    assert chapter["verses"][0]["text"] == "For God so loved the world..."


def test_backend_study_search_filters(tmp_path: Path) -> None:
    bibles_dir = tmp_path / "data" / "bibles"
    create_sample_bible_sqlite(bibles_dir / "TST.sqlite", translation="TST")
    backend = BibleBackend(
        bibles_dir=bibles_dir,
        favorites_db=tmp_path / "data" / "user" / "favorites.db",
        settings_file=tmp_path / "data" / "user" / "settings.json",
        study_db=tmp_path / "data" / "user" / "study.db",
    )
    backend.initialize()

    # phrase mode
    phrase = backend.search_study("Deus amou", match_mode="phrase")
    assert len(phrase) == 1
    assert phrase[0]["book_name"] == "João"

    # any terms mode
    any_terms = backend.search_study("Nicodemos mundo", match_mode="any_terms")
    assert len(any_terms) >= 2

    # all terms mode
    all_terms = backend.search_study("Deus mundo", match_mode="all_terms")
    assert len(all_terms) >= 1
    assert all("Deus" in row["text"] or "Deus".lower() in row["text"].lower() for row in all_terms)

    # testament filter (sample helper: João is NT / testament_reference_id 2)
    nt_only = backend.search_study("mundo", testament_id=2)
    assert len(nt_only) == 2
    ot_only = backend.search_study("mundo", testament_id=1)
    assert ot_only == []
