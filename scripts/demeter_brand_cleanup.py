"""Clean Demeter brand ts/signals after SIG-QA1-BATCH2 repair.
The brand is stored as 'Demeter Fragrance Library / The Library Of Fragrance'.
"""
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.autocommit = False
cur = conn.cursor()

# Find Demeter brand entity
cur.execute(
    "SELECT id, brand_name FROM entity_market "
    "WHERE brand_name ILIKE '%demeter%' AND entity_type = 'brand'"
)
rows = cur.fetchall()
print("Demeter brand entities found:")
for r in rows:
    print(f"  {r}")

if not rows:
    print("No Demeter brand entity found — nothing to clean")
    conn.rollback()
    conn.close()
    exit(0)

# Check for other legitimate tracked perfumes under this brand
cur.execute(
    "SELECT canonical_name, id FROM entity_market "
    "WHERE brand_name ILIKE '%demeter%' AND entity_type = 'perfume' "
    "ORDER BY canonical_name"
)
perfumes = cur.fetchall()
print("\nDemeter perfumes in entity_market:")
for p in perfumes:
    print(f"  {p}")

# For each brand entity, check ts/signals and clean
apply_mode = os.environ.get('APPLY_MODE', 'false') == 'true'
mode = "APPLY" if apply_mode else "DRY-RUN"
print(f"\n[demeter-brand-cleanup] {mode}")

for brand_row in rows:
    eid = str(brand_row[0])
    brand_name = brand_row[1]
    cur.execute("SELECT COUNT(*) FROM entity_timeseries_daily WHERE entity_id = %s", (eid,))
    ts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM signals WHERE entity_id = %s", (eid,))
    sigs = cur.fetchone()[0]
    print(f"  {brand_name}: ts={ts} signals={sigs}")
    if apply_mode:
        cur.execute("DELETE FROM entity_timeseries_daily WHERE entity_id = %s", (eid,))
        cur.execute("DELETE FROM signals WHERE entity_id = %s", (eid,))
        print(f"    -> deleted ts={cur.rowcount}")

if apply_mode:
    conn.commit()
    print("\nDemeter brand cleanup committed.")
else:
    conn.rollback()
    print("\nDry-run complete — set APPLY_MODE=true to execute.")

conn.close()
