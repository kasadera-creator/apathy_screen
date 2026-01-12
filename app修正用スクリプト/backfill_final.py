"""
Backfill `Article.final_*` fields from existing `ScreeningDecision` rows.

Usage:
  python backfill_final.py        # dry-run (prints changes)
  python backfill_final.py --apply

Logic:
  - For each article with at least two reviewer rows: if r1.decision == r2.decision (not None), set Article.final_decision to that value.
  - For final category flags, set True only when both reviewers have the same True value for that category.
  - Set `finalized_at` to current ISO datetime when applying.

This script is conservative: it only writes when `--apply` is provided.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime

from sqlmodel import Session, create_engine, select

# Import models and DATABASE_URL from app main so we use same DB
from app.models import Article, ScreeningDecision
import os

# Use unified DATABASE_URL from environment or production default
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:////home/yvofxbku/apathy_data/apathy_screen.db"


def gather_decisions(session: Session):
    stmt = select(ScreeningDecision).order_by(ScreeningDecision.article_id, ScreeningDecision.user_id)
    rows = session.exec(stmt).all()
    by_article = defaultdict(list)
    for sd in rows:
        by_article[sd.article_id].append(sd)
    return by_article


def backfill(engine_url: str, apply: bool = False):
    engine = create_engine(engine_url, echo=False)
    changes = []
    with Session(engine) as session:
        by_article = gather_decisions(session)
        for art_id, sd_list in by_article.items():
            if not sd_list:
                continue
            if len(sd_list) < 2:
                # skip single-reviewer items for conservative backfill
                continue

            sd1 = sd_list[0]
            sd2 = sd_list[1]

            # decisions
            final_decision = None
            if sd1.decision is not None and sd2.decision is not None and sd1.decision == sd2.decision:
                final_decision = sd1.decision

            # categories: agree only when both True
            final_cat_physical = bool(sd1.cat_physical and sd2.cat_physical)
            final_cat_brain = bool(sd1.cat_brain and sd2.cat_brain)
            final_cat_psycho = bool(sd1.cat_psycho and sd2.cat_psycho)
            final_cat_drug = bool(sd1.cat_drug and sd2.cat_drug)

            art = session.get(Article, art_id)
            if art is None:
                continue

            artifact = {"article_id": art_id}
            changed = False

            if final_decision is not None and getattr(art, "final_decision", None) != final_decision:
                artifact["final_decision"] = (getattr(art, "final_decision", None), final_decision)
                art.final_decision = final_decision
                changed = True

            # categories
            for field, val in (
                ("final_cat_physical", final_cat_physical),
                ("final_cat_brain", final_cat_brain),
                ("final_cat_psycho", final_cat_psycho),
                ("final_cat_drug", final_cat_drug),
            ):
                if getattr(art, field, False) != val:
                    artifact[field] = (getattr(art, field, False), val)
                    setattr(art, field, val)
                    changed = True

            if changed:
                artifact["finalized_at"] = (getattr(art, "finalized_at", None), datetime.utcnow().isoformat())
                if apply:
                    art.finalized_at = datetime.utcnow().isoformat()
                    session.add(art)
                changes.append(artifact)

        if apply and changes:
            session.commit()

    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply changes to the database")
    args = parser.parse_args()

    print("Dry-run mode. Use --apply to write changes.")
    changes = backfill(DATABASE_URL, apply=args.apply)
    if not changes:
        print("No changes detected.")
        return

    print(f"Found {len(changes)} articles to update:")
    for c in changes[:200]:
        print(c)

    if not args.apply:
        print("Run with --apply to persist these changes.")
    else:
        print("Applied changes to the database.")


if __name__ == '__main__':
    main()
