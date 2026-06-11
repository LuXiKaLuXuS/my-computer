#!/usr/bin/env python3
"""Start local My Computer stack without Docker (pgserver + uvicorn)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PGDATA = ROOT / ".data" / "pgdata"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
VENV_UVICORN = ROOT / ".venv" / "bin" / "uvicorn"


def ensure_pgserver() -> str:
    import pgserver

    PGDATA.parent.mkdir(parents=True, exist_ok=True)
    pg = pgserver.get_server(str(PGDATA), cleanup_mode="stop")
    time.sleep(1)
    uri = pg.get_uri()
    # asyncpg unix socket URI
    async_url = uri.replace("postgresql://", "postgresql+asyncpg://")
    if "postgresql+asyncpg://" not in async_url:
        async_url = f"postgresql+asyncpg://postgres@/postgres?host={PGDATA}"
    return async_url


def run_migrations(database_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [str(ROOT / ".venv" / "bin" / "alembic"), "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
    )


def main() -> None:
    os.chdir(ROOT)
    if not VENV_UVICORN.exists():
        print("Missing .venv – run: python3 -m venv .venv && pip install -r requirements.txt")
        sys.exit(1)

    database_url = ensure_pgserver()
    print(f"PostgreSQL ready: {PGDATA}")
    os.environ["DATABASE_URL"] = database_url

    if not (PGDATA / "pgdata_bootstrapped").exists():
        run_migrations(database_url)
        (PGDATA / "pgdata_bootstrapped").touch()
        print("Migrations applied.")

    print("Starting API on http://localhost:8000")
    subprocess.run(
        [
            str(VENV_UVICORN),
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
    )


if __name__ == "__main__":
    main()