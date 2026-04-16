import psycopg2
import os

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
SELECT setval(
    pg_get_serial_sequence('resolved_signals', 'id'),
    COALESCE((SELECT MAX(id) FROM resolved_signals), 1)
);
""")

print("sequence reset OK")

conn.close()
