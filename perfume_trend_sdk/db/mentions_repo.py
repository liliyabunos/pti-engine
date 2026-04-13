import sqlite3

DB_PATH = "perfume_trend_sdk/db/perfume.db"


def insert_mention(raw_text, normalized_text, source, weight=1.0):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO mentions (raw_text, normalized_text, source, weight) VALUES (?, ?, ?, ?)",
        (raw_text, normalized_text, source, weight),
    )

    mention_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return mention_id
