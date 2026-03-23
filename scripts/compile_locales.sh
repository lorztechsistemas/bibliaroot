#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p locale

xgettext -L Python -k_ -o locale/bibliaapp.pot app/*.py app/services/*.py scripts/daily_notification.py

for lang in pt_BR en es; do
  po="locale/${lang}/LC_MESSAGES/bibliaapp.po"
  mo="locale/${lang}/LC_MESSAGES/bibliaapp.mo"
  mkdir -p "$(dirname "$po")"
  if [[ ! -f "$po" ]]; then
    msginit --no-translator --locale="${lang}.UTF-8" --input=locale/bibliaapp.pot --output-file="$po"
  else
    msgmerge --update --no-fuzzy-matching "$po" locale/bibliaapp.pot >/dev/null
  fi
  msgfmt "$po" -o "$mo"
done

echo "Locales atualizados e compilados."
