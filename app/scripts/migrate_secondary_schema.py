#!/usr/bin/env python3
"""
Idempotent migration script to ensure secondary tables exist:
 - secondaryarticle
 - secondaryautoextraction
 - secondaryreview

Usage:
    python app/scripts/migrate_secondary_schema.py --db /path/to/apathy_screen.db

The script checks sqlite_master for each table and runs CREATE TABLE only when missing.
It creates a timestamped backup by default.
"""
from pathlib import Path
import argparse
import sqlite3
import shutil
from datetime import datetime
import sys


def backup(db_path: Path) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = db_path.with_suffix(db_path.suffix + f".bak.{ts}")
    shutil.copy2(db_path, dest)
    return dest


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def create_tables(conn: sqlite3.Connection):
    # Create secondaryarticle
    conn.execute("""
    CREATE TABLE IF NOT EXISTS secondaryarticle (
        id INTEGER PRIMARY KEY,
        pmid INTEGER UNIQUE,
        is_physical INTEGER DEFAULT 0,
        is_brain INTEGER DEFAULT 0,
        is_psycho INTEGER DEFAULT 0,
        is_drug INTEGER DEFAULT 0,
        pdf_exists INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    # Create secondaryautoextraction
    conn.execute("""
    CREATE TABLE IF NOT EXISTS secondaryautoextraction (
        id INTEGER PRIMARY KEY,
        pmid INTEGER UNIQUE,
        auto_citation TEXT,
        auto_apathy_terms TEXT,
        auto_target_condition TEXT,
        auto_population_N TEXT,
        auto_prevalence TEXT,
        auto_intervention TEXT,
        auto_confidence TEXT,
        auto_needs_review INTEGER DEFAULT 0,
        updated_at TEXT
    )
    """)

    # Create secondaryreview
    conn.execute("""
    CREATE TABLE IF NOT EXISTS secondaryreview (
        id INTEGER PRIMARY KEY,
        pmid INTEGER,
        "group" TEXT,
        reviewer_id INTEGER,
        decision TEXT DEFAULT 'pending',
        final_citation TEXT,
        final_apathy_terms TEXT,
        final_target_condition TEXT,
        final_population_n TEXT,
        final_prevalence TEXT,
        final_intervention TEXT,
        comment TEXT,
        updated_at TEXT
    )
    """)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="/home/yvofxbku/apathy_data/apathy_screen.db")
    p.add_argument("--no-backup", action="store_true", help="Do not create a backup copy before modifying DB")
    args = p.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"Error: DB not found: {db_path}", file=sys.stderr)
        sys.exit(2)

    if not args.no_backup:
        try:
            b = backup(db_path)
            print(f"Backup created: {b}")
        except Exception as e:
            print(f"Warning: backup failed: {e}")

    conn = sqlite3.connect(str(db_path))
    try:
        # Ensure tables exist (CREATE TABLE IF NOT EXISTS is idempotent)
        create_tables(conn)
        conn.commit()
        print("Ensured tables: secondaryarticle, secondaryautoextraction, secondaryreview")
    except Exception as e:
        print(f"Error during migration: {e}", file=sys.stderr)
        sys.exit(3)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
