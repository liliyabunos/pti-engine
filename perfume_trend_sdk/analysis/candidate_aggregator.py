from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def aggregate_unresolved(unresolved_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    unresolved_rows:
    [
      {
        "normalized_text": "lattafa khamrah",
        "source": "youtube",
        "created_at": "..."
      }
    ]
    """
    agg: Dict[str, Any] = defaultdict(lambda: {
        "text": "",
        "count": 0,
        "sources": set(),
        "first_seen_at": None,
        "last_seen_at": None,
    })

    for row in unresolved_rows:
        key = row["normalized_text"]
        item = agg[key]
        item["text"] = key
        item["count"] += 1
        item["sources"].add(row.get("source"))

        ts_raw = row.get("created_at")
        if ts_raw:
            ts = datetime.fromisoformat(ts_raw)
            if not item["first_seen_at"] or ts < item["first_seen_at"]:
                item["first_seen_at"] = ts
            if not item["last_seen_at"] or ts > item["last_seen_at"]:
                item["last_seen_at"] = ts

    result: List[Dict[str, Any]] = []
    for v in agg.values():
        result.append({
            "text": v["text"],
            "count": v["count"],
            "sources": len(v["sources"]),
            "first_seen_at": str(v["first_seen_at"]),
            "last_seen_at": str(v["last_seen_at"]),
        })

    return sorted(result, key=lambda x: x["count"], reverse=True)


def save_top_candidates(
    data: List[Dict[str, Any]],
    path: str = "outputs/top_unresolved_candidates.json",
) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
