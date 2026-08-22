#!/usr/bin/env bash
# filepath: run.sh
# Convenience launcher. Activates venv (created via `uv venv`) and runs uvicorn.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ ! -d venv ]; then
  echo "venv missing — create it first: uv venv venv --python python3.14"
  exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate

# Load .env if present
[ -f .env ] && set -a && . ./.env && set +a

exec uvicorn app.main:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8000}" \
  --reload \
  --log-level "${LOG_LEVEL:-info}"
