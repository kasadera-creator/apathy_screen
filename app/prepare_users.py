from pathlib import Path
from sqlmodel import Session, create_engine, delete

from .models import User
from passlib.context import CryptContext

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = "sqlite:////home/yvofxbku/apathy_data/apathy_screen.db"
DB_URL = os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_pw(pw: str) -> str:
    return pwd_context.hash(pw)


def main():
    engine = create_engine(DB_URL, echo=False)

    users = [
        ("user1", "password1", 1),
        ("user2", "password2", 1),
        ("user3", "password3", 2),
        ("user4", "password4", 2),
        ("user5", "password5", 3),
        ("user6", "password6", 3),
        ("user7", "password7", 4),
        ("user8", "password8", 4),
    ]

    with Session(engine) as session:
        # 既存ユーザーを全削除
        session.exec(delete(User))

        # 新しいユーザーを追加
        for uname, pw, grp in users:
            u = User(
                username=uname,
                password_hash=hash_pw(pw),
                group_no=grp,
            )
            session.add(u)

        session.commit()


if __name__ == "__main__":
    main()
