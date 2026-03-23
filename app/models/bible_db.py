from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any
import unicodedata


class BibleDB:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path("data/bibles")
        self.translation = "ARA"

    def set_translation(self, translation: str) -> None:
        self.translation = translation

    def available_translations(self) -> list[str]:
        if not self.data_dir.exists():
            return []
        return sorted(p.stem for p in self.data_dir.glob("*.sqlite"))

    def get_database_path(self) -> Path:
        return self.data_dir / f"{self.translation}.sqlite"

    def connect(self) -> sqlite3.Connection:
        db_path = self.get_database_path()
        if not db_path.exists():
            raise FileNotFoundError(
                f"Banco nao encontrado: {db_path}. Rode scripts/setup_db.py primeiro."
            )
        return sqlite3.connect(db_path)

    @staticmethod
    def _normalize_book_name(value: str) -> str:
        normalized = unicodedata.normalize("NFD", value)
        without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return without_marks.casefold().strip()

    def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(query, params).fetchall()

    def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(query, params).fetchone()

    def get_books(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT id, name, testament_reference_id
            FROM book
            ORDER BY id
            """
        )
        return [dict(row) for row in rows]

    def get_metadata(self) -> dict[str, str]:
        rows = self._fetchall("SELECT key, value FROM metadata")
        return {str(row["key"]): str(row["value"]) for row in rows}

    def get_translation_metadata(self, translation: str) -> dict[str, str]:
        previous = self.translation
        self.set_translation(translation)
        try:
            return self.get_metadata()
        finally:
            self.set_translation(previous)

    def get_book(self, book_id: int) -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT id, name, testament_reference_id
            FROM book
            WHERE id = ?
            """,
            (book_id,),
        )
        return dict(row) if row else None

    def find_book(self, name_or_id: str | int) -> dict[str, Any] | None:
        if isinstance(name_or_id, int) or str(name_or_id).isdigit():
            return self.get_book(int(name_or_id))

        target = self._normalize_book_name(str(name_or_id))
        for book in self.get_books():
            if self._normalize_book_name(str(book["name"])) == target:
                return book
        return None

    def get_chapter_count(self, book_id: int) -> int:
        row = self._fetchone(
            """
            SELECT MAX(chapter) AS max_chapter
            FROM verse
            WHERE book_id = ?
            """,
            (book_id,),
        )
        if row is None or row["max_chapter"] is None:
            return 0
        return int(row["max_chapter"])

    def get_verses(self, book_id: int, chapter: int) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT verse, text
            FROM verse
            WHERE book_id = ? AND chapter = ?
            ORDER BY verse
            """,
            (book_id, chapter),
        )
        return [dict(row) for row in rows]

    def get_verse(self, book_id: int, chapter: int, verse: int) -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT b.id AS book_id, b.name AS book_name, v.chapter, v.verse, v.text
            FROM verse v
            JOIN book b ON b.id = v.book_id
            WHERE v.book_id = ? AND v.chapter = ? AND v.verse = ?
            """,
            (book_id, chapter, verse),
        )
        return dict(row) if row else None

    def search(
        self,
        query: str,
        *,
        limit: int = 100,
        translation: str | None = None,
        book_id: int | None = None,
        testament_id: int | None = None,
        match_mode: str = "phrase",
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        previous_translation = self.translation
        if translation:
            self.set_translation(translation)

        sql = """
            SELECT
                b.id AS book_id,
                b.name AS book_name,
                b.testament_reference_id,
                v.chapter,
                v.verse,
                v.text
            FROM verse v
            JOIN book b ON b.id = v.book_id
            WHERE 1=1
        """
        params: list[Any] = []
        mode = (match_mode or "phrase").strip().lower()
        if mode == "all_terms":
            terms = [t for t in query.split() if t.strip()]
            if not terms:
                return []
            for term in terms:
                sql += " AND lower(v.text) LIKE lower(?)"
                params.append(f"%{term}%")
        elif mode == "any_terms":
            terms = [t for t in query.split() if t.strip()]
            if not terms:
                return []
            sql += " AND (" + " OR ".join(["lower(v.text) LIKE lower(?)"] * len(terms)) + ")"
            params.extend([f"%{term}%" for term in terms])
        else:
            sql += " AND lower(v.text) LIKE lower(?)"
            params.append(f"%{query}%")
        if book_id is not None:
            sql += " AND b.id = ?"
            params.append(book_id)
        if testament_id is not None:
            sql += " AND b.testament_reference_id = ?"
            params.append(testament_id)
        sql += " ORDER BY b.id, v.chapter, v.verse LIMIT ?"
        params.append(max(1, int(limit)))

        try:
            rows = self._fetchall(sql, tuple(params))
            return [dict(row) for row in rows]
        finally:
            if translation:
                self.set_translation(previous_translation)

    def get_chapter(
        self, book_id: int, chapter: int
    ) -> dict[str, Any] | None:
        book = self.get_book(book_id)
        if not book:
            return None
        verses = self.get_verses(book_id, chapter)
        if not verses:
            return None
        return {
            "translation": self.translation,
            "book": book,
            "chapter": int(chapter),
            "chapter_count": self.get_chapter_count(book_id),
            "verses": verses,
        }

    def get_verse_count(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS total FROM verse")
        if row is None or row["total"] is None:
            return 0
        return int(row["total"])

    def get_verse_by_global_index(self, index: int) -> dict[str, Any] | None:
        total = self.get_verse_count()
        if total <= 0:
            return None
        normalized_index = int(index) % total
        row = self._fetchone(
            """
            SELECT
                b.id AS book_id,
                b.name AS book_name,
                v.chapter,
                v.verse,
                v.text
            FROM verse v
            JOIN book b ON b.id = v.book_id
            ORDER BY b.id, v.chapter, v.verse
            LIMIT 1 OFFSET ?
            """,
            (normalized_index,),
        )
        return dict(row) if row else None
