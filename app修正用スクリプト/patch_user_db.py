import sqlite3
from pathlib import Path

DEFAULT_DB = "sqlite:////home/yvofxbku/apathy_data/apathy_screen.db"
DATABASE_URL = os.getenv("DATABASE_URL") or DEFAULT_DB
DB_PATH = None
if DATABASE_URL.startswith("sqlite://"):
    DB_PATH = Path(DATABASE_URL.split("sqlite://", 1)[1]).expanduser()
else:
    raise SystemExit("This script requires DATABASE_URL pointing to a sqlite DB")

def patch_user_table():
    print(f"Connecting to database: {DB_PATH}")
    if not DB_PATH.exists():
        print("Error: Database file not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # is_admin カラムを追加 (デフォルト0=False)
        cursor.execute("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0")
        conn.commit()
        print("Success: Added 'is_admin' column to 'user' table.")
    except sqlite3.OperationalError as e:
        print(f"Info: {e} (Column might already exist)")

    # ID=1 (user1) を管理者に設定
    cursor.execute("UPDATE user SET is_admin = 1 WHERE id = 1")
    conn.commit()
    print("Success: Set user ID=1 as Admin.")

    conn.close()

if __name__ == "__main__":
    patch_user_table()