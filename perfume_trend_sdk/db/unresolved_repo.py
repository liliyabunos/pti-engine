import sqlite3

DB_PATH = "perfume_trend_sdk/db/perfume.db"


def insert_unresolved(mention_id, candidate, reason="low_confidence"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO unresolved (mention_id, candidate_text, reason)
        VALUES (?, ?, ?)
        """,
        (mention_id, candidate, reason),
    )

    conn.commit()
    conn.close()
