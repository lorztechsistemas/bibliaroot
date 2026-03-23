from pathlib import Path

from app.services.backend import BibleBackend
from tests.helpers import create_sample_bible_sqlite


def _backend(tmp_path: Path) -> BibleBackend:
    bibles_dir = tmp_path / "data" / "bibles"
    create_sample_bible_sqlite(bibles_dir / "TST.sqlite", translation="TST")
    create_sample_bible_sqlite(bibles_dir / "ALT.sqlite", translation="ALT")
    backend = BibleBackend(
        bibles_dir=bibles_dir,
        favorites_db=tmp_path / "data" / "user" / "favorites.db",
        settings_file=tmp_path / "data" / "user" / "settings.json",
        study_db=tmp_path / "data" / "user" / "study.db",
    )
    backend.initialize()
    backend.set_translation("TST")
    return backend


def test_notes_notebooks_and_plans(tmp_path: Path) -> None:
    backend = _backend(tmp_path)

    note = backend.save_study_note(
        translation="TST",
        book_id=43,
        book="João",
        chapter=3,
        verse=16,
        note_text="Texto-chave para evangelismo.",
        highlight_color="yellow",
        tags=["evangelismo", "amor"],
    )
    assert note["chapter"] == 3
    assert note["highlight_color"] == "yellow"
    assert "amor" in note["tags"]

    fetched = backend.get_study_note(translation="TST", book="João", chapter=3, verse=16)
    assert fetched is not None
    assert fetched["note_text"] == "Texto-chave para evangelismo."

    notes = backend.list_study_notes(tag="amor")
    assert len(notes) == 1

    notebook = backend.create_notebook(name="Culto Domingo", description="Mensagens e referências")
    backend.add_notebook_entry(
        notebook_id=int(notebook["id"]),
        translation="TST",
        book_id=43,
        book="João",
        chapter=3,
        verse=16,
        note_text="Usar na introdução.",
    )
    notebooks = backend.list_notebooks()
    assert notebooks and notebooks[0]["entry_count"] >= 1
    entries = backend.list_notebook_entries(notebook_id=int(notebook["id"]))
    assert entries[0]["verse"] == 16

    plans = backend.list_reading_plans()
    assert any(p["slug"] == "gospels-30d" for p in plans)
    backend.set_plan_day_completed(plan_slug="gospels-30d", day_index=1, completed=True)
    assert backend.list_plan_progress(plan_slug="gospels-30d") == [1]


def test_cross_references_and_compare(tmp_path: Path) -> None:
    backend = _backend(tmp_path)

    backend.add_cross_reference(
        source_book_id=43,
        source_chapter=3,
        source_verse=16,
        target_book_id=1,
        target_chapter=1,
        target_verse=1,
        weight=0.8,
    )
    refs = backend.list_cross_references(book_id=43, chapter=3, verse=16)
    assert len(refs) == 1
    assert refs[0]["target_book_id"] == 1
    assert refs[0]["target_text"]

    compared = backend.compare_verse(
        book_id=43,
        chapter=3,
        verse=16,
        translations=["TST", "ALT"],
    )
    assert [item["translation"] for item in compared] == ["TST", "ALT"]
    assert all(int(item["verse"]) == 16 for item in compared)


def test_export_and_import_study_data(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    notebook = backend.create_notebook(name="Backup Teste")
    backend.save_study_note(
        translation="TST",
        book_id=43,
        book="João",
        chapter=3,
        verse=16,
        note_text="Nota exportável",
        tags=["backup"],
    )
    backend.add_notebook_entry(
        notebook_id=int(notebook["id"]),
        translation="TST",
        book_id=43,
        book="João",
        chapter=3,
        verse=16,
        note_text="Entrada exportável",
    )
    backend.add_cross_reference(
        source_book_id=43,
        source_chapter=3,
        source_verse=16,
        target_book_id=1,
        target_chapter=1,
        target_verse=1,
    )
    export_path = tmp_path / "backup.json"
    backend.export_study_data(export_path)
    assert export_path.exists()

    backend2 = _backend(tmp_path / "other")
    counts = backend2.import_study_data(export_path, merge=True)
    assert counts["notes"] >= 1
    assert counts["notebook_entries"] >= 1
    assert backend2.count_cross_references() >= 1


def test_recent_notebook_entries_and_delete(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    notebook = backend.create_notebook(name="Recentes")
    entry = backend.add_notebook_entry(
        notebook_id=int(notebook["id"]),
        translation="TST",
        book_id=43,
        book="João",
        chapter=3,
        verse=16,
        note_text="Entrada para lista recente",
    )
    recents = backend.list_recent_notebook_entries(limit=10)
    assert recents
    assert recents[0]["id"] == entry["id"]
    removed = backend.delete_notebook_entry(entry_id=int(entry["id"]))
    assert removed == 1


def test_full_backup_export_import(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    backend.set_theme_mode("dark")
    backend.toggle_favorite(
        translation="TST",
        book="João",
        chapter=3,
        verse=16,
        text="Porque Deus amou...",
        book_id=43,
    )
    backend.save_study_note(
        translation="TST",
        book_id=43,
        book="João",
        chapter=3,
        verse=16,
        note_text="Nota completa",
        tags=["full-backup"],
    )
    backup = tmp_path / "full-backup.json"
    backend.export_full_backup(backup)
    assert backup.exists()

    backend2 = _backend(tmp_path / "restored")
    result = backend2.import_full_backup(backup, merge=True)
    assert result["settings"] is True
    assert result["favorites"] >= 1
    assert int(result["study"]["notes"]) >= 1
    assert backend2.get_settings().theme_mode == "dark"
    assert len(backend2.list_favorites()) >= 1
