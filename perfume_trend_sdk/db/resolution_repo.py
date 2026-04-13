import sqlite3

DB_PATH = "perfume_trend_sdk/db/perfume.db"


def insert_resolution(mention_id, result):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO resolutions (mention_id, entity_type, entity_id, resolution_method, confidence)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            mention_id,
            result.get("entity_type"),
            result.get("entity_id"),
            result.get("method"),
            result.get("confidence"),
        ),
    )

    conn.commit()
    conn.close()


def insert_unresolved(mention_id, candidate_text, reason):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO unresolved (mention_id, candidate_text, reason) VALUES (?, ?, ?)",
        (mention_id, candidate_text, reason),
    )

    conn.commit()
    conn.close()
