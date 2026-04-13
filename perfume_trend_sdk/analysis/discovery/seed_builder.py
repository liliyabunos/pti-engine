from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Known brands used for brand/perfume splitting
# Extend as knowledge base grows
KNOWN_BRANDS = {
    "parfums de marly", "pdm",
    "maison francis kurkdjian", "mfk",
    "maison margiela",
    "yves saint laurent", "ysl",
    "xerjoff",
    "lattafa",
    "mancera",
    "initio",
    "creed",
    "dior",
    "chanel",
    "tom ford",
    "versace",
    "giorgio armani",
    "gucci",
    "byredo",
    "viktor and rolf",
    "viktor & rolf",
    "mercedes benz",
    "rasasi",
    "ajmal",
    "armaf",
    "montale",
    "memo",
    "kilian",
    "frederic malle",
    "serge lutens",
    "nasomatto",
    "orto parisi",
    "nishane",
    "zoologist",
    "bdk parfums",
    "parfums de nicolai",
    "house of sillage",
}


def parse_candidate(text: str) -> Tuple[Optional[str], str]:
    """
    Split 'brand perfume_name' on first space.
    Returns (brand, perfume) — brand is None if single token.
    """
    parts = text.split(" ", 1)

    if len(parts) == 2:
        return parts[0].title(), parts[1].title()

    return None, text.title()


def build_seed_rows(
    candidates: List[Dict[str, Any]],
    source: str = "discovery",
) -> List[Dict[str, str]]:
    rows = []

    for c in candidates:
        brand, perfume = parse_candidate(c["text"])

        rows.append({
            "brand_name": brand or "Unknown",
            "perfume_name": perfume,
            "source": source,
        })

    return rows


def append_to_seed_csv(
    rows: List[Dict[str, str]],
    csv_path: str = "perfume_trend_sdk/data/fragrance_master/seed_master.csv",
) -> int:
    path = Path(csv_path)
    fieldnames = ["fragrance_id", "brand_name", "perfume_name", "release_year", "gender", "source"]

    write_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    return len(rows)
