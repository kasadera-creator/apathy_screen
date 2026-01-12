import sqlite3
from pathlib import Path

DB_PATH = Path("apathy_screening.db")

def add_columns():
    print(f"Connecting to database: {DB_PATH}")
    if not DB_PATH.exists():
        print("Error: Database file not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    new_cols = [
        ("cat_physical", "BOOLEAN DEFAULT 0"),
        ("cat_brain", "BOOLEAN DEFAULT 0"),
        ("cat_psycho", "BOOLEAN DEFAULT 0"),
    ]
    
    for col_name, col_type in new_cols:
        try:
            cursor.execute(f"ALTER TABLE screeningdecision ADD COLUMN {col_name} {col_type}")
            print(f"Success: Added '{col_name}' column.")
        except sqlite3.OperationalError as e:
            print(f"Info: {e} (Column '{col_name}' might already exist)")
            
    conn.commit()
    conn.close()
    print("Database patch completed.")

if __name__ == "__main__":
    add_columns()