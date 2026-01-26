#!/usr/bin/env python
"""
audit_secondary_candidates.py

Audits discrepancies between CSV candidate lists and DB SecondaryArticle records.

Generates:
  - Console report with counts and missing/extra PMID summary
  - data/audit_secondary_report.json with detailed stats
  - data/missing_pmids_*.csv for each category with missing PMIDs

Usage:
    python -m app.scripts.audit_secondary_candidates \
      --physical /path/to/category_physical_allgroups.csv \
      --brain /path/to/category_brain_allgroups.csv \
      --psycho /path/to/category_psycho_allgroups.csv \
      [--database-url sqlite:///...] \
      [--output-dir data/]
"""

import sys
import argparse
import csv
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlmodel import Session, create_engine, select
from sqlalchemy import func
from app.models import SecondaryArticle, SecondaryReview
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
    """Load PMID set from CSV file.
    
    Expects 'pmid' column. Handles:
    - Empty values, NaN, None → skipped
    - Float → converted to int
    - Whitespace stripped
    - Duplicates removed
    - Returns only valid integers
    """
    pmids = set()
    skipped = defaultdict(int)
    
    if not Path(csv_path).exists():
        print(f"  ERROR: CSV not found: {csv_path}")
        return pmids, skipped
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or 'pmid' not in reader.fieldnames:
            print(f"  ERROR: 'pmid' column not found in {csv_path}")
            return pmids, skipped
        
        for row_idx, row in enumerate(reader, start=2):  # start=2 because header is row 1
            raw_pmid = row.get('pmid', '').strip()
            
            # Try to parse
            try:
                if not raw_pmid or raw_pmid.lower() in ['none', 'nan', '']:
                    skipped['empty'] += 1
                    continue
                
                # Handle float (e.g., "123.0")
                if '.' in raw_pmid:
                    pmid_int = int(float(raw_pmid))
                else:
                    pmid_int = int(raw_pmid)
                
                if pmid_int > 0:
                    pmids.add(pmid_int)
                else:
                    skipped['negative'] += 1
            except (ValueError, TypeError) as e:
                skipped['invalid'] += 1
    
    return pmids, skipped


def get_db_pmids_for_category(session, category: str) -> set:
    """Get PMIDs from DB where is_{category} == True."""
    col = getattr(SecondaryArticle, f"is_{category}")
    rows = session.exec(select(SecondaryArticle.pmid).where(col == True)).all()
    return set(rows) if rows else set()


def get_reviewed_pmids(session, category: str) -> set:
    """Get PMIDs that have been reviewed in this category."""
    rows = session.exec(
        select(SecondaryReview.pmid).where(SecondaryReview.group == category)
    ).all()
    return set(rows) if rows else set()


def get_pending_pmids(session, category: str) -> set:
    """Get PMIDs with pending reviews."""
    rows = session.exec(
        select(SecondaryReview.pmid).where(
            (SecondaryReview.group == category) & 
            (SecondaryReview.decision == "pending")
        )
    ).all()
    return set(rows) if rows else set()


def audit_category(session, category: str, csv_pmids: set) -> dict:
    """Audit one category: physical, brain, psycho, drug."""
    db_pmids = get_db_pmids_for_category(session, category)
    reviewed_pmids = get_reviewed_pmids(session, category)
    pending_pmids = get_pending_pmids(session, category)
    
    missing = csv_pmids - db_pmids  # In CSV but not in DB
    extra = db_pmids - csv_pmids    # In DB but not in CSV
    
    # Additional analysis
    reviewed_and_missing = reviewed_pmids & missing  # Already reviewed but missing from candidates?
    
    report = {
        "category": category,
        "csv_count": len(csv_pmids),
        "db_count": len(db_pmids),
        "reviewed_count": len(reviewed_pmids),
        "pending_count": len(pending_pmids),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "reviewed_and_missing": len(reviewed_and_missing),
        
        # Details (first 50)
        "missing_pmids_sample": sorted(list(missing))[:50],
        "extra_pmids_sample": sorted(list(extra))[:50],
        "all_missing_pmids": sorted(list(missing)),  # Full list for export
        "all_extra_pmids": sorted(list(extra)),
    }
    
    return report


def run_audit(physical_csv, brain_csv, psycho_csv, database_url=None, output_dir="data"):
    """Main audit logic."""
    db_url = database_url or DATABASE_URL
    print(f"\n{'='*70}")
    print(f"Secondary Candidates Audit")
    print(f"{'='*70}")
    print(f"Database: {db_url}")
    print(f"Timestamp: {datetime.now().isoformat()}\n")
    
    # Load CSVs
    print("Loading CSV files...")
    csv_physical, skip_phys = load_pmids_from_csv(physical_csv)
    csv_brain, skip_brain = load_pmids_from_csv(brain_csv)
    csv_psycho, skip_psych = load_pmids_from_csv(psycho_csv)
    
    print(f"  Physical: {len(csv_physical)} valid PMIDs (skipped: {skip_phys})")
    print(f"  Brain: {len(csv_brain)} valid PMIDs (skipped: {skip_brain})")
    print(f"  Psycho: {len(csv_psycho)} valid PMIDs (skipped: {skip_psych})")
    
    # Connect to DB
    engine = create_engine(db_url, echo=False)
    print(f"\nConnecting to DB: {engine.url}")
    
    with Session(engine) as session:
        reports = {}
        
        # Audit each category
        for category, csv_pmids in [
            ("physical", csv_physical),
            ("brain", csv_brain),
            ("psycho", csv_psycho),
        ]:
            print(f"\nAuditing {category}...")
            report = audit_category(session, category, csv_pmids)
            reports[category] = report
            
            # Console output
            print(f"  CSV count:        {report['csv_count']:4d}")
            print(f"  DB count:         {report['db_count']:4d}")
            print(f"  Reviewed:         {report['reviewed_count']:4d}")
            print(f"  Pending:          {report['pending_count']:4d}")
            print(f"  ⚠️  Missing:       {report['missing_count']:4d}")
            print(f"  Extra:            {report['extra_count']:4d}")
            if report['reviewed_and_missing'] > 0:
                print(f"  ⚠️  Reviewed+Missing: {report['reviewed_and_missing']:4d} (ALERT!)")
            
            # Sample missing PMIDs
            if report['missing_pmids_sample']:
                sample_str = ", ".join(str(p) for p in report['missing_pmids_sample'][:10])
                print(f"  Missing sample: {sample_str}{'...' if len(report['missing_pmids_sample']) > 10 else ''}")
    
    # Summary table
    print(f"\n{'='*70}")
    print(f"Summary")
    print(f"{'='*70}")
    print(f"{'Category':<12} {'CSV':<8} {'DB':<8} {'Missing':<8} {'Extra':<8}")
    print(f"{'-'*50}")
    for cat in ["physical", "brain", "psycho"]:
        r = reports[cat]
        print(f"{cat:<12} {r['csv_count']:<8} {r['db_count']:<8} {r['missing_count']:<8} {r['extra_count']:<8}")
    
    # Save JSON report
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare JSON (remove full lists for readability)
    json_report = {}
    for cat, rep in reports.items():
        json_report[cat] = {
            "csv_count": rep["csv_count"],
            "db_count": rep["db_count"],
            "reviewed_count": rep["reviewed_count"],
            "pending_count": rep["pending_count"],
            "missing_count": rep["missing_count"],
            "extra_count": rep["extra_count"],
            "missing_pmids_sample": rep["missing_pmids_sample"],
            "extra_pmids_sample": rep["extra_pmids_sample"],
        }
    
    report_path = output_dir / "audit_secondary_report.json"
    with open(report_path, 'w') as f:
        json.dump(json_report, f, indent=2)
    print(f"\n✓ Report saved: {report_path}")
    
    # Export missing PMIDs as CSVs
    for cat in ["physical", "brain", "psycho"]:
        missing_pmids = reports[cat]["all_missing_pmids"]
        if missing_pmids:
            csv_path = output_dir / f"missing_pmids_{cat}.csv"
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["pmid"])
                for pmid in missing_pmids:
                    writer.writerow([pmid])
            print(f"✓ Missing PMIDs exported: {csv_path} ({len(missing_pmids)} rows)")
    
    print(f"\n{'='*70}")
    return reports


def main():
    parser = argparse.ArgumentParser(
        description="Audit secondary candidates: compare CSV vs DB"
    )
    parser.add_argument('--physical', required=True, help='Physical category CSV')
    parser.add_argument('--brain', required=True, help='Brain category CSV')
    parser.add_argument('--psycho', required=True, help='Psycho category CSV')
    parser.add_argument('--database-url', help='Override DATABASE_URL')
    parser.add_argument('--output-dir', default='data', help='Output directory for reports')
    
    args = parser.parse_args()
    
    run_audit(
        physical_csv=args.physical,
        brain_csv=args.brain,
        psycho_csv=args.psycho,
        database_url=args.database_url,
        output_dir=args.output_dir,
    )


if __name__ == '__main__':
    main()
