#!/usr/bin/env python3
"""
Idempotent migration: add `final_population_n` TEXT column to `secondaryreview` table
if it does not already exist.

Usage:
    python app/scripts/migrate_add_final_population_n.py --db /path/to/apathy_screen.db

By default the script will create a timestamped backup of the DB before ALTER TABLE.
"""
import argparse
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
import sys


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    return column in cols


def backup_db(db_path: Path) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_suffix(db_path.suffix + f".bak.{ts}")
    shutil.copy2(db_path, backup)
    return backup


def add_column(db_path: Path, table: str, column: str, coldef: str, do_backup: bool = True) -> int:
    if not db_path.exists():
        print(f"Error: DB file not found: {db_path}", file=sys.stderr)
        return 2

    if do_backup:
        try:
            b = backup_db(db_path)
            print(f"Backup created: {b}")
        except Exception as e:
            print(f"Warning: backup failed: {e}")

    conn = sqlite3.connect(str(db_path))
    try:
        if has_column(conn, table, column):
            print(f"Column '{column}' already exists on table '{table}', nothing to do.")
            return 0

        sql = f"ALTER TABLE {table} ADD COLUMN {column} {coldef}"
        print(f"Executing: {sql}")
        conn.execute(sql)
        conn.commit()
        print(f"Column '{column}' added to '{table}'.")
        return 0
    except sqlite3.OperationalError as e:
        print(f"SQLite operational error: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 4
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", help="Path to SQLite DB", default="/home/yvofxbku/apathy_data/apathy_screen.db")
    p.add_argument("--no-backup", help="Do not create backup before altering", action="store_true")
    args = p.parse_args()

    db_path = Path(args.db).expanduser()
    table = "secondaryreview"
    column = "final_population_n"
    coldef = "TEXT"

    rc = add_column(db_path, table, column, coldef, do_backup=not args.no_backup)
    sys.exit(rc)


if __name__ == "__main__":
    main()
