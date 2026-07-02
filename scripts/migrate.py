"""
Apply db/migrations/*.sql in order, each in its own transaction, exactly once.

Applied files are recorded in public.schema_migrations together with a SHA-256 of their
contents, so editing a migration that has already run is detected instead of silently ignored.

Usage:
    python scripts/migrate.py                 # uses DATABASE_URL or postgresql:///event_mgmt
    python scripts/migrate.py --reset         # drop and recreate the database first
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "db" / "migrations"
DEFAULT_URL = "postgresql:///event_mgmt"


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_URL)


def reset_database(url: str) -> None:
    info = psycopg.conninfo.conninfo_to_dict(url)
    name = info.get("dbname", "event_mgmt")
    admin = psycopg.conninfo.make_conninfo(url, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as con:
        con.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        con.execute(f'CREATE DATABASE "{name}"')
    print(f"recreated database {name}")


def migrate(url: str) -> list[str]:
    applied_now = []
    with psycopg.connect(url) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS public.schema_migrations (
                           filename   text PRIMARY KEY,
                           sha256     text NOT NULL,
                           applied_at timestamptz NOT NULL DEFAULT now())""")
        con.commit()
        done = dict(con.execute("SELECT filename, sha256 FROM public.schema_migrations").fetchall())
        for path in sorted(MIGRATIONS.glob("*.sql")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.name in done:
                if done[path.name] != digest:
                    sys.exit(f"{path.name} changed after it was applied; add a new migration instead")
                continue
            with con.transaction():
                con.execute(path.read_text())
                con.execute("INSERT INTO public.schema_migrations (filename, sha256) VALUES (%s, %s)",
                            (path.name, digest))
            applied_now.append(path.name)
            print(f"applied {path.name}")
    return applied_now


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="drop and recreate the database first")
    args = ap.parse_args()
    url = database_url()
    if args.reset:
        reset_database(url)
    applied = migrate(url)
    print(f"{len(applied)} migration(s) applied" if applied else "database is up to date")


if __name__ == "__main__":
    main()
