#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Starting PostgreSQL (pgserver binaries)"
"$ROOT/scripts/pg_ctl_local.sh"

if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> "$ROOT/.env"
fi

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres@127.0.0.1:5432/postgres}"

echo "==> Running migrations"
"$ROOT/.venv/bin/alembic" upgrade head

echo "==> Starting API http://127.0.0.1:8000"
exec "$ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 --reload