#!/usr/bin/env bash
# Build dist/ngbs_icon.zip (see scripts/package.py).
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/package.py "$@"
