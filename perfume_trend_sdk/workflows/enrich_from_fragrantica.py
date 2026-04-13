from __future__ import annotations

"""Workflow: Enrich known perfumes with Fragrantica metadata.

CLI usage:
    python -m perfume_trend_sdk.workflows.enrich_from_fragrantica \
        --db outputs/pti.db \
        --limit 20 \
        --output outputs/enriched/fragrantica.json

Flow:
    1. Load resolved perfumes from FragranceMasterStore
    2. For each: build URL → fetch HTML → save raw → parse → normalize → enrich
    3. Save enriched records to output JSON
    4. Errors per perfume are caught and logged — pipeline continues
    5. Print summary at end
"""

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from perfume_trend_sdk.connectors.fragrantica.client import FragranticaClient
from perfume_trend_sdk.connectors.fragrantica.parser import FragranticaParser
from perfume_trend_sdk.connectors.fragrantica.urls import build_perfume_url, slugify
from perfume_trend_sdk.core.logging.logger import log_event
from perfume_trend_sdk.enrichers.perfume_metadata.fragrantica_enricher import FragranticaEnricher
from perfume_trend_sdk.normalizers.fragrantica.normalizer import FragranticaNormalizer
from perfume_trend_sdk.storage.entities.fragrance_master_store import FragranceMasterStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage


def _load_perfumes_from_master(db_path: str, limit: int) -> List[Dict]:
    """Load perfumes from fragrance_master table."""
    store = FragranceMasterStore(db_path=db_path)
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT fragrance_id, brand_name, perfume_name, canonical_name, normalized_name "
            "FROM fragrance_master LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        log_event("ERROR", "load_perfumes_failed", error=str(exc))
        return []
    finally:
        conn.close()


def run(db_path: str, limit: int, output_path: str) -> None:
    run_id = f"fragrantica_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    log_event("INFO", "workflow_started", workflow="enrich_from_fragrantica", run_id=run_id)

    raw_storage = FilesystemRawStorage(base_dir="data/raw")
    client = FragranticaClient()
    parser = FragranticaParser()
    normalizer = FragranticaNormalizer()
    enricher = FragranticaEnricher()

    perfumes = _load_perfumes_from_master(db_path, limit)
    log_event("INFO", "perfumes_loaded", count=len(perfumes), run_id=run_id)

    fetched = 0
    parsed_ok = 0
    enriched_ok = 0
    failed = 0
    enriched_records: List[Dict] = []

    for perfume in perfumes:
        brand_name: Optional[str] = perfume.get("brand_name")
        perfume_name: Optional[str] = perfume.get("perfume_name")

        if not brand_name or not perfume_name:
            log_event("WARNING", "perfume_skipped_missing_names", record=perfume)
            failed += 1
            continue

        brand_slug = slugify(brand_name)
        perfume_slug = slugify(perfume_name)
        url = build_perfume_url(brand_slug, perfume_slug)

        # Step 1: Fetch raw HTML
        raw_html: Optional[str] = None
        try:
            raw_html = client.fetch_page(url)
            fetched += 1
        except Exception as exc:
            log_event("ERROR", "fetch_error", url=url, error=str(exc), run_id=run_id)
            failed += 1
            continue

        # Step 2: Save raw HTML BEFORE parsing (required by architecture)
        raw_item = {
            "source_name": "fragrantica",
            "source_url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "raw_html": raw_html,
            "brand_name": brand_name,
            "perfume_name": perfume_name,
        }
        try:
            refs = raw_storage.save_raw_batch(
                source_name="fragrantica",
                run_id=run_id,
                items=[raw_item],
            )
            raw_payload_ref = refs[0] if refs else ""
        except Exception as exc:
            log_event("ERROR", "raw_save_error", url=url, error=str(exc), run_id=run_id)
            raw_payload_ref = ""

        # Step 3: Parse
        try:
            parsed = parser.parse(raw_html, source_url=url)
            parsed_ok += 1
        except Exception as exc:
            log_event("ERROR", "parse_error", url=url, error=str(exc), run_id=run_id)
            failed += 1
            continue

        # Step 4: Normalize
        try:
            normalized = normalizer.normalize(parsed, raw_payload_ref=raw_payload_ref)
        except Exception as exc:
            log_event("ERROR", "normalize_error", url=url, error=str(exc), run_id=run_id)
            failed += 1
            continue

        # Step 5: Enrich — must not break pipeline on failure
        try:
            enriched = enricher.enrich(perfume, normalized)
            enriched_ok += 1
            enriched_records.append(enriched)
        except Exception as exc:
            log_event("ERROR", "enrich_error", url=url, error=str(exc), run_id=run_id)
            failed += 1
            continue

    # Save output JSON
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(enriched_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = {
        "run_id": run_id,
        "fetched": fetched,
        "parsed": parsed_ok,
        "enriched": enriched_ok,
        "failed": failed,
        "output": output_path,
    }
    log_event("INFO", "workflow_completed", workflow="enrich_from_fragrantica", **summary)

    print("\n=== Fragrantica Enrichment Summary ===")
    print(f"  Fetched:  {fetched}")
    print(f"  Parsed:   {parsed_ok}")
    print(f"  Enriched: {enriched_ok}")
    print(f"  Failed:   {failed}")
    print(f"  Output:   {output_path}")
    print("======================================\n")


def main() -> None:
    load_dotenv()
    arg_parser = argparse.ArgumentParser(
        description="Enrich resolved perfumes with Fragrantica metadata"
    )
    arg_parser.add_argument("--db", default="outputs/pti.db", help="Path to SQLite DB")
    arg_parser.add_argument("--limit", type=int, default=20, help="Max perfumes to process")
    arg_parser.add_argument(
        "--output",
        default="outputs/enriched/fragrantica.json",
        help="Output JSON file path",
    )
    args = arg_parser.parse_args()
    run(db_path=args.db, limit=args.limit, output_path=args.output)


if __name__ == "__main__":
    main()
