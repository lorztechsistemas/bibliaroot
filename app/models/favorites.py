from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any


class FavoritesStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path("data/user/favorites.db")

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    translation TEXT NOT NULL,
                    book_id INTEGER,
                    book TEXT NOT NULL,
                    chapter INTEGER NOT NULL,
                    verse INTEGER NOT NULL,
                    text TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (translation, book, chapter, verse)
                )
                """
            )
            self._migrate_columns(conn)

    def _migrate_columns(self, conn: sqlite3.Connection) -> None:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(favorites)").fetchall()
        }
        if "book_id" not in cols:
            conn.execute("ALTER TABLE favorites ADD COLUMN book_id INTEGER")
        if "text" not in cols:
            conn.execute("ALTER TABLE favorites ADD COLUMN text TEXT")

    def _connect(self) -> sqlite3.Connection:
        self.init()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(
        self,
        *,
        translation: str,
        book: str,
        chapter: int,
        verse: int,
        text: str | None = None,
        book_id: int | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO favorites
                    (translation, book_id, book, chapter, verse, text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (translation, book_id, book, chapter, verse, text),
            )

    def remove(self, *, translation: str, book: str, chapter: int, verse: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM favorites
                WHERE translation = ? AND book = ? AND chapter = ? AND verse = ?
                """,
                (translation, book, chapter, verse),
            )
            return int(cur.rowcount)

    def is_favorite(self, *, translation: str, book: str, chapter: int, verse: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM favorites
                WHERE translation = ? AND book = ? AND chapter = ? AND verse = ?
                LIMIT 1
                """,
                (translation, book, chapter, verse),
            ).fetchone()
            return row is not None

    def toggle(
        self,
        *,
        translation: str,
        book: str,
        chapter: int,
        verse: int,
        text: str | None = None,
        book_id: int | None = None,
    ) -> bool:
        if self.is_favorite(
            translation=translation, book=book, chapter=chapter, verse=verse
        ):
            self.remove(
                translation=translation, book=book, chapter=chapter, verse=verse
            )
            return False
        self.add(
            translation=translation,
            book=book,
            chapter=chapter,
            verse=verse,
            text=text,
            book_id=book_id,
        )
        return True

    def list_favorites(
        self,
        *,
        translation: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, translation, book_id, book, chapter, verse, text, created_at
            FROM favorites
        """
        params: list[Any] = []
        if translation:
            sql += " WHERE translation = ?"
            params.append(translation)
        sql += " ORDER BY created_at DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    def export_json(self) -> list[dict[str, Any]]:
        return self.list_favorites(limit=None)

    def import_json(self, items: list[dict[str, Any]], *, merge: bool = True) -> int:
        self.init()
        imported = 0
        with self._connect() as conn:
            if not merge:
                conn.execute("DELETE FROM favorites")
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO favorites
                        (translation, book_id, book, chapter, verse, text)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item.get("translation") or ""),
                        item.get("book_id"),
                        str(item.get("book") or ""),
                        int(item.get("chapter") or 0),
                        int(item.get("verse") or 0),
                        item.get("text"),
                    ),
                )
                imported += 1
        return imported
