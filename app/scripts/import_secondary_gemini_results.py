#!/usr/bin/env python
"""
import_secondary_gemini_results.py

Reads extraction_results.csv (Gemini extraction results) and upserts into
SecondaryAutoExtraction table.

Usage:
    python -m app.scripts.import_secondary_gemini_results --input /path/to/extraction_results.csv
"""

import sys
import argparse
import csv
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlmodel import Session, create_engine, select
from app.models import SecondaryAutoExtraction
from sqlalchemy import inspect
import os
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


def import_gemini_results(csv_path: str, database_url: str = None, mode: str = "insert-only", force: bool = False, pmid_filter: list | None = None):
    """
    Read extraction_results.csv and upsert into SecondaryAutoExtraction.
    
    Expected columns in CSV:
    - pmid
    - apathy_terms
    - population_N
    - prevalence
    - intervention
    - is_relevant
    """
    
    # Allow overriding DATABASE_URL via argument
    db_url = database_url or DATABASE_URL
    print(f"Using DATABASE_URL={db_url}")
    engine = create_engine(db_url, echo=False)

    # Check whether target table exists; if not, abort with instruction
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
    except Exception:
        tables = []
    if 'secondaryautoextraction' not in [t.lower() for t in tables]:
        print("ERROR: target table 'secondaryautoextraction' does not exist in the target database.")
        print("Run the following to create missing tables for this DATABASE_URL:")
        print("  AUTO_CREATE_TABLES=1 DATABASE_URL='{}' python -m app.scripts.setup_db --create-tables".format(db_url))
        sys.exit(2)
    
    csv_file = Path(csv_path)
    if not csv_file.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        sys.exit(1)
    
    count_inserted = 0
    count_updated = 0
    count_skipped = 0
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        with Session(engine) as session:
            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                try:
                    pmid_str = row.get('pmid', '').strip()
                    if not pmid_str:
                        print(f"  [Row {row_num}] Skipping: no pmid")
                        count_skipped += 1
                        continue
                    
                    try:
                        pmid = int(pmid_str)
                    except ValueError:
                        print(f"  [Row {row_num}] Skipping: invalid pmid={pmid_str}")
                        count_skipped += 1
                        continue
                    
                    # Extract relevant fields from CSV
                    apathy_terms = row.get('apathy_terms', '').strip()
                    population_n = row.get('population_N', '').strip()
                    prevalence = row.get('prevalence', '').strip()
                    intervention = row.get('intervention', '').strip()
                    is_relevant_str = row.get('is_relevant', '').strip().lower()
                    
                    # Parse is_relevant as boolean
                    is_relevant = None
                    if is_relevant_str in ('true', 'yes', '1'):
                        is_relevant = True
                    elif is_relevant_str in ('false', 'no', '0'):
                        is_relevant = False
                    
                    # Optional pmid filter
                    if pmid_filter and pmid not in pmid_filter:
                        # do not process this row
                        count_skipped += 1
                        continue

                    # Check if record already exists
                    existing = session.exec(
                        select(SecondaryAutoExtraction).where(SecondaryAutoExtraction.pmid == pmid)
                    ).first()

                    if existing:
                        if mode != 'upsert' or (mode == 'upsert' and not force):
                            # insert-only behavior: skip existing
                            print(f"  [Row {row_num}] Skipping existing pmid {pmid} (insert-only)")
                            count_skipped += 1
                        else:
                            # upsert with force -> update existing
                            existing.auto_apathy_terms = apathy_terms if apathy_terms else existing.auto_apathy_terms
                            existing.auto_population_N = population_n if population_n else existing.auto_population_N
                            existing.auto_prevalence = prevalence if prevalence else existing.auto_prevalence
                            existing.auto_intervention = intervention if intervention else existing.auto_intervention
                            existing.updated_at = datetime.utcnow().isoformat()
                            session.add(existing)
                            count_updated += 1
                    else:
                        # Create new record
                        new_record = SecondaryAutoExtraction(
                            pmid=pmid,
                            auto_apathy_terms=apathy_terms if apathy_terms else None,
                            auto_population_N=population_n if population_n else None,
                            auto_prevalence=prevalence if prevalence else None,
                            auto_intervention=intervention if intervention else None,
                            updated_at=datetime.utcnow().isoformat()
                        )
                        session.add(new_record)
                        count_inserted += 1
                    
                    # Commit every N records to avoid holding too many locks
                    if (row_num - 1) % 100 == 0:
                        session.commit()
                        print(f"  Processed {row_num - 1} rows...")
                
                except Exception as e:
                    print(f"  [Row {row_num}] Error: {e}")
                    count_skipped += 1
                    continue
            
            # Final commit
            session.commit()
    
    print("\n" + "="*60)
    print("Import Summary:")
    print(f"  Inserted: {count_inserted}")
    print(f"  Updated:  {count_updated}")
    print(f"  Skipped:  {count_skipped}")
    print("="*60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import Gemini extraction results from CSV into SecondaryAutoExtraction table"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to extraction_results.csv"
    )
    parser.add_argument("--mode", choices=["insert-only","upsert"], default="insert-only", help="insert-only (default) or upsert")
    parser.add_argument("--force", action="store_true", help="When using upsert, actually overwrite existing rows")
    parser.add_argument("--db-url", help="Optional DATABASE_URL to use instead of env var")
    parser.add_argument("--pmid", help="Comma-separated list of pmids to import (e.g. 123,456)")
    
    args = parser.parse_args()

    print(f"Importing from: {args.input}")
    pmid_filter = None
    if args.pmid:
        try:
            pmid_filter = [int(x.strip()) for x in args.pmid.split(',') if x.strip()]
        except Exception:
            print("Invalid --pmid list; must be comma-separated integers")
            sys.exit(2)
    import_gemini_results(args.input, database_url=args.db_url, mode=args.mode, force=args.force, pmid_filter=pmid_filter)
    print("Import completed!")
