import sqlite3
from pathlib import Path

DB_PATH = Path("apathy_screening.db")

def add_drug_column():
    print(f"Connecting to database: {DB_PATH}")
    if not DB_PATH.exists():
        print("Error: Database file not found!")
        return

    conn = sqlite3.connect(DB_PATH)
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