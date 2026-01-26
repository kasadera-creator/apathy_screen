#!/usr/bin/env python
"""
verify_secondary_display.py

Verifies that the /secondary display counts match the CSV totals.
Simulates the exact query logic used in /secondary endpoint.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlmodel import Session, create_engine, select
from sqlalchemy import func
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

def verify_display_counts(database_url=None):
    """Verify /secondary display counts match expectations."""
    db_url = database_url or DATABASE_URL
    
    print(f"\n{'='*70}")
    print(f"Verification: /secondary Display Counts")
    print(f"{'='*70}\n")
    print(f"Database: {db_url}\n")
    
    engine = create_engine(db_url, echo=False)
    
    with Session(engine) as session:
        groups = ["physical", "brain", "psycho", "drug"]
        expected_totals = {
            "physical": 314,
            "brain": 879,
            "psycho": 344,
            "drug": 0,  # No drug CSV provided yet
        }
        
        print(f"{'Category':<12} {'Expected':<12} {'Display':<12} {'Match':<8}")
        print(f"{'-'*50}")
        
        for g in groups:
            col = getattr(SecondaryArticle, f"is_{g}")
            total = session.exec(
                select(func.count(SecondaryArticle.id)).where(col == True)
            ).one()
            total = total or 0
            
            expected = expected_totals.get(g, 0)
            match = "✅" if total == expected else "❌"
            
            print(f"{g:<12} {expected:<12} {total:<12} {match:<8}")
    
    print(f"\n{'='*70}\n")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--database-url', help='Override DATABASE_URL')
    args = parser.parse_args()
    
    verify_display_counts(database_url=args.database_url)
