import sqlite3

from perfume_trend_sdk.utils.normalization import normalize_text

DB_PATH = "perfume_trend_sdk/db/perfume.db"

NEW_BRANDS = [
    ("Mancera", "mancera"),
    ("Lattafa", "lattafa"),
    ("Gucci", "gucci"),
    ("Rasasi", "rasasi"),
    ("Forte Series", "forte series"),  # provisional
]

NEW_PERFUMES = [
    ("Gucci", "Gucci Flora Gorgeous Gardenia"),
    ("Lattafa", "Lattafa Love"),
    ("Rasasi", "Hawas"),
]

NEW_ALIASES = [
    # Brands
    ("mancera", "brand", "Mancera"),
    ("lattafa", "brand", "Lattafa"),
    ("gucci", "brand", "Gucci"),
    ("rasasi", "brand", "Rasasi"),
    ("forte series", "brand", "Forte Series"),
    # Perfumes
    ("gucci flora gorgeous", "perfume", "Gucci Flora Gorgeous Gardenia"),
    ("gucci flora gorgeous gardenia", "perfume", "Gucci Flora Gorgeous Gardenia"),
    ("flora gorgeous", "perfume", "Gucci Flora Gorgeous Gardenia"),
    ("lattafa love", "perfume", "Lattafa Love"),
    ("hawas", "perfume", "Hawas"),
    ("rasasi hawas", "perfume", "Hawas"),
]


def seed_v2():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    brand_ids = {}
    for canonical_name, normalized_name in NEW_BRANDS:
        cursor.execute(
            "INSERT OR IGNORE INTO brands (canonical_name, normalized_name) VALUES (?, ?)",
            (canonical_name, normalized_name),
        )
        cursor.execute(
            "SELECT id FROM brands WHERE normalized_name = ?", (normalized_name,)
        )
        brand_ids[canonical_name] = cursor.fetchone()[0]

    perfume_ids = {}
    for brand_name, perfume_name in NEW_PERFUMES:
        normalized, _ = normalize_text(perfume_name)
        brand_id = brand_ids.get(brand_name)
        cursor.execute(
            "INSERT OR IGNORE INTO perfumes (brand_id, canonical_name, normalized_name) VALUES (?, ?, ?)",
            (brand_id, perfume_name, normalized),
        )
        cursor.execute(
            "SELECT id FROM perfumes WHERE normalized_name = ?", (normalized,)
        )
        perfume_ids[perfume_name] = cursor.fetchone()[0]

    for alias_text, entity_type, canonical_name in NEW_ALIASES:
        normalized_alias, _ = normalize_text(alias_text)

        if entity_type == "brand":
            cursor.execute(
                "SELECT id FROM brands WHERE canonical_name = ?", (canonical_name,)
            )
        else:
            cursor.execute(
                "SELECT id FROM perfumes WHERE canonical_name = ?", (canonical_name,)
            )
        row = cursor.fetchone()
        entity_id = row[0] if row else 0

        cursor.execute(
            """
            INSERT OR IGNORE INTO aliases
                (alias_text, normalized_alias_text, entity_type, entity_id, match_type, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (alias_text, normalized_alias, entity_type, entity_id, "manual", 1.0),
        )

    conn.commit()
    conn.close()
    print(f"seed_v2 done: {len(NEW_BRANDS)} brands, {len(NEW_PERFUMES)} perfumes, {len(NEW_ALIASES)} aliases")


if __name__ == "__main__":
    seed_v2()
