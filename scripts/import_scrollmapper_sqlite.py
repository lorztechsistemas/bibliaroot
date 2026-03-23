from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import sys
from typing import Any

from app.services.language_inference import infer_language_code


@dataclass
class ScrollmapperTranslation:
    code: str
    title: str
    language: str | None = None
    license_text: str | None = None


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Evita falhas de SQLite ao criar arquivos temporários de ordenação em ambientes restritos.
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _translations_columns(conn: sqlite3.Connection) -> set[str]:
    cols = conn.execute("PRAGMA table_info(translations)").fetchall()
    return {str(r["name"]) for r in cols}


def list_translations(source_db: Path) -> list[ScrollmapperTranslation]:
    with _connect(source_db) as conn:
        if not _table_exists(conn, "translations"):
            raise RuntimeError("Tabela 'translations' não encontrada no SQLite de origem.")
        cols = _translations_columns(conn)
        rows = conn.execute("SELECT * FROM translations ORDER BY translation").fetchall()
        out: list[ScrollmapperTranslation] = []
        for row in rows:
            code = str(row["translation"])
            title = str(row["title"] or code) if "title" in cols else code
            lang = None
            for candidate in ("language", "lang", "iso", "iso_code"):
                if candidate in cols and row[candidate]:
                    lang = str(row[candidate])
                    break
            license_text = str(row["license"]) if "license" in cols and row["license"] else None
            out.append(
                ScrollmapperTranslation(
                    code=code,
                    title=title,
                    language=lang,
                    license_text=license_text,
                )
            )
        return out


def _create_target_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS testament (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS book (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            testament_reference_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS verse (
            book_id INTEGER NOT NULL,
            chapter INTEGER NOT NULL,
            verse INTEGER NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY (book_id, chapter, verse)
        );
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_verse_book_chapter ON verse(book_id, chapter);
        CREATE INDEX IF NOT EXISTS idx_verse_text ON verse(text);
        """
    )
    conn.execute("INSERT OR REPLACE INTO testament (id, name) VALUES (1, 'Old Testament')")
    conn.execute("INSERT OR REPLACE INTO testament (id, name) VALUES (2, 'New Testament')")


def _infer_testament_id(book_id: int, total_books: int) -> int | None:
    if total_books == 66:
        return 1 if int(book_id) <= 39 else 2
    if total_books == 39:
        return 1
    if total_books == 27:
        return 2
    return None


def _read_books_and_verses(conn: sqlite3.Connection, code: str) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    books_table = f"{code}_books"
    verses_table = f"{code}_verses"
    if not _table_exists(conn, books_table):
        raise RuntimeError(f"Tabela '{books_table}' não encontrada.")
    if not _table_exists(conn, verses_table):
        raise RuntimeError(f"Tabela '{verses_table}' não encontrada.")
    books = conn.execute(f"SELECT id, name FROM '{books_table}' ORDER BY id").fetchall()
    verses = conn.execute(
        f"SELECT book_id, chapter, verse, text FROM '{verses_table}' ORDER BY book_id, chapter, verse"
    ).fetchall()
    return books, verses


def export_translation(
    source_db: Path,
    out_dir: Path,
    meta: ScrollmapperTranslation,
    *,
    overwrite: bool = False,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target_db = out_dir / f"{meta.code}.sqlite"
    if target_db.exists() and not overwrite:
        raise FileExistsError(f"Arquivo já existe: {target_db}")
    if target_db.exists():
        target_db.unlink()

    with _connect(source_db) as src:
        books, verses = _read_books_and_verses(src, meta.code)
    total_books = len(books)

    with sqlite3.connect(target_db) as dst:
        dst.row_factory = sqlite3.Row
        _create_target_schema(dst)

        dst.executemany(
            "INSERT OR REPLACE INTO book (id, name, testament_reference_id) VALUES (?, ?, ?)",
            [
                (
                    int(row["id"]),
                    str(row["name"]),
                    _infer_testament_id(int(row["id"]), total_books),
                )
                for row in books
            ],
        )
        dst.executemany(
            "INSERT OR REPLACE INTO verse (book_id, chapter, verse, text) VALUES (?, ?, ?, ?)",
            [
                (
                    int(row["book_id"]),
                    int(row["chapter"]),
                    int(row["verse"]),
                    str(row["text"] or ""),
                )
                for row in verses
            ],
        )

        metadata: dict[str, Any] = {
            "translation": meta.code,
            "name": meta.title or meta.code,
            "source": "scrollmapper",
            "source_db": source_db.name,
        }
        inferred_lang = meta.language or infer_language_code(meta.code, meta.title)
        if inferred_lang:
            metadata["language"] = inferred_lang
        if meta.license_text:
            metadata["license"] = meta.license_text
        dst.executemany(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            [(str(k), str(v)) for k, v in metadata.items()],
        )
        dst.commit()
    return target_db


def export_many(
    source_db: Path,
    out_dir: Path,
    codes: list[str] | None = None,
    *,
    overwrite: bool = False,
) -> list[Path]:
    catalog = list_translations(source_db)
    by_code = {item.code.upper(): item for item in catalog}
    selected_codes = [c.upper() for c in codes] if codes else sorted(by_code)
    missing = [c for c in selected_codes if c not in by_code]
    if missing:
        raise RuntimeError(f"Traduções não encontradas na origem: {', '.join(missing)}")
    outputs: list[Path] = []
    for code in selected_codes:
        outputs.append(export_translation(source_db, out_dir, by_code[code], overwrite=overwrite))
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa traduções do SQLite do scrollmapper/bible_databases para o formato local do BíbliaRoot."
    )
    parser.add_argument("--source", type=Path, required=True, help="SQLite de origem (Scrollmapper).")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "bibles",
        help="Diretório de saída para os .sqlite do BíbliaRoot.",
    )
    parser.add_argument("--list", action="store_true", help="Lista traduções disponíveis e sai.")
    parser.add_argument(
        "--translations",
        nargs="+",
        help="Lista de códigos para importar (ex.: ACF KJV SpaRV1909). Se omitido, importa todas.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Sobrescreve arquivos existentes.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    if not source.exists():
        print(f"Erro: arquivo de origem não encontrado: {source}")
        return 1
    try:
        catalog = list_translations(source)
    except Exception as exc:
        print(f"Erro ao ler catálogo: {exc}")
        return 2

    if args.list:
        print(f"Origem: {source}")
        for item in catalog:
            lang = f" [{item.language}]" if item.language else ""
            print(f"- {item.code}{lang}: {item.title}")
        print(f"Total: {len(catalog)}")
        return 0

    try:
        outputs = export_many(
            source,
            args.out_dir.resolve(),
            args.translations,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"Erro: {exc}")
        print("Use --overwrite para sobrescrever.")
        return 3
    except Exception as exc:
        print(f"Erro ao importar: {exc}")
        return 4

    print(f"Importadas {len(outputs)} tradução(ões) para {args.out_dir.resolve()}:")
    for path in outputs:
        print(f" - {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
