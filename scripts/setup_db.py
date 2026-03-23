from __future__ import annotations

import argparse
from pathlib import Path
import sys

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from scripts.import_scrollmapper_sqlite import export_many as import_scrollmapper_many
except Exception:  # pragma: no cover
    try:
        from import_scrollmapper_sqlite import export_many as import_scrollmapper_many
    except Exception:  # pragma: no cover
        import_scrollmapper_many = None

try:
    from scripts.import_scrollmapper_crossrefs import import_crossrefs as import_scrollmapper_crossrefs
except Exception:  # pragma: no cover
    try:
        from import_scrollmapper_crossrefs import import_crossrefs as import_scrollmapper_crossrefs
    except Exception:  # pragma: no cover
        import_scrollmapper_crossrefs = None


DEFAULT_TRANSLATIONS = [
    "ARA",
    "ARC",
    "NVI",
    "ACF",
    "KJA",
]


def ensure_dirs(base_dir: Path) -> tuple[Path, Path]:
    bibles_dir = base_dir / "data" / "bibles"
    user_dir = base_dir / "data" / "user"
    bibles_dir.mkdir(parents=True, exist_ok=True)
    user_dir.mkdir(parents=True, exist_ok=True)
    return bibles_dir, user_dir


def guess_download_urls(translation: str) -> list[str]:
    filename = f"{translation}.sqlite"
    return [
        f"https://raw.githubusercontent.com/damarals/biblias/master/inst/sql/{filename}",
        f"https://raw.githubusercontent.com/damarals/biblias/main/inst/sql/{filename}",
        f"https://github.com/damarals/biblias/raw/master/inst/sql/{filename}",
        f"https://github.com/damarals/biblias/raw/main/inst/sql/{filename}",
    ]


def download_file(urls: list[str], destination: Path, timeout: int = 30) -> bool:
    if requests is None:
        raise RuntimeError("Dependencia 'requests' nao instalada.")

    for url in urls:
        response = requests.get(url, timeout=timeout)
        if response.status_code == 200 and response.content:
            destination.write_bytes(response.content)
            return True
    return False


def write_user_seed_files(user_dir: Path) -> None:
    favorites_db = user_dir / "favorites.db"
    settings_json = user_dir / "settings.json"
    if not settings_json.exists():
        settings_json.write_text(
            '{\n  "translation": "ARA",\n  "font_scale": 1.0,\n  "last_book": "Joao",\n  "last_chapter": 3\n}\n',
            encoding="utf-8",
        )
    if not favorites_db.exists():
        favorites_db.touch()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepara pastas locais e baixa bancos SQLite das traducoes."
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Diretorio raiz do projeto (padrao: pasta atual do repositorio).",
    )
    parser.add_argument(
        "--translations",
        nargs="+",
        default=DEFAULT_TRANSLATIONS,
        help="Lista de traducoes para baixar (ex: ARA ARC NVI).",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Cria a estrutura de pastas sem tentar baixar arquivos.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sobrescreve arquivos .sqlite existentes.",
    )
    parser.add_argument(
        "--scrollmapper-source",
        type=Path,
        help="SQLite de origem do scrollmapper/bible_databases para importar traducoes multilíngues.",
    )
    parser.add_argument(
        "--scrollmapper-translations",
        nargs="+",
        help="Códigos de traduções do Scrollmapper para importar (se omitido, importa todas).",
    )
    parser.add_argument(
        "--scrollmapper-crossrefs-source",
        type=Path,
        help="SQLite de referências cruzadas para importar ao study.db.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_dir = args.project_dir.resolve()
    bibles_dir, user_dir = ensure_dirs(project_dir)
    write_user_seed_files(user_dir)
    study_db = user_dir / "study.db"

    print(f"Projeto: {project_dir}")
    print(f"Bancos:   {bibles_dir}")
    print(f"Usuario:  {user_dir}")

    if args.scrollmapper_source:
        source = args.scrollmapper_source.resolve()
        if import_scrollmapper_many is None:
            print("Erro: importador Scrollmapper indisponível (scripts/import_scrollmapper_sqlite.py).")
            return 1
        if not source.exists():
            print(f"Erro: SQLite Scrollmapper nao encontrado: {source}")
            return 1
        print(f"[scrollmapper] importando de {source} ...")
        try:
            imported = import_scrollmapper_many(
                source_db=source,
                out_dir=bibles_dir,
                codes=args.scrollmapper_translations,
                overwrite=bool(args.force),
            )
        except FileExistsError as exc:
            print(f"Erro: {exc}")
            print("Use --force para sobrescrever bancos existentes.")
            return 3
        except Exception as exc:
            print(f"Erro ao importar Scrollmapper: {exc}")
            return 4
        print(f"[scrollmapper] {len(imported)} traducao(oes) importada(s).")
        for path in imported[:20]:
            print(f"  - {path.name}")
        if len(imported) > 20:
            print(f"  ... e mais {len(imported) - 20}")
        if args.skip_download:
            print("Download ignorado (--skip-download).")
            if args.scrollmapper_crossrefs_source:
                pass
            else:
                return 0

    if args.scrollmapper_crossrefs_source:
        source = args.scrollmapper_crossrefs_source.resolve()
        if import_scrollmapper_crossrefs is None:
            print("Erro: importador de referências cruzadas indisponível (scripts/import_scrollmapper_crossrefs.py).")
            return 1
        if not source.exists():
            print(f"Erro: SQLite de referências cruzadas não encontrado: {source}")
            return 1
        print(f"[crossrefs] importando de {source} ...")
        try:
            total = import_scrollmapper_crossrefs(source, study_db=study_db)
        except Exception as exc:
            print(f"Erro ao importar referências cruzadas: {exc}")
            return 5
        print(f"[crossrefs] {total} referência(s) importada(s) em {study_db}")

    if args.skip_download:
        print("Download ignorado (--skip-download).")
        return 0

    if requests is None:
        print("Erro: pacote 'requests' nao instalado. Rode: pip install -r requirements.txt")
        return 1

    failures: list[str] = []
    for code in args.translations:
        code = code.upper()
        dest = bibles_dir / f"{code}.sqlite"
        if dest.exists() and not args.force:
            print(f"[skip] {code}: arquivo ja existe ({dest.name})")
            continue
        print(f"[down] {code}: tentando baixar...")
        try:
            ok = download_file(guess_download_urls(code), dest)
        except Exception as exc:  # pragma: no cover
            print(f"[erro] {code}: {exc}")
            failures.append(code)
            continue
        if ok:
            print(f"[ok]   {code}: salvo em {dest}")
        else:
            print(f"[fail] {code}: nao encontrado nas URLs testadas")
            failures.append(code)

    if failures:
        print("Falhas:", ", ".join(failures))
        return 2
    print("Setup concluido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
