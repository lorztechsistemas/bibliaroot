from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.language_inference import infer_language_code


def _read_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM metadata").fetchall()
    except sqlite3.Error:
        return {}
    return {str(k): str(v) for k, v in rows}


def main() -> int:
    bibles_dir = ROOT / "data" / "bibles"
    files = sorted(bibles_dir.glob("*.sqlite"))
    updated = 0
    skipped = 0
    for dbfile in files:
        try:
            with sqlite3.connect(dbfile) as conn:
                meta = _read_metadata(conn)
                code = str(meta.get("translation") or dbfile.stem)
                title = meta.get("name") or meta.get("copyright") or ""
                current = str(meta.get("language") or "").strip()
                inferred = infer_language_code(code, title)
                if current:
                    skipped += 1
                    continue
                if not inferred:
                    skipped += 1
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("language", inferred),
                )
                conn.commit()
                updated += 1
        except sqlite3.Error:
            skipped += 1
            continue
    print(f"Backfill concluído: updated={updated} skipped={skipped} total={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
