from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.backend import BibleBackend


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta backup completo do BíbliaRoot (config + favoritos + estudo).")
    parser.add_argument("--output", type=Path, help="Arquivo de saída JSON")
    args = parser.parse_args()

    out = args.output
    if out is None:
        docs = Path.home() / "Documentos"
        if not docs.exists():
            docs = Path.home()
        out = docs / f'bibliaroot-backup-completo-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'

    backend = BibleBackend()
    backend.initialize()
    backend.export_full_backup(out)
    print(f"Backup completo exportado: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
