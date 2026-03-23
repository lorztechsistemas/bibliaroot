#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "[1/4] Testes"
pytest -q

echo "[2/4] Compile"
python3 -m compileall app scripts tests main.py >/dev/null

echo "[3/4] Locales"
bash scripts/compile_locales.sh

echo "[4/4] Validação AppStream (se disponível)"
if command -v appstreamcli >/dev/null 2>&1; then
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT
  mkdir -p "$tmpdir/metainfo" "$tmpdir/applications" "$tmpdir/icons/hicolor/scalable/apps"
  cp packaging/flatpak/io.github.lorztechsistemas.bibliaroot.metainfo.xml "$tmpdir/metainfo/"
  cp packaging/flatpak/io.github.lorztechsistemas.bibliaroot.desktop "$tmpdir/applications/io.github.lorztechsistemas.bibliaroot.desktop"
  cp resources/icons/io.github.bibliaapp.svg "$tmpdir/icons/hicolor/scalable/apps/io.github.lorztechsistemas.bibliaroot.svg"
  appstreamcli validate --no-net packaging/flatpak/io.github.lorztechsistemas.bibliaroot.metainfo.xml || true
else
  echo "appstreamcli não encontrado; pulando."
fi

echo "Checklist local de release concluído."
