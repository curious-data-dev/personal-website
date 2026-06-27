"""Versioned SQLite migration command used by Docker deployments."""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.database import DB_PATH, MIGRATIONS_DIR, init_db


def has_pending_migrations() -> bool:
    if not DB_PATH.exists():
        return True
    conn = sqlite3.connect(str(DB_PATH))
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not table:
            return True
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        return any(path.stem not in applied for path in MIGRATIONS_DIR.glob("*.sql"))
    finally:
        conn.close()


def backup_database() -> Path | None:
    if not DB_PATH.exists():
        return None
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{DB_PATH.stem}-{stamp}.db"
    source_conn = sqlite3.connect(str(DB_PATH))
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    pending = has_pending_migrations()
    backup = None if args.no_backup or not pending else backup_database()
    if backup:
        print(f"Database backup: {backup}")
    init_db()
    print("Database migrations complete")


if __name__ == "__main__":
    main()
