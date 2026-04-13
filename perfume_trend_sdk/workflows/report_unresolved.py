import json
import sqlite3
from pathlib import Path

DB_PATH = "perfume_trend_sdk/db/perfume.db"
OUTPUT_PATH = "outputs/reports/top_unresolved_candidates.json"


def run_report_unresolved():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT candidate_text, COUNT(*) as count
        FROM unresolved
        WHERE candidate_text IS NOT NULL AND candidate_text != ''
        GROUP BY candidate_text
        ORDER BY count DESC
        LIMIT 20
        """
    ).fetchall()
    conn.close()

    candidates = [{"candidate": row[0], "count": row[1]} for row in rows]

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    print(f"Top unresolved candidates ({len(candidates)}):")
    for item in candidates:
        print(f"  {item['count']:>4}x  {item['candidate']}")

    return candidates


if __name__ == "__main__":
    run_report_unresolved()
