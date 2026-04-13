from __future__ import annotations

import csv
import json
from pathlib import Path

from perfume_trend_sdk.analysis.discovery.candidate_filter import filter_candidates
from perfume_trend_sdk.analysis.discovery.seed_builder import build_seed_rows


INPUT = "outputs/top_unresolved_candidates.json"
SEED_PATH = "perfume_trend_sdk/data/fragrance_master/seed_master.csv"


def run() -> None:
    with open(INPUT, encoding="utf-8") as f:
        candidates = json.load(f)

    filtered = filter_candidates(candidates)
    rows = build_seed_rows(filtered)

    with open(SEED_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["brand_name", "perfume_name", "source"],
        )
        for r in rows:
            writer.writerow(r)

    print(f"Promoted {len(rows)} candidates")


if __name__ == "__main__":
    run()
