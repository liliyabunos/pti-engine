from __future__ import annotations

"""Workflow: Enrich known perfumes with Fragrantica metadata.

CLI usage (resolver SQLite → market SQLite, local dev):
    python -m perfume_trend_sdk.workflows.enrich_from_fragrantica \
        --resolver-db data/resolver/pti.db \
        --limit 100 \
        --output outputs/enriched/fragrantica.json

CLI usage (production — resolver SQLite, market Postgres):
    DATABASE_URL="postgresql://..." \\
    python -m perfume_trend_sdk.workflows.enrich_from_fragrantica \
        --resolver-db data/resolver/pti.db \
        --limit 100

Flow:
    1. Load resolved perfumes (with resolver int PK) from fragrance_master SQLite
    2. For each perfume:
       a. Build Fragrantica URL from brand/perfume slugs
       b. Fetch raw HTML → save to raw storage
       c. Parse → normalize → enrich (in memory)
       d. Look up market UUID via perfume_identity_map
       e. Persist to DB: fragrantica_records, notes, accords,
          perfume_notes, perfume_accords, perfumes.notes_summary
       f. Append enriched dict to JSON output (backward compatibility)
    3. Print summary + DB row counts

Per-perfume errors are caught and logged; the pipeline continues.
DB persistence is additive and idempotent — re-running is safe.
"""

import argparse
import json
import logging
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
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resolver DB loader
# ---------------------------------------------------------------------------

def _load_perfumes_from_master(db_path: str, limit: int) -> List[Dict]:
    """Load perfumes from fragrance_master table.

    Returns dicts with: fragrance_id, brand_name, perfume_name,
    canonical_name, normalized_name, perfume_id (resolver int PK).
    """
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT fragrance_id, brand_name, perfume_name, canonical_name, "
            "normalized_name, perfume_id "
            "FROM fragrance_master LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        log_event("ERROR", "load_perfumes_failed", error=str(exc))
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def run(
    resolver_db: str,
    limit: int,
    output_path: str,
    market_db_url: str | None = None,
) -> Dict:
    """Enrich perfumes with Fragrantica data and persist to market DB.

    Parameters
    ----------
    resolver_db     : Path to the resolver SQLite DB (data/resolver/pti.db).
    limit           : Maximum number of perfumes to process.
    output_path     : JSON output file path (backward compat).
    market_db_url   : Market engine DB URL. If None, resolved from env vars
                      (DATABASE_URL → PTI_DB_PATH → default SQLite).

    Returns
    -------
    Summary dict with counts.
    """
    run_id = (
        f"fragrantica_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        f"_{uuid.uuid4().hex[:8]}"
    )
    log_event("INFO", "workflow_started", workflow="enrich_from_fragrantica", run_id=run_id)

    # Resolve market DB URL
    if not market_db_url:
        market_db_url = _resolve_market_url()

    # Lazy import (store is optional — workflow degrades gracefully without it)
    db_store = None
    try:
        from perfume_trend_sdk.storage.entities.fragrantica_enrichment_store import (
            FragranticaEnrichmentStore,
        )
        db_store = FragranticaEnrichmentStore(market_db_url)
        logger.info("[enrich_from_fragrantica] DB store initialized: %s",
                    market_db_url.split("@")[-1] if "@" in market_db_url else market_db_url)
    except Exception as exc:
        logger.warning(
            "[enrich_from_fragrantica] DB store unavailable (%s) — will write JSON only", exc
        )

    raw_storage = FilesystemRawStorage(base_dir="data/raw")
    client = FragranticaClient()
    parser = FragranticaParser()
    normalizer = FragranticaNormalizer()
    enricher = FragranticaEnricher()

    perfumes = _load_perfumes_from_master(resolver_db, limit)
    log_event("INFO", "perfumes_loaded", count=len(perfumes), run_id=run_id)

    fetched = 0
    parsed_ok = 0
    enriched_ok = 0
    db_persisted = 0
    uuid_matched = 0
    failed = 0
    enriched_records: List[Dict] = []

    for perfume in perfumes:
        brand_name: Optional[str] = perfume.get("brand_name")
        perfume_name: Optional[str] = perfume.get("perfume_name")
        fragrance_id: Optional[str] = perfume.get("fragrance_id")
        resolver_perfume_id: Optional[int] = perfume.get("perfume_id")

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
        raw_payload_ref = ""
        try:
            refs = raw_storage.save_raw_batch(
                source_name="fragrantica",
                run_id=run_id,
                items=[raw_item],
            )
            raw_payload_ref = refs[0] if refs else ""
        except Exception as exc:
            log_event("ERROR", "raw_save_error", url=url, error=str(exc), run_id=run_id)

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

        # Step 5: Enrich in memory
        try:
            enriched = enricher.enrich(perfume, normalized)
            enriched_ok += 1
            enriched_records.append(enriched)
        except Exception as exc:
            log_event("ERROR", "enrich_error", url=url, error=str(exc), run_id=run_id)
            failed += 1
            continue

        # Step 6: Persist to market DB
        if db_store and fragrance_id:
            market_uuid: Optional[str] = None
            if resolver_perfume_id is not None:
                try:
                    market_uuid = db_store.lookup_market_uuid(resolver_perfume_id)
                    if market_uuid:
                        uuid_matched += 1
                except Exception as exc:
                    logger.warning(
                        "[enrich_from_fragrantica] identity map lookup failed: %s — %s",
                        fragrance_id, exc,
                    )

            try:
                db_store.persist(
                    fragrance_id=fragrance_id,
                    market_perfume_uuid=market_uuid,
                    source_url=url,
                    raw_payload_ref=raw_payload_ref,
                    brand_name=brand_name,
                    perfume_name=perfume_name,
                    record=normalized,
                )
                db_persisted += 1
            except Exception as exc:
                logger.error(
                    "[enrich_from_fragrantica] DB persist failed: %s — %s", fragrance_id, exc
                )

    # Save JSON output (backward compatibility)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(enriched_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Collect DB counts for report
    db_counts: Dict = {}
    if db_store:
        for tbl in ("fragrantica_records", "notes", "accords", "perfume_notes", "perfume_accords"):
            try:
                db_counts[tbl] = db_store.count_rows(tbl)
            except Exception:
                db_counts[tbl] = "?"
        try:
            db_counts["perfumes_with_notes_summary"] = db_store.count_enriched_perfumes()
        except Exception:
            db_counts["perfumes_with_notes_summary"] = "?"

    summary = {
        "run_id": run_id,
        "fetched": fetched,
        "parsed": parsed_ok,
        "enriched": enriched_ok,
        "uuid_matched": uuid_matched,
        "db_persisted": db_persisted,
        "failed": failed,
        "output": output_path,
        "db_counts": db_counts,
    }
    log_event("INFO", "workflow_completed", workflow="enrich_from_fragrantica", **summary)

    print("\n=== Fragrantica Enrichment Summary ===")
    print(f"  Perfumes processed : {len(perfumes)}")
    print(f"  Fetched            : {fetched}")
    print(f"  Parsed             : {parsed_ok}")
    print(f"  Enriched           : {enriched_ok}")
    print(f"  Market UUID found  : {uuid_matched}")
    print(f"  DB persisted       : {db_persisted}")
    print(f"  Failed             : {failed}")
    print(f"  JSON output        : {output_path}")
    if db_counts:
        print("\n  DB row counts (post-run):")
        for k, v in db_counts.items():
            print(f"    {k:<35} : {v}")
    print("======================================\n")

    return summary


def _resolve_market_url() -> str:
    """Resolve the market DB URL from environment variables."""
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[len("postgres://"):]
        return db_url
    path = os.environ.get("PTI_DB_PATH", "outputs/market_dev.db")
    if "://" in path:
        return path
    return f"sqlite:///{path}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    arg_parser = argparse.ArgumentParser(
        description="Enrich resolved perfumes with Fragrantica metadata + persist to market DB"
    )
    arg_parser.add_argument(
        "--resolver-db",
        default="data/resolver/pti.db",
        help="Path to resolver SQLite DB (default: data/resolver/pti.db)",
    )
    arg_parser.add_argument(
        "--db",
        default=None,
        help="[DEPRECATED] Alias for --resolver-db (backward compat)",
    )
    arg_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max perfumes to process (default: 20)",
    )
    arg_parser.add_argument(
        "--output",
        default="outputs/enriched/fragrantica.json",
        help="Output JSON file path",
    )
    arg_parser.add_argument(
        "--market-db",
        default=None,
        help="Market DB URL (default: from DATABASE_URL or PTI_DB_PATH env vars)",
    )
    args = arg_parser.parse_args()

    # Backward compat: --db was the old resolver DB flag
    resolver_db = args.resolver_db
    if args.db and resolver_db == "data/resolver/pti.db":
        resolver_db = args.db

    run(
        resolver_db=resolver_db,
        limit=args.limit,
        output_path=args.output,
        market_db_url=args.market_db,
    )


if __name__ == "__main__":
    main()
