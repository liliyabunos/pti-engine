import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = "perfume_trend_sdk/db/perfume.db"
OUTPUT_PATH = Path("outputs/reports/trends.json")
REPORT_PATH = Path("outputs/reports/trend_report.json")


def build_trends():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            b.canonical_name as brand,
            p.canonical_name as perfume,
            COUNT(*) as mention_count,
            SUM(m.weight) as trend_score,
            AVG(r.confidence) as avg_confidence
        FROM resolutions r
        JOIN perfumes p ON r.entity_id = p.id
        JOIN brands b ON p.brand_id = b.id
        JOIN mentions m ON r.mention_id = m.id
        WHERE r.entity_type = 'perfume'
        GROUP BY b.canonical_name, p.canonical_name
        ORDER BY trend_score DESC
    """)
    results = cursor.fetchall()

    cursor.execute("""
        SELECT
            p.canonical_name,
            MIN(m.created_at) as first_seen
        FROM resolutions r
        JOIN perfumes p ON r.entity_id = p.id
        JOIN mentions m ON r.mention_id = m.id
        WHERE r.entity_type = 'perfume'
        GROUP BY p.canonical_name
    """)
    first_seen_map = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT
            p.canonical_name,
            COUNT(*) as cnt
        FROM resolutions r
        JOIN perfumes p ON r.entity_id = p.id
        JOIN mentions m ON r.mention_id = m.id
        WHERE r.entity_type = 'perfume'
          AND m.created_at >= datetime('now', '-1 day')
        GROUP BY p.canonical_name
    """)
    last_24h = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT
            p.canonical_name,
            COUNT(*) as cnt
        FROM resolutions r
        JOIN perfumes p ON r.entity_id = p.id
        JOIN mentions m ON r.mention_id = m.id
        WHERE r.entity_type = 'perfume'
          AND m.created_at >= datetime('now', '-2 days')
          AND m.created_at < datetime('now', '-1 day')
        GROUP BY p.canonical_name
    """)
    prev_24h = {row[0]: row[1] for row in cursor.fetchall()}

    conn.close()

    trends = []
    for brand, perfume, count, trend_score, avg_conf in results:
        last = last_24h.get(perfume, 0)
        prev = prev_24h.get(perfume, 0)
        if prev > 0:
            growth = round((last - prev) / prev, 3)
        elif last > 0:
            growth = 1.0
        else:
            growth = 0.0

        trends.append({
            "brand": brand,
            "perfume": perfume,
            "mention_count": count,
            "trend_score": round(trend_score, 3),
            "avg_confidence": round(avg_conf, 3),
            "mentions_last_24h": last,
            "mentions_prev_24h": prev,
            "growth": growth,
            "first_seen": first_seen_map.get(perfume),
        })

    return trends


def classify_trends(trends: list) -> dict:
    sorted_by_score = sorted(trends, key=lambda x: x["trend_score"], reverse=True)
    top_ids = {t["perfume"] for t in sorted_by_score[:10]}

    top_trending = []
    emerging = []
    stable = []

    for t in trends:
        if t["perfume"] in top_ids:
            top_trending.append(t)
        elif t["growth"] > 0.5 and t["mentions_prev_24h"] == 0:
            emerging.append(t)
        else:
            stable.append(t)

    return {
        "top_trending": top_trending,
        "emerging": emerging,
        "stable": stable,
    }


if __name__ == "__main__":
    trends = build_trends()
    for t in trends:
        print(t)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(trends, f, indent=2)
    print(f"Saved trends to {OUTPUT_PATH}")

    report = classify_trends(trends)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved report to {REPORT_PATH}")
