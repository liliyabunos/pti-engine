import sqlite3
from pathlib import Path

DB_PATH = Path("perfume_trend_sdk/db/perfume.db")
SCHEMA_PATH = Path("perfume_trend_sdk/db/schema.sql")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print("DB initialized")


if __name__ == "__main__":
    init_db()
