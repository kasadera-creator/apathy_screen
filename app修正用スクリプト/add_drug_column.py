import sqlite3
import os
from pathlib import Path

DEFAULT_DB = "sqlite:////home/yvofxbku/apathy_data/apathy_screen.db"
DATABASE_URL = os.getenv("DATABASE_URL") or DEFAULT_DB
DB_PATH = None
if DATABASE_URL.startswith("sqlite://"):
    DB_PATH = Path(DATABASE_URL.split("sqlite://", 1)[1]).expanduser()
else:
    raise SystemExit("This script requires DATABASE_URL pointing to a sqlite DB")

def add_drug_column():
    print(f"Connecting to database: {DB_PATH}")
    if not DB_PATH.exists():
        print("Error: Database file not found!")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    column_name = "cat_drug"
    column_type = "BOOLEAN DEFAULT 0"
    
    try:
        cursor.execute(f"ALTER TABLE screeningdecision ADD COLUMN {column_name} {column_type}")
        print(f"Success: Added '{column_name}' column.")
    except sqlite3.OperationalError as e:
        print(f"Info: {e} (Column '{column_name}' might already exist)")
            
    conn.commit()
    conn.close()
    print("Database patch completed.")

if __name__ == "__main__":
    add_drug_column()