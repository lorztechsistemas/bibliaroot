from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.backend import BibleBackend


def main() -> int:
    parser = argparse.ArgumentParser(description="Restaura backup completo do BíbliaRoot.")
    parser.add_argument("--input", type=Path, required=True, help="Arquivo JSON de backup")
    parser.add_argument("--replace", action="store_true", help="Substitui dados (em vez de mesclar)")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    if not source.exists():
        print(f"Arquivo não encontrado: {source}")
        return 1

    backend = BibleBackend()
    backend.initialize()
    result = backend.import_full_backup(source, merge=not args.replace)
    print(f"Backup restaurado: {source}")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
