#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGDATA="$ROOT/.data/pgdata"
PGCTL="$ROOT/.venv/lib/python3.12/site-packages/pgserver/pginstall/bin/pg_ctl"
INITDB="$ROOT/.venv/lib/python3.12/site-packages/pgserver/pginstall/bin/initdb"

mkdir -p "$ROOT/.data"

if [ ! -d "$PGDATA/base" ]; then
  "$INITDB" -D "$PGDATA" -U postgres --auth=trust
fi

if [ ! -f "$PGDATA/postmaster.pid" ] || ! "$PGCTL" -D "$PGDATA" status >/dev/null 2>&1; then
  rm -f "$PGDATA/postmaster.pid"
  "$PGCTL" -D "$PGDATA" -o "-k $PGDATA" start
fi

echo "PostgreSQL running at $PGDATA"