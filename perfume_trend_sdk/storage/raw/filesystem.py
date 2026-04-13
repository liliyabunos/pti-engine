from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FilesystemRawStorage:
    def __init__(self, base_dir: str = "data/raw") -> None:
        self.base_dir = Path(base_dir)

    def save_raw_batch(self, source_name: str, run_id: str, items: list[dict[str, Any]]) -> list[str]:
        target_dir = self.base_dir / source_name / run_id
        target_dir.mkdir(parents=True, exist_ok=True)

        refs: list[str] = []
        for idx, item in enumerate(items, start=1):
            path = target_dir / f"{idx:05d}.json"
            path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            refs.append(str(path))
        return refs
