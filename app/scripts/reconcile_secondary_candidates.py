#!/usr/bin/env python
"""
reconcile_secondary_candidates.py

Safely upserts missing secondary candidates from CSVs into the database.

Upsert policy:
  - Does NOT overwrite existing SecondaryArticle records
  - Adds only missing PMIDs
  - Preserves all existing reviews and auto-extractions
  - Sets created_at/updated_at timestamps appropriately

Usage (dry-run first!):
    python -m app.scripts.reconcile_secondary_candidates \
      --physical /path/to/category_physical_allgroups.csv \
      --brain /path/to/category_brain_allgroups.csv \
      --psycho /path/to/category_psycho_allgroups.csv \
      --dry-run
    
    # Then commit with --create-missing
    python -m app.scripts.reconcile_secondary_candidates \
      --physical /path/to/category_physical_allgroups.csv \
      --brain /path/to/category_brain_allgroups.csv \
      --psycho /path/to/category_psycho_allgroups.csv \
      --create-missing
"""

import sys
import argparse
import csv
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlmodel import Session, create_engine, select
from app.models import SecondaryArticle
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


def load_pmids_from_csv(csv_path: str) -> set:
    """Load PMID set from CSV file."""
    pmids = set()
    
    if not Path(csv_path).exists():
        print(f"  ERROR: CSV not found: {csv_path}")
        return pmids
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or 'pmid' not in reader.fieldnames:
            print(f"  ERROR: 'pmid' column not found in {csv_path}")
            return pmids
        
        for row in reader:
            raw_pmid = row.get('pmid', '').strip()
            
            try:
                if not raw_pmid or raw_pmid.lower() in ['none', 'nan', '']:
                    continue
                
                if '.' in raw_pmid:
                    pmid_int = int(float(raw_pmid))
                else:
                    pmid_int = int(raw_pmid)
                
                if pmid_int > 0:
                    pmids.add(pmid_int)
            except (ValueError, TypeError):
                pass
    
    return pmids


def reconcile(
    physical_csv,
    brain_csv,
    psycho_csv,
    database_url=None,
    dry_run=False,
    create_missing=False,
    only_missing=False,
):
    """Main reconciliation logic."""
    db_url = database_url or DATABASE_URL
    
    print(f"\n{'='*70}")
    print(f"Secondary Candidates Reconciliation")
    print(f"{'='*70}")
    print(f"Database: {db_url}")
    print(f"Mode: {'DRY-RUN' if dry_run else 'REAL'}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")
    
    # Load CSVs
    print("Loading CSV files...")
    csv_physical = load_pmids_from_csv(physical_csv)
    csv_brain = load_pmids_from_csv(brain_csv)
    csv_psycho = load_pmids_from_csv(psycho_csv)
    
    print(f"  Physical: {len(csv_physical)} PMIDs")
    print(f"  Brain: {len(csv_brain)} PMIDs")
    print(f"  Psycho: {len(csv_psycho)} PMIDs")
    
    # Connect to DB
    engine = create_engine(db_url, echo=False)
    print(f"\nConnecting to DB: {engine.url}")
    
    with Session(engine) as session:
        # Find missing PMIDs for each category
        missing_by_category = {
            "physical": [],
            "brain": [],
            "psycho": [],
        }
        
        for category, csv_pmids in [
            ("physical", csv_physical),
            ("brain", csv_brain),
            ("psycho", csv_psycho),
        ]:
            col = getattr(SecondaryArticle, f"is_{category}")
            db_pmids_set = set(
                session.exec(select(SecondaryArticle.pmid).where(col == True)).all()
            )
            
            missing = csv_pmids - db_pmids_set
            missing_by_category[category] = sorted(list(missing))
            
            print(f"  {category}: CSV={len(csv_pmids)}, DB={len(db_pmids_set)}, Missing={len(missing)}")
        
        # Summary
        total_missing = sum(len(m) for m in missing_by_category.values())
        print(f"\nTotal missing PMIDs to reconcile: {total_missing}")
        
        if dry_run:
            print("\n[DRY-RUN MODE] Showing what would be inserted:\n")
            for category, missing_pmids in missing_by_category.items():
                if missing_pmids:
                    sample = missing_pmids[:5]
                    print(f"  {category}: INSERT {len(missing_pmids)} records")
                    print(f"    Sample: {sample}{'...' if len(missing_pmids) > 5 else ''}")
        
        elif create_missing:
            print("\n[REAL MODE] Creating missing records...\n")
            
            created = 0
            updated = 0
            
            for category, missing_pmids in missing_by_category.items():
                category_col = f"is_{category}"
                
                for pmid in missing_pmids:
                    # Check if record exists
                    existing = session.exec(
                        select(SecondaryArticle).where(SecondaryArticle.pmid == pmid)
                    ).first()
                    
                    if existing:
                        # Record exists: only set category flag if not already set
                        flag_value = getattr(existing, category_col, False)
                        if not flag_value:
                            setattr(existing, category_col, True)
                            existing.updated_at = datetime.utcnow().isoformat()
                            session.add(existing)
                            updated += 1
                            if updated <= 5:
                                print(f"  Updated: {pmid} (set {category_col}=True)")
                    else:
                        # Record does NOT exist: create it
                        flags = {
                            "is_physical": False,
                            "is_brain": False,
                            "is_psycho": False,
                            "is_drug": False,
                        }
                        flags[category_col] = True
                        
                        new_record = SecondaryArticle(
                            pmid=pmid,
                            group_no=0,  # Unassigned
                            **flags,
                            pdf_exists=False,
                            created_at=datetime.utcnow().isoformat(),
                            updated_at=datetime.utcnow().isoformat(),
                        )
                        session.add(new_record)
                        created += 1
                        if created <= 5:
                            print(f"  Created: {pmid} (set {category_col}=True)")
                
                if len(missing_pmids) > 5:
                    print(f"  ... and {len(missing_pmids) - 5} more for {category}")
            
            # Commit changes
            session.commit()
            
            print(f"\n{'='*70}")
            print(f"Results:")
            print(f"  Created: {created} new SecondaryArticle records")
            print(f"  Updated: {updated} existing records (only category flags)")
            print(f"  Total:   {created + updated} changes")
            print(f"{'='*70}\n")
        
        else:
            print("\nNo action taken. Use --dry-run to preview or --create-missing to commit.")


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile secondary candidates: upsert missing PMIDs safely"
    )
    parser.add_argument('--physical', required=True, help='Physical category CSV')
    parser.add_argument('--brain', required=True, help='Brain category CSV')
    parser.add_argument('--psycho', required=True, help='Psycho category CSV')
    parser.add_argument('--database-url', help='Override DATABASE_URL')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without committing'
    )
    parser.add_argument(
        '--create-missing',
        action='store_true',
        help='Create/update missing records in DB'
    )
    parser.add_argument(
        '--only-missing',
        action='store_true',
        help='(Deprecated) Same as default behavior'
    )
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.create_missing:
        print("ERROR: Must specify --dry-run or --create-missing")
        sys.exit(1)
    
    reconcile(
        physical_csv=args.physical,
        brain_csv=args.brain,
        psycho_csv=args.psycho,
        database_url=args.database_url,
        dry_run=args.dry_run,
        create_missing=args.create_missing,
        only_missing=args.only_missing,
    )


if __name__ == '__main__':
    main()
