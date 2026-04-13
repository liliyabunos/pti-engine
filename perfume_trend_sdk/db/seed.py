import sqlite3

from perfume_trend_sdk.utils.normalization import normalize_text

DB_PATH = "perfume_trend_sdk/db/perfume.db"


def seed():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # BRAND
    cursor.execute(
        "INSERT INTO brands (canonical_name, normalized_name) VALUES (?, ?)",
        ("Maison Francis Kurkdjian", "maison francis kurkdjian"),
    )
    brand_id = cursor.lastrowid

    # PERFUME
    cursor.execute(
        "INSERT INTO perfumes (brand_id, canonical_name, normalized_name) VALUES (?, ?, ?)",
        (brand_id, "Baccarat Rouge 540", "baccarat rouge 540"),
    )
    perfume_id = cursor.lastrowid

    aliases = [
        "baccarat rouge 540",
        "baccarat 540",
        "br540",
        "baccarat rouge",
        "баккара 540",
    ]

    for alias in aliases:
        norm, _ = normalize_text(alias)
        cursor.execute(
            "INSERT INTO aliases (alias_text, normalized_alias_text, entity_type, entity_id, match_type, confidence) VALUES (?, ?, ?, ?, ?, ?)",
            (alias, norm, "perfume", perfume_id, "manual", 1.0),
        )

    conn.commit()
    conn.close()
    print("Seed data inserted")


if __name__ == "__main__":
    seed()
