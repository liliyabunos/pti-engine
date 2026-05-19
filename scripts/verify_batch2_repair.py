import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

names = ['White Musk','Black Pepper','Apple Blossom','Bitter Orange',
         'Earl Grey','Earl Grey Tea','Black Jeans','Black Suit',
         'Green Tea','Hair Perfume','Bath & Body','Be Cool']

print("=== RS residuals (must be 0) ===")
all_pass = True
for name in names:
    cur.execute(
        "SELECT COUNT(*) FROM resolved_signals WHERE EXISTS ("
        "  SELECT 1 FROM jsonb_array_elements(resolved_entities_json::jsonb) AS elem"
        "  WHERE elem->>'canonical_name' = %s"
        ")",
        (name,)
    )
    count = cur.fetchone()[0]
    status = "OK ✓" if count == 0 else f"FAIL — {count} rows remain"
    if count != 0: all_pass = False
    print(f"  {name}: {status}")

print("\n=== entity_mentions (must be 0) ===")
cur.execute(
    "SELECT eml.canonical_name, COUNT(*) FROM entity_mentions em"
    "  JOIN entity_market eml ON eml.id = em.entity_id"
    "  WHERE eml.canonical_name = ANY(%s)"
    "  GROUP BY eml.canonical_name ORDER BY eml.canonical_name",
    (names,)
)
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  FAIL — {r[0]}: {r[1]} mentions remain")
    all_pass = False
else:
    print("  All 0 ✓")

print("\n=== entity_timeseries_daily (must be 0) ===")
cur.execute(
    "SELECT eml.canonical_name, COUNT(*) FROM entity_timeseries_daily etd"
    "  JOIN entity_market eml ON eml.id = etd.entity_id"
    "  WHERE eml.canonical_name = ANY(%s)"
    "  GROUP BY eml.canonical_name ORDER BY eml.canonical_name",
    (names,)
)
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  FAIL — {r[0]}: {r[1]} ts rows remain")
    all_pass = False
else:
    print("  All 0 ✓")

print("\n=== signals (must be 0) ===")
cur.execute(
    "SELECT eml.canonical_name, COUNT(*) FROM signals s"
    "  JOIN entity_market eml ON eml.id = s.entity_id"
    "  WHERE eml.canonical_name = ANY(%s)"
    "  GROUP BY eml.canonical_name ORDER BY eml.canonical_name",
    (names,)
)
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  FAIL — {r[0]}: {r[1]} signals remain")
    all_pass = False
else:
    print("  All 0 ✓")

print("\n=== Brand ts/signals (must be 0) ===")
brand_checks = [
    ("W.Dressroom", "W.Dressroom"),
    ("Demeter", "Demeter Fragrance Library / The Library Of Fragrance"),
    ("Auric Blends", "Auric Blends"),
    ("Zara", "Zara"),
    ("Teone Reinthal", "Teone Reinthal Natural Perfume"),
    ("Versace", "Versace"),
    ("Ramon Monegal", "Ramon Monegal"),
    ("Coty", "Coty"),
    ("Balmain", "Balmain"),
    ("Marbert", "Marbert"),
    ("Avon", "Avon"),
]
for label, brand_name in brand_checks:
    cur.execute(
        "SELECT id FROM entity_market WHERE brand_name = %s AND entity_type = 'brand' LIMIT 1",
        (brand_name,)
    )
    row = cur.fetchone()
    if not row:
        print(f"  {label}: brand entity not found (skip)")
        continue
    eid = str(row[0])
    cur.execute("SELECT COUNT(*) FROM entity_timeseries_daily WHERE entity_id = %s", (eid,))
    ts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM signals WHERE entity_id = %s", (eid,))
    sigs = cur.fetchone()[0]
    status = "OK ✓" if ts == 0 and sigs == 0 else f"ts={ts} signals={sigs}"
    print(f"  {label}: {status}")

print(f"\n{'ALL PASS ✓' if all_pass else 'SOME CHECKS FAILED'}")
conn.close()
