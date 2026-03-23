from pathlib import Path

from scripts.setup_db import ensure_dirs, write_user_seed_files


def test_setup_creates_directories_and_seed_files(tmp_path: Path) -> None:
    bibles_dir, user_dir = ensure_dirs(tmp_path)
    write_user_seed_files(user_dir)

    assert bibles_dir.exists()
    assert user_dir.exists()
    assert (user_dir / "favorites.db").exists()
    assert (user_dir / "settings.json").exists()
