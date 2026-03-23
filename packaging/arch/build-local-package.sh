#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PKG_DIR="$ROOT_DIR/packaging/arch"
PKGBUILD="$PKG_DIR/PKGBUILD"

pkgname="$(awk -F= '/^pkgname=/{print $2; exit}' "$PKGBUILD")"
pkgver="$(awk -F= '/^pkgver=/{print $2; exit}' "$PKGBUILD")"
srcname="${pkgname}-${pkgver}"
tarball="$PKG_DIR/${srcname}.tar.gz"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

mkdir -p "$tmpdir/$srcname"
rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.flatpak-builder' \
  --exclude 'build-flatpak' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '*.pyc' \
  "$ROOT_DIR/" "$tmpdir/$srcname/"

tar -C "$tmpdir" -czf "$tarball" "$srcname"
echo "Tarball criado: $tarball"
echo "Execute:"
echo "  cd \"$PKG_DIR\" && makepkg -si"
