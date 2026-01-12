import argparse
import csv
import os
from pathlib import Path
from sqlmodel import Session, select
from datetime import datetime

from ..models import SecondaryArticle, Article, SecondaryReview, User
from ..main import engine, get_year_min


def upsert_from_list(pmids, pdf_dir=None, source_filename: str | None = None):
    created = 0
    updated = 0
    total_rows = 0
    valid_count = 0
    skipped = {}
    skipped_examples = []

    # detect file-based category hints
    src = source_filename.lower() if source_filename else ""
    force_flags = {
        'is_physical': 'physical' in src,
        'is_brain': 'brain' in src,
        'is_psycho': 'psycho' in src or 'psych' in src,
        'is_drug': 'drug' in src,
    }

    normalized_pmids = []

    with Session(engine) as session:
        for idx, raw in enumerate(pmids, start=1):
            total_rows += 1
            pmid_str = None

            # Normalization rules
            if raw is None:
                reason = 'none'
                skipped[reason] = skipped.get(reason, 0) + 1
                if len(skipped_examples) < 10:
                    skipped_examples.append((idx, raw, type(raw).__name__))
                continue
            if isinstance(raw, float):
                # handle NaN
                if raw != raw:
                    reason = 'nan'
                    skipped[reason] = skipped.get(reason, 0) + 1
                    if len(skipped_examples) < 10:
                        skipped_examples.append((idx, raw, type(raw).__name__))
                    continue
                pmid_str = str(int(raw))
            elif isinstance(raw, int):
                pmid_str = str(raw)
            else:
                pmid_str = str(raw).strip()

            if not pmid_str:
                reason = 'empty'
                skipped[reason] = skipped.get(reason, 0) + 1
                if len(skipped_examples) < 10:
                    skipped_examples.append((idx, raw, type(raw).__name__))
                continue

            # final check: must be digits
            if not pmid_str.isdigit():
                reason = 'non-numeric'
                skipped[reason] = skipped.get(reason, 0) + 1
                if len(skipped_examples) < 10:
                    skipped_examples.append((idx, raw, type(raw).__name__))
                continue

            # now valid
            valid_count += 1
            pmid_i = int(pmid_str)
            normalized_pmids.append(pmid_i)

            sec = session.exec(select(SecondaryArticle).where(SecondaryArticle.pmid == pmid_i)).first()

            # Inspect Article to set category flags when possible
            art = session.exec(select(Article).where(Article.pmid == pmid_i)).first()
            is_physical = False; is_brain = False; is_psycho = False; is_drug = False
            if art:
                is_physical = getattr(art, 'final_cat_physical', False) or getattr(art, 'cat_physical', False)
                is_brain = getattr(art, 'final_cat_brain', False) or getattr(art, 'cat_brain', False)
                is_psycho = getattr(art, 'final_cat_psycho', False) or getattr(art, 'cat_psycho', False)
                is_drug = getattr(art, 'final_cat_drug', False) or getattr(art, 'cat_drug', False)

            # apply file-based forcing flags (ensure True if present in filename)
            if force_flags.get('is_physical'):
                is_physical = True
            if force_flags.get('is_brain'):
                is_brain = True
            if force_flags.get('is_psycho'):
                is_psycho = True
            if force_flags.get('is_drug'):
                is_drug = True

            pdf_exists = False
            if pdf_dir:
                p = Path(pdf_dir) / f"{pmid_i}.pdf"
                pdf_exists = p.exists()

            if sec:
                sec.is_physical = bool(is_physical)
                sec.is_brain = bool(is_brain)
                sec.is_psycho = bool(is_psycho)
                sec.is_drug = bool(is_drug)
                sec.pdf_exists = bool(pdf_exists)
                sec.updated_at = datetime.utcnow().isoformat()
                session.add(sec)
                updated += 1
            else:
                sec = SecondaryArticle(pmid=pmid_i, is_physical=is_physical, is_brain=is_brain, is_psycho=is_psycho, is_drug=is_drug, pdf_exists=bool(pdf_exists), created_at=datetime.utcnow().isoformat(), updated_at=datetime.utcnow().isoformat())
                session.add(sec)
                created += 1
        session.commit()

    # debug output for skipped examples
    if skipped_examples:
        print("Skipped examples (first up to 10):")
        for ex in skipped_examples:
            print(f"  row={ex[0]} raw={ex[1]!r} type={ex[2]}")

    # final summary will be printed by caller; return normalized pmids for further processing
    return created, updated, total_rows, valid_count, skipped, normalized_pmids


def create_reviews_for_pmids(pmids, reviewers_per_group=2):
    """Create SecondaryReview rows for each pmid and each active category group.
    Assign to up to `reviewers_per_group` users from the matching numeric group_no.
    Group mapping: physical->1, brain->2, psycho->3, drug->4
    """
    GROUP_MAP = {"physical": 1, "brain": 2, "psycho": 3, "drug": 4}
    created = 0
    with Session(engine) as session:
        for pmid in pmids:
            try:
                pmid_i = int(pmid)
            except Exception:
                continue
            sec = session.exec(select(SecondaryArticle).where(SecondaryArticle.pmid == pmid_i)).first()
            if not sec:
                continue
            active_groups = [g for g in GROUP_MAP.keys() if getattr(sec, f"is_{g}", False)]
            for g in active_groups:
                gno = GROUP_MAP[g]
                users = session.exec(select(User).where(User.group_no == gno).order_by(User.id)).all()
                users = users[:reviewers_per_group]
                for u in users:
                    exists = session.exec(select(SecondaryReview).where((SecondaryReview.pmid == pmid_i) & (SecondaryReview.group == g) & (SecondaryReview.reviewer_id == u.id))).first()
                    if not exists:
                        rev = SecondaryReview(pmid=pmid_i, group=g, reviewer_id=u.id, decision="pending", updated_at=datetime.utcnow().isoformat())
                        session.add(rev)
                        created += 1
        session.commit()
    return created


def load_input(path):
    path = Path(path)
    if not path.exists():
        return []
    if path.suffix.lower() in ['.csv']:
        rows = []
        with open(path, newline='', encoding='utf-8') as fh:
            reader = csv.DictReader(fh)
            if 'pmid' in reader.fieldnames:
                for r in reader:
                    rows.append(r.get('pmid'))
            else:
                # fallback: first column
                for r in reader:
                    vals = list(r.values())
                    if vals:
                        rows.append(vals[0])
        return rows
    else:
        # txt with one pmid per line
        with open(path, encoding='utf-8') as fh:
            return [l.strip() for l in fh if l.strip()]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', '-i', required=True, help='Input txt or csv with pmid list')
    parser.add_argument('--pdf-dir', help='Directory where {pmid}.pdf files reside (overrides SECONDARY_PDF_DIR env)')
    parser.add_argument('--create-reviews', action='store_true', help='Create SecondaryReview rows for group reviewers for each pmid')
    parser.add_argument('--reviewers-per-group', type=int, default=2, help='Number of reviewers per group to assign when --create-reviews')
    args = parser.parse_args()
    pdf_dir = args.pdf_dir or os.environ.get('SECONDARY_PDF_DIR')
    pmids = load_input(args.input)
    c, u, total_rows, valid_count, skipped, normalized_pmids = upsert_from_list(pmids, pdf_dir=pdf_dir, source_filename=args.input)

    print(f"total_rows={total_rows}")
    print(f"valid_pmids={valid_count}")
    print(f"created={c} updated={u}")
    print(f"skipped={skipped}")

    if args.create_reviews:
        added = create_reviews_for_pmids(normalized_pmids, reviewers_per_group=args.reviewers_per_group)
        print(f"secondary_reviews_created={added}")
