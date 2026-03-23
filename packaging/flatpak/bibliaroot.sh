#!/usr/bin/env sh
set -eu
cd /app/share/bibliaroot
exec python3 /app/share/bibliaroot/main.py "$@"
