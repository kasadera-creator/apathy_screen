import argparse
from sqlmodel import Session, create_engine, select, SQLModel
from passlib.context import CryptContext
from pathlib import Path
import os

from ..models import User
import os
from pathlib import Path


def _database_url_from_env_or_exit():
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL environment variable is required")
    return DATABASE_URL


def get_engine():
    DATABASE_URL = _database_url_from_env_or_exit()
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
    # Only run create_all when explicitly enabled
    if os.getenv("AUTO_CREATE_TABLES", "0") == "1":
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
