import argparse
from sqlmodel import Session, create_engine, select, SQLModel
from passlib.context import CryptContext
from pathlib import Path
import os

from ..models import User


def get_engine():
    # Match the main app's DB location (repository root / apathy_screening.db)
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    DB_PATH = BASE_DIR / "apathy_screening.db"
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    return create_engine(DATABASE_URL, echo=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--group-no", type=int, default=1)
    parser.add_argument("--is-admin", action="store_true")
    args = parser.parse_args()

    pwd_context = CryptContext(schemes=["pbkdf2_sha256", "sha256_crypt"], deprecated="auto")
    pw_hash = pwd_context.hash(args.password)

    engine = get_engine()
    # ensure tables exist
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        existing = session.exec(select(User).where(User.username == args.username)).first()
        if existing:
            existing.password_hash = pw_hash
            existing.group_no = args.group_no
            existing.is_admin = args.is_admin
            session.add(existing)
            session.commit()
            print(f"Updated user '{args.username}' (is_admin={args.is_admin}, group_no={args.group_no})")
        else:
            user = User(username=args.username, password_hash=pw_hash, group_no=args.group_no, is_admin=args.is_admin)
            session.add(user)
            session.commit()
            print(f"Created user '{args.username}' (is_admin={args.is_admin}, group_no={args.group_no})")


if __name__ == '__main__':
    main()
