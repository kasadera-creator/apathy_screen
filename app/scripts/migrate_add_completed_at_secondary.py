#!/usr/bin/env python
"""
migrate_add_completed_at_secondary.py

Adds completed_at column to SecondaryReview table to track completion status.
This allows completed items to remain visible and editable.

Usage:
    python -m app.scripts.migrate_add_completed_at_secondary
"""

import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text, inspect
from sqlmodel import Session, create_engine
from dotenv import load_dotenv

# Load environment
env_file = os.getenv("ENV_FILE")
if env_file:
    load_dotenv(env_file)
else:
    load_dotenv(".env.local")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")


def migrate_add_completed_at():
    """Add completed_at column to SecondaryReview table if not exists."""
    engine = create_engine(DATABASE_URL, echo=False)
    
    print(f"Database: {DATABASE_URL}")
    print("Checking SecondaryReview table schema...\n")
    
    # Check if column exists
    with Session(engine) as session:
        inspector = inspect(engine)
        columns = inspector.get_columns('secondaryreview')
        column_names = [col['name'] for col in columns]
        
        if 'completed_at' in column_names:
            print("✓ Column 'completed_at' already exists in SecondaryReview table")
            return
        
        print("Column 'completed_at' NOT found. Adding it...\n")
        
        # Add column
        try:
            # SQLite syntax
            session.exec(text("""
                ALTER TABLE secondaryreview 
                ADD COLUMN completed_at TEXT DEFAULT NULL
            """))
            session.commit()
            print("✓ Column 'completed_at' added successfully to SecondaryReview table")
        except Exception as e:
            print(f"ERROR: Failed to add column: {e}")
            raise
    
    # Verify
    with Session(engine) as session:
        inspector = inspect(engine)
        columns = inspector.get_columns('secondaryreview')
        column_names = [col['name'] for col in columns]
        if 'completed_at' in column_names:
            print("\n✓ Verification: Column 'completed_at' is now in schema")
        else:
            print("\n❌ Verification failed: Column not found after migration")


if __name__ == '__main__':
    migrate_add_completed_at()
