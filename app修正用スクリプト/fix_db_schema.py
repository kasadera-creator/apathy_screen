import sqlite3
from pathlib import Path

# データベースファイルのパス
DEFAULT_DB = "sqlite:////home/yvofxbku/apathy_data/apathy_screen.db"
DATABASE_URL = os.getenv("DATABASE_URL") or DEFAULT_DB
DB_PATH = None
if DATABASE_URL.startswith("sqlite://"):
    DB_PATH = Path(DATABASE_URL.split("sqlite://", 1)[1]).expanduser()
else:
    raise SystemExit("This script requires DATABASE_URL pointing to a sqlite DB")

def fix_database():
    print(f"Connecting to database: {DB_PATH}")
    
    if not DB_PATH.exists():
        print("Error: Database file not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 追加すべきカラムのリスト (テーブル名, カラム名, 型定義)
    columns_to_add = [
        # Articleテーブル (二次スクリーニング用要約)
        ("article", "fulltext_summary_ja", "TEXT"),
        
        # ScreeningDecisionテーブル (カテゴリー分類フラグ)
        ("screeningdecision", "cat_physical", "BOOLEAN DEFAULT 0"),
        ("screeningdecision", "cat_brain", "BOOLEAN DEFAULT 0"),
        ("screeningdecision", "cat_psycho", "BOOLEAN DEFAULT 0"),
    ]

    for table, col, col_type in columns_to_add:
        try:
            # カラムが存在するかチェック
            cursor.execute(f"SELECT {col} FROM {table} LIMIT 1")
            print(f"OK: '{table}.{col}' は既に存在します。")
        except sqlite3.OperationalError:
            print(f"Fixing: '{table}.{col}' を追加します...")
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                conn.commit()
                print(" -> 成功しました。")
            except Exception as e:
                print(f" -> 失敗しました: {e}")

    conn.close()
    print("データベースの修復処理が完了しました。")

if __name__ == "__main__":
    fix_database()