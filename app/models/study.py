from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class StudyStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path("data/user/study.db")

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    translation TEXT NOT NULL,
                    book_id INTEGER,
                    book TEXT NOT NULL,
                    chapter INTEGER NOT NULL,
                    verse INTEGER NOT NULL,
                    note_text TEXT NOT NULL DEFAULT '',
                    highlight_color TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (translation, book, chapter, verse)
                );

                CREATE TABLE IF NOT EXISTS notebooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS notebook_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notebook_id INTEGER NOT NULL,
                    translation TEXT NOT NULL,
                    book_id INTEGER,
                    book TEXT NOT NULL,
                    chapter INTEGER NOT NULL,
                    verse INTEGER NOT NULL,
                    note_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reading_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    days_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS plan_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_slug TEXT NOT NULL,
                    day_index INTEGER NOT NULL,
                    completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(plan_slug, day_index)
                );

                CREATE TABLE IF NOT EXISTS cross_references (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_book_id INTEGER NOT NULL,
                    source_chapter INTEGER NOT NULL,
                    source_verse INTEGER NOT NULL,
                    target_book_id INTEGER NOT NULL,
                    target_chapter INTEGER NOT NULL,
                    target_verse INTEGER NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    source_label TEXT NOT NULL DEFAULT '',
                    target_label TEXT NOT NULL DEFAULT '',
                    UNIQUE (
                        source_book_id, source_chapter, source_verse,
                        target_book_id, target_chapter, target_verse
                    )
                );
                """
            )
            conn.execute("PRAGMA foreign_keys = ON")
            self._seed_default_plans(conn)

    def _connect(self) -> sqlite3.Connection:
        self.init()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _seed_default_plans(self, conn: sqlite3.Connection) -> None:
        count = conn.execute("SELECT COUNT(*) FROM reading_plans").fetchone()[0]
        if int(count or 0) > 0:
            return
        plans = [
            {
                "slug": "gospels-30d",
                "title": "Evangelhos em 30 dias",
                "description": "Leitura guiada dos quatro evangelhos.",
                "days": [
                    ["Mateus 1-2"], ["Mateus 3-4"], ["Mateus 5-7"], ["Mateus 8-9"],
                    ["Mateus 10-11"], ["Mateus 12-13"], ["Mateus 14-15"], ["Mateus 16-17"],
                    ["Mateus 18-20"], ["Mateus 21-23"], ["Mateus 24-25"], ["Mateus 26-28"],
                    ["Marcos 1-2"], ["Marcos 3-4"], ["Marcos 5-6"], ["Marcos 7-8"],
                    ["Marcos 9-10"], ["Marcos 11-13"], ["Marcos 14-16"], ["Lucas 1-2"],
                    ["Lucas 3-4"], ["Lucas 5-6"], ["Lucas 7-9"], ["Lucas 10-12"],
                    ["Lucas 13-16"], ["Lucas 17-19"], ["Lucas 20-22"], ["Lucas 23-24"],
                    ["João 1-10"], ["João 11-21"],
                ],
            },
            {
                "slug": "psalms-prayers-21d",
                "title": "Salmos e oração (21 dias)",
                "description": "Plano curto para devoção e oração diária.",
                "days": [[f"Salmos {n}"] for n in [1, 3, 5, 8, 11, 15, 19, 23, 27, 32, 34, 37, 42, 46, 51, 63, 84, 91, 103, 121, 139]],
            },
            {
                "slug": "proverbs-wisdom-31d",
                "title": "Provérbios (31 dias)",
                "description": "Um capítulo de Provérbios por dia.",
                "days": [[f"Provérbios {n}"] for n in range(1, 32)],
            },
        ]
        for plan in plans:
            conn.execute(
                """
                INSERT INTO reading_plans (slug, title, description, days_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    plan["slug"],
                    plan["title"],
                    plan["description"],
                    _json_dumps(plan["days"]),
                ),
            )

    def upsert_note(
        self,
        *,
        translation: str,
        book_id: int | None,
        book: str,
        chapter: int,
        verse: int,
        note_text: str,
        highlight_color: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notes (
                    translation, book_id, book, chapter, verse, note_text, highlight_color, tags_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(translation, book, chapter, verse) DO UPDATE SET
                    book_id=excluded.book_id,
                    note_text=excluded.note_text,
                    highlight_color=excluded.highlight_color,
                    tags_json=excluded.tags_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    translation,
                    book_id,
                    book,
                    int(chapter),
                    int(verse),
                    note_text,
                    (highlight_color or "").strip(),
                    _json_dumps(tags),
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM notes
                WHERE translation=? AND book=? AND chapter=? AND verse=?
                """,
                (translation, book, int(chapter), int(verse)),
            ).fetchone()
            return self._note_row_to_dict(row)

    def get_note(
        self, *, translation: str, book: str, chapter: int, verse: int
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM notes
                WHERE translation=? AND book=? AND chapter=? AND verse=?
                """,
                (translation, book, int(chapter), int(verse)),
            ).fetchone()
            return self._note_row_to_dict(row) if row else None

    def delete_note(self, *, translation: str, book: str, chapter: int, verse: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM notes
                WHERE translation=? AND book=? AND chapter=? AND verse=?
                """,
                (translation, book, int(chapter), int(verse)),
            )
            return int(cur.rowcount)

    def list_notes(
        self,
        *,
        translation: str | None = None,
        book: str | None = None,
        chapter: int | None = None,
        tag: str | None = None,
        limit: int | None = 200,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM notes"
        where: list[str] = []
        params: list[Any] = []
        if translation:
            where.append("translation = ?")
            params.append(translation)
        if book:
            where.append("book = ?")
            params.append(book)
        if chapter is not None:
            where.append("chapter = ?")
            params.append(int(chapter))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        items = [self._note_row_to_dict(r) for r in rows]
        if tag:
            target = tag.strip().casefold()
            items = [
                item for item in items if any(str(t).casefold() == target for t in item.get("tags", []))
            ]
        return items

    def create_notebook(self, *, name: str, description: str = "") -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO notebooks (name, description) VALUES (?, ?)",
                (name.strip(), description.strip()),
            )
            row = conn.execute(
                "SELECT * FROM notebooks WHERE name = ?",
                (name.strip(),),
            ).fetchone()
            return dict(row)

    def list_notebooks(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT n.*,
                       COUNT(e.id) AS entry_count
                FROM notebooks n
                LEFT JOIN notebook_entries e ON e.notebook_id = n.id
                GROUP BY n.id
                ORDER BY n.created_at DESC, n.id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def add_notebook_entry(
        self,
        *,
        notebook_id: int,
        translation: str,
        book_id: int | None,
        book: str,
        chapter: int,
        verse: int,
        note_text: str = "",
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO notebook_entries (
                    notebook_id, translation, book_id, book, chapter, verse, note_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(notebook_id),
                    translation,
                    book_id,
                    book,
                    int(chapter),
                    int(verse),
                    note_text,
                ),
            )
            row = conn.execute(
                "SELECT * FROM notebook_entries WHERE id = ?",
                (int(cur.lastrowid),),
            ).fetchone()
            return dict(row)

    def list_notebook_entries(self, *, notebook_id: int, limit: int | None = 500) -> list[dict[str, Any]]:
        sql = """
            SELECT * FROM notebook_entries
            WHERE notebook_id = ?
            ORDER BY created_at DESC, id DESC
        """
        params: list[Any] = [int(notebook_id)]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    def delete_notebook_entry(self, *, entry_id: int) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM notebook_entries WHERE id = ?", (int(entry_id),))
            return int(cur.rowcount)

    def list_recent_notebook_entries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.*, n.name AS notebook_name
                FROM notebook_entries e
                JOIN notebooks n ON n.id = e.notebook_id
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_reading_plans(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*, COUNT(pg.id) AS completed_days
                FROM reading_plans p
                LEFT JOIN plan_progress pg ON pg.plan_slug = p.slug
                GROUP BY p.id
                ORDER BY p.title COLLATE NOCASE
                """
            ).fetchall()
        plans: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["days"] = json.loads(item.pop("days_json") or "[]")
            item["total_days"] = len(item["days"])
            item["completed_days"] = int(item.get("completed_days") or 0)
            plans.append(item)
        return plans

    def mark_plan_day(self, *, plan_slug: str, day_index: int, completed: bool) -> None:
        with self._connect() as conn:
            if completed:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO plan_progress (plan_slug, day_index)
                    VALUES (?, ?)
                    """,
                    (plan_slug, int(day_index)),
                )
            else:
                conn.execute(
                    "DELETE FROM plan_progress WHERE plan_slug = ? AND day_index = ?",
                    (plan_slug, int(day_index)),
                )

    def list_plan_progress(self, *, plan_slug: str) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT day_index FROM plan_progress WHERE plan_slug = ? ORDER BY day_index",
                (plan_slug,),
            ).fetchall()
            return [int(r["day_index"]) for r in rows]

    def add_cross_reference(
        self,
        *,
        source_book_id: int,
        source_chapter: int,
        source_verse: int,
        target_book_id: int,
        target_chapter: int,
        target_verse: int,
        weight: float = 1.0,
        source_label: str = "",
        target_label: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cross_references (
                    source_book_id, source_chapter, source_verse,
                    target_book_id, target_chapter, target_verse,
                    weight, source_label, target_label
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(source_book_id),
                    int(source_chapter),
                    int(source_verse),
                    int(target_book_id),
                    int(target_chapter),
                    int(target_verse),
                    float(weight),
                    source_label,
                    target_label,
                ),
            )

    def list_cross_references(
        self,
        *,
        source_book_id: int,
        source_chapter: int,
        source_verse: int,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM cross_references
                WHERE source_book_id = ? AND source_chapter = ? AND source_verse = ?
                ORDER BY weight DESC, id ASC
                LIMIT ?
                """,
                (int(source_book_id), int(source_chapter), int(source_verse), max(1, int(limit))),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_cross_references(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM cross_references").fetchone()
            return int(row["total"] or 0)

    def export_json(self) -> dict[str, Any]:
        with self._connect() as conn:
            payload: dict[str, Any] = {}
            for table in [
                "notes",
                "notebooks",
                "notebook_entries",
                "reading_plans",
                "plan_progress",
                "cross_references",
            ]:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                if table == "notes":
                    items = [self._note_row_to_dict(r) for r in rows]
                elif table == "reading_plans":
                    items = []
                    for r in rows:
                        item = dict(r)
                        try:
                            item["days"] = json.loads(item.pop("days_json") or "[]")
                        except Exception:
                            item["days"] = []
                        items.append(item)
                else:
                    items = [dict(r) for r in rows]
                payload[table] = items
            return payload

    def import_json(self, payload: dict[str, Any], *, merge: bool = True) -> dict[str, int]:
        self.init()
        counts = {
            "notes": 0,
            "notebooks": 0,
            "notebook_entries": 0,
            "reading_plans": 0,
            "plan_progress": 0,
            "cross_references": 0,
        }
        with self._connect() as conn:
            if not merge:
                conn.executescript(
                    """
                    DELETE FROM notes;
                    DELETE FROM notebook_entries;
                    DELETE FROM notebooks;
                    DELETE FROM plan_progress;
                    DELETE FROM cross_references;
                    """
                )
            for item in payload.get("notes", []) or []:
                if not isinstance(item, dict):
                    continue
                tags = [str(t).strip() for t in (item.get("tags") or []) if str(t).strip()]
                conn.execute(
                    """
                    INSERT INTO notes (
                        translation, book_id, book, chapter, verse, note_text, highlight_color, tags_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(translation, book, chapter, verse) DO UPDATE SET
                        book_id=excluded.book_id,
                        note_text=excluded.note_text,
                        highlight_color=excluded.highlight_color,
                        tags_json=excluded.tags_json,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        str(item.get("translation") or ""),
                        item.get("book_id"),
                        str(item.get("book") or ""),
                        int(item.get("chapter") or 0),
                        int(item.get("verse") or 0),
                        str(item.get("note_text") or ""),
                        str(item.get("highlight_color") or ""),
                        _json_dumps(tags),
                    ),
                )
                counts["notes"] += 1

            notebook_name_to_id: dict[str, int] = {}
            for item in payload.get("notebooks", []) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO notebooks (name, description) VALUES (?, ?)",
                    (name, str(item.get("description") or "")),
                )
                row = conn.execute("SELECT id, name FROM notebooks WHERE name = ?", (name,)).fetchone()
                if row:
                    notebook_name_to_id[str(row["name"])] = int(row["id"])
                counts["notebooks"] += 1

            for item in payload.get("notebook_entries", []) or []:
                if not isinstance(item, dict):
                    continue
                nb_name = str(item.get("notebook_name") or "")
                notebook_id = item.get("notebook_id")
                resolved_id: int | None = None
                if nb_name and nb_name in notebook_name_to_id:
                    resolved_id = notebook_name_to_id[nb_name]
                elif notebook_id is not None:
                    row = conn.execute("SELECT id FROM notebooks WHERE id = ?", (int(notebook_id),)).fetchone()
                    if row:
                        resolved_id = int(row["id"])
                if resolved_id is None:
                    row = conn.execute("SELECT id FROM notebooks ORDER BY id LIMIT 1").fetchone()
                    if row:
                        resolved_id = int(row["id"])
                if resolved_id is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO notebook_entries (
                        notebook_id, translation, book_id, book, chapter, verse, note_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_id,
                        str(item.get("translation") or ""),
                        item.get("book_id"),
                        str(item.get("book") or ""),
                        int(item.get("chapter") or 0),
                        int(item.get("verse") or 0),
                        str(item.get("note_text") or ""),
                    ),
                )
                counts["notebook_entries"] += 1

            for item in payload.get("plan_progress", []) or []:
                if not isinstance(item, dict):
                    continue
                slug = str(item.get("plan_slug") or "")
                day_index = int(item.get("day_index") or 0)
                if slug and day_index > 0:
                    conn.execute(
                        "INSERT OR IGNORE INTO plan_progress (plan_slug, day_index) VALUES (?, ?)",
                        (slug, day_index),
                    )
                    counts["plan_progress"] += 1

            for item in payload.get("cross_references", []) or []:
                if not isinstance(item, dict):
                    continue
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO cross_references (
                            source_book_id, source_chapter, source_verse,
                            target_book_id, target_chapter, target_verse,
                            weight, source_label, target_label
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(item.get("source_book_id")),
                            int(item.get("source_chapter")),
                            int(item.get("source_verse")),
                            int(item.get("target_book_id")),
                            int(item.get("target_chapter")),
                            int(item.get("target_verse")),
                            float(item.get("weight") or 1.0),
                            str(item.get("source_label") or ""),
                            str(item.get("target_label") or ""),
                        ),
                    )
                    counts["cross_references"] += 1
                except Exception:
                    continue
        return counts

    @staticmethod
    def _note_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
        except Exception:
            item["tags"] = []
        return item
