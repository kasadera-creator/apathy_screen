import sqlite3
from pathlib import Path

# データベースファイルのパス
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL environment variable is required for this script")
DB_PATH = None
if DATABASE_URL.startswith("sqlite://"):
    DB_PATH = Path(DATABASE_URL.split("sqlite://", 1)[1]).expanduser()
else:
    raise SystemExit("This script requires DATABASE_URL pointing to a sqlite DB")

def patch_database():
    print(f"Connecting to database: {DB_PATH}")
    
    if not DB_PATH.exists():
        print("Error: Database file not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Articleテーブルに fulltext_summary_ja カラムがあるか確認
        cursor.execute("SELECT fulltext_summary_ja FROM article LIMIT 1")
        print("カラム 'fulltext_summary_ja' は既に存在します。")
    except sqlite3.OperationalError:
        # カラムがない場合のエラーをキャッチして追加処理を行う
        print("カラム 'fulltext_summary_ja' が見つかりません。追加します...")
        try:
            cursor.execute("ALTER TABLE article ADD COLUMN fulltext_summary_ja TEXT")
            conn.commit()
            print("成功: カラムを追加しました。")
        except Exception as e:
            print(f"失敗: カラムの追加に失敗しました。\n{e}")
            
    conn.close()
    print("データベースの修正が完了しました。")

if __name__ == "__main__":
    patch_database()