#!/usr/bin/env python3
"""Quick verification of trend_state population in production."""
import os
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

e = create_engine(url)
with e.connect() as c:
    print("=== DB distribution (rows with mention_count > 0) ===")
    for row in c.execute(text(
        "SELECT COALESCE(trend_state,'NULL') as ts, COUNT(*) as n "
        "FROM entity_timeseries_daily WHERE mention_count > 0 "
        "GROUP BY trend_state ORDER BY n DESC"
    )):
        print(f"  {row[0]:12} : {row[1]}")

    latest = c.execute(text(
        "SELECT MAX(date) FROM entity_timeseries_daily WHERE mention_count > 0"
    )).scalar()
    print(f"\nLatest active date: {latest}")

    null_count = c.execute(text(
        "SELECT COUNT(*) FROM entity_timeseries_daily "
        "WHERE date=:d AND mention_count > 0 AND trend_state IS NULL"
    ), {"d": latest}).scalar()
    total_count = c.execute(text(
        "SELECT COUNT(*) FROM entity_timeseries_daily "
        "WHERE date=:d AND mention_count > 0"
    ), {"d": latest}).scalar()
    print(f"Active rows on {latest}: {total_count} total, {null_count} still NULL")

    print(f"\nSample rows for {latest}:")
    rows = c.execute(text("""
        SELECT e.canonical_name, t.composite_market_score, t.trend_state
        FROM entity_timeseries_daily t
        JOIN entity_market e ON e.id = t.entity_id
        WHERE t.date = :d AND t.mention_count > 0
        ORDER BY t.composite_market_score DESC
        LIMIT 10
    """), {"d": latest}).fetchall()
    print(f"  {'Name':35} {'Score':8} Trend")
    for name, score, ts in rows:
        print(f"  {name[:35]:35} {float(score or 0):8.2f} {ts or 'NULL'}")
