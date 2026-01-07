import sqlite3
from pathlib import Path

# データベースファイルのパス
DB_PATH = Path("apathy_screening.db")

def patch_database():
    print(f"Connecting to database: {DB_PATH}")
    
    if not DB_PATH.exists():
        print("Error: Database file not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    table_name = "article"
    column_name = "fulltext_summary_ja"
    column_type = "TEXT"

    try:
        # カラムが存在するかチェック
        cursor.execute(f"SELECT {column_name} FROM {table_name} LIMIT 1")
        print(f"OK: カラム '{column_name}' は既に存在します。")
    except sqlite3.OperationalError:
        # カラムがない場合のエラーをキャッチして追加
        print(f"Fixing: テーブル '{table_name}' にカラム '{column_name}' を追加します...")
        try:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            conn.commit()
            print(" -> 成功しました。")
        except Exception as e:
            print(f" -> 失敗しました: {e}")

    conn.close()
    print("処理が完了しました。")

if __name__ == "__main__":
    patch_database()