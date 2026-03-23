from pathlib import Path

from app.models.settings import SettingsStore, UserSettings


def test_settings_roundtrip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    data = UserSettings(translation="NVI", font_scale=1.2, last_book="Romanos", last_chapter=8)
    store.save(data)

    loaded = store.load()
    assert loaded.translation == "NVI"
    assert loaded.last_chapter == 8


def test_record_reading_updates_history(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.record_reading(translation="ARA", book="João", chapter=3, book_id=43)
    store.record_reading(translation="ARA", book="Romanos", chapter=8, book_id=45)
    store.record_reading(translation="ARA", book="João", chapter=3, book_id=43)

    settings = store.load()
    assert settings.last_book == "João"
    assert settings.last_chapter == 3
    assert len(settings.reading_history) == 2
    assert settings.reading_history[0]["book"] == "João"
