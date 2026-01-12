"""DB setup helper.

Usage examples:
  python -m app.scripts.setup_db --create-tables
  python -m app.scripts.setup_db --create-user iwata password8 --is-admin
  python -m app.scripts.setup_db --import-candidates path/to/file.txt --pdf-dir /path/to/pdfs --create-reviews
"""
import argparse
from pathlib import Path
import os
import importlib
from sqlmodel import SQLModel, Session, create_engine, select
from passlib.context import CryptContext
from datetime import datetime


def get_engine():
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    DB_PATH = BASE_DIR / "apathy_screening.db"
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    return create_engine(DATABASE_URL, echo=False)


def create_tables(engine):
    SQLModel.metadata.create_all(engine)
    print("Created/verified tables via SQLModel.metadata.create_all")


def create_user(engine, username, password, group_no=1, is_admin=False):
    pwd_context = CryptContext(schemes=["pbkdf2_sha256", "sha256_crypt"], deprecated="auto")
    pw_hash = pwd_context.hash(password)
    # import models lazily to avoid circular imports
    from app.models import User
    with Session(engine) as session:
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing:
            existing.password_hash = pw_hash
            existing.group_no = group_no
            existing.is_admin = is_admin
            session.add(existing)
            session.commit()
            print(f"Updated user '{username}'")
        else:
            user = User(username=username, password_hash=pw_hash, group_no=group_no, is_admin=is_admin)
            session.add(user)
            session.commit()
            print(f"Created user '{username}'")


def import_candidates(engine, path, pdf_dir=None, create_reviews=False, reviewers_per_group=2):
    mod = importlib.import_module('app.scripts.import_secondary_candidates')
    pmids = mod.load_input(path)
    c, u = mod.upsert_from_list(pmids, pdf_dir=pdf_dir)
    print(f"SecondaryArticle: created={c} updated={u}")
    if create_reviews:
        added = mod.create_reviews_for_pmids(pmids, reviewers_per_group=reviewers_per_group)
        print(f"SecondaryReview rows created: {added}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--create-tables', action='store_true')
    parser.add_argument('--create-user', nargs=2, metavar=('USERNAME', 'PASSWORD'))
    parser.add_argument('--group-no', type=int, default=1)
    parser.add_argument('--is-admin', action='store_true')
    parser.add_argument('--import-candidates', help='Path to txt/csv with pmids')
    parser.add_argument('--pdf-dir', help='PDF directory path for existence checks')
    parser.add_argument('--create-reviews', action='store_true')
    parser.add_argument('--reviewers-per-group', type=int, default=2)
    args = parser.parse_args()

    engine = get_engine()

    if args.create_tables:
        create_tables(engine)

    if args.create_user:
        username, password = args.create_user
        create_user(engine, username, password, group_no=args.group_no, is_admin=args.is_admin)

    if args.import_candidates:
        import_candidates(engine, args.import_candidates, pdf_dir=args.pdf_dir, create_reviews=args.create_reviews, reviewers_per_group=args.reviewers_per_group)

    if not (args.create_tables or args.create_user or args.import_candidates):
        parser.print_help()


if __name__ == '__main__':
    main()
