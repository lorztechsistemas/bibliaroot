from pathlib import Path

from app.models.favorites import FavoritesStore


def test_favorites_add_toggle_and_list(tmp_path: Path) -> None:
    store = FavoritesStore(tmp_path / "favorites.db")
    store.init()

    store.add(
        translation="ARA",
        book="João",
        chapter=3,
        verse=16,
        text="Porque Deus amou...",
        book_id=43,
    )
    assert store.is_favorite(translation="ARA", book="João", chapter=3, verse=16)

    items = store.list_favorites()
    assert len(items) == 1
    assert items[0]["book"] == "João"
    assert items[0]["book_id"] == 43

    added = store.toggle(
        translation="ARA", book="João", chapter=3, verse=17, text="Outro", book_id=43
    )
    assert added is True
    removed = store.toggle(
        translation="ARA", book="João", chapter=3, verse=17, text="Outro", book_id=43
    )
    assert removed is False
