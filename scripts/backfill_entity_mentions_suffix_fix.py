#!/usr/bin/env python3
"""Backfill missing entity_mentions rows for suffix-bearing resolver canonical names.

Root cause (fixed 2026-05-14):
  _write_mentions() in aggregate_daily_market_metrics.py looked up entity UUIDs using
  the raw resolver canonical_name (e.g. "Lattafa Khamrah Eau de Parfum"), but
  entity_uuid_map is keyed by _base_name()-stripped names (e.g. "Lattafa Khamrah").
  The lookup failed silently → no entity_mention row written for suffix-bearing resolvers.

This script:
  1. Scans resolved_signals in the target date range
  2. Identifies content items where the canonical_name has a concentration suffix
     AND the _base_name() key is in entity_market
     AND no entity_mention row exists yet
  3. Inserts the missing entity_mention rows (idempotent — skips existing rows)
  4. Reports scope: affected entities, estimated missing row count, inserted count

Usage (dry-run):
  DATABASE_URL=<url> python3 scripts/backfill_entity_mentions_suffix_fix.py \
      --since 2026-05-01 --dry-run

Usage (apply):
  DATABASE_URL=<url> python3 scripts/backfill_entity_mentions_suffix_fix.py \
      --since 2026-05-01 --apply

Railway:
  railway run --service generous-prosperity \
    python3 scripts/backfill_entity_mentions_suffix_fix.py --since 2026-05-01 --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from perfume_trend_sdk.analysis.market_signals.aggregator import _base_name
from perfume_trend_sdk.db.market.entity_mention import EntityMention
from perfume_trend_sdk.db.market.session import make_session_factory, get_database_url
from perfume_trend_sdk.db.market.source_intelligence import MentionSource, SourceProfile
from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import (
    _resolve_source_url,
    _compute_source_score,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_NOW = datetime.now(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run(since: str, dry_run: bool) -> dict:
    """Run scope audit and optionally insert missing entity_mention rows.

    Returns a summary dict with scope and insert counts.
    """
    db_url = get_database_url()
    factory = make_session_factory(db_url)
    db = factory()

    try:
        return _run_with_session(db, since=since, dry_run=dry_run)
    finally:
        db.close()


def _run_with_session(db, *, since: str, dry_run: bool) -> dict:
    # ── Step 1: load entity_market canonical_name → UUID map ──────────────────
    log.info("Loading entity_market UUID map...")
    em_rows = db.execute(text(
        "SELECT canonical_name, id FROM entity_market WHERE entity_type = 'perfume'"
    )).fetchall()
    entity_uuid_map = {row[0]: uuid.UUID(str(row[1])) for row in em_rows}
    log.info("  entity_market perfume entries: %d", len(entity_uuid_map))

    # ── Step 2: load resolved_signals in date range ────────────────────────────
    log.info("Loading resolved_signals since %s...", since)
    sig_rows = db.execute(text("""
        SELECT rs.id, rs.content_item_id, rs.resolved_entities_json,
               ci.source_platform, ci.source_url, ci.external_content_id,
               ci.source_account_handle, ci.media_metadata_json, ci.engagement_json,
               ci.published_at
        FROM resolved_signals rs
        JOIN canonical_content_items ci ON ci.id = rs.content_item_id
        WHERE ci.published_at::date >= :since
          AND rs.resolved_entities_json IS NOT NULL
          AND rs.resolved_entities_json != '[]'
        ORDER BY ci.published_at ASC
    """), {"since": since}).fetchall()
    log.info("  resolved_signals rows loaded: %d", len(sig_rows))

    # ── Step 3: identify suffix-affected signals ───────────────────────────────
    affected_entities: dict[str, int] = {}  # base_name → count of suffix hits
    candidates = []  # (base_name, entity_uuid, sig_row, entity dict)

    for row in sig_rows:
        entities = json.loads(row[2] or "[]")
        for ent in entities:
            if ent.get("entity_type", "perfume") not in ("perfume", "brand"):
                continue
            canonical = ent.get("canonical_name", "")
            base = _base_name(canonical)
            if base == canonical:
                continue  # no suffix — not affected by this bug
            # Suffix present; check if base name is in entity_market
            entity_uuid = entity_uuid_map.get(base)
            if entity_uuid is None:
                continue  # entity not tracked in market engine
            affected_entities[base] = affected_entities.get(base, 0) + 1
            candidates.append((base, entity_uuid, row, ent))

    log.info("Suffix-bearing signals hitting tracked entities: %d", len(candidates))
    log.info("Distinct affected base names: %d", len(affected_entities))
    if affected_entities:
        top = sorted(affected_entities.items(), key=lambda x: -x[1])[:10]
        log.info("Top affected entities:")
        for name, count in top:
            log.info("  %-50s  %d signal hits", name, count)

    # ── Step 4: check which ones already have entity_mention rows ─────────────
    missing = []
    already_present = 0

    for base, entity_uuid, row, ent in candidates:
        source_url_resolved = _resolve_source_url(
            {
                "source_platform": row[3],
                "source_url": row[4],
                "external_content_id": row[5],
            },
            str(row[1]),
        )
        exists = db.execute(text("""
            SELECT 1 FROM entity_mentions
            WHERE entity_id = :eid AND source_url = :url
            LIMIT 1
        """), {"eid": str(entity_uuid), "url": source_url_resolved}).fetchone()

        if exists:
            already_present += 1
        else:
            missing.append((base, entity_uuid, row, ent, source_url_resolved))

    log.info("Already-existing entity_mention rows: %d", already_present)
    log.info("Missing entity_mention rows to insert: %d", len(missing))

    if dry_run:
        log.info("DRY RUN — no rows inserted.")
        return {
            "dry_run": True,
            "affected_entity_count": len(affected_entities),
            "affected_entities_sample": dict(sorted(affected_entities.items(), key=lambda x: -x[1])[:10]),
            "total_suffix_signal_hits": len(candidates),
            "already_present": already_present,
            "missing_count": len(missing),
            "inserted": 0,
        }

    # ── Step 5: insert missing entity_mention rows ────────────────────────────
    inserted = 0
    errors = 0

    for base, entity_uuid, row, ent, source_url_resolved in missing:
        try:
            pub_date = (row[9] or "")[:10] if row[9] else ""
            try:
                occurred_at = datetime.fromisoformat(pub_date).replace(tzinfo=timezone.utc)
            except ValueError:
                occurred_at = _now()

            meta = json.loads(row[7] or "{}")
            engagement = json.loads(row[8] or "{}")
            eng_total = (
                float(engagement.get("views") or 0)
                + float(engagement.get("likes") or 0) * 3
                + float(engagement.get("comments") or 0) * 5
            )

            mention = EntityMention(
                entity_id=entity_uuid,
                entity_type=ent.get("entity_type", "perfume"),
                source_platform=row[3],
                source_url=source_url_resolved,
                author_id=row[6],
                author_name=meta.get("channel_title") or row[6],
                mention_count=1.0,
                influence_score=float(meta.get("influence_score") or 0),
                confidence=float(ent.get("confidence") or 1.0),
                engagement=eng_total or None,
                occurred_at=occurred_at,
                created_at=_now(),
            )
            db.add(mention)
            db.flush()

            # Source intelligence rows
            platform = row[3] or "unknown"
            source_id = meta.get("channel_id") or row[6] or ""
            source_name = meta.get("channel_title") or row[6]
            views_raw = int(engagement.get("views") or 0)
            likes_raw = int(engagement.get("likes") or 0)
            comments_raw = int(engagement.get("comments") or 0)
            eng_rate: Optional[float] = (
                (likes_raw + comments_raw) / views_raw if views_raw > 0 else None
            )

            if source_id:
                db.execute(text("""
                    INSERT INTO source_profiles
                        (id, platform, source_id, source_name, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :platform, :source_id, :source_name, NOW(), NOW())
                    ON CONFLICT (platform, source_id)
                    DO UPDATE SET
                        source_name = EXCLUDED.source_name,
                        updated_at  = NOW()
                """), {
                    "platform": platform,
                    "source_id": source_id,
                    "source_name": source_name,
                })

            src_score = _compute_source_score(
                platform=platform,
                views=views_raw or None,
                likes=likes_raw or None,
                comments_count=comments_raw or None,
                engagement_rate=eng_rate,
            )
            db.add(MentionSource(
                mention_id=mention.id,
                platform=platform,
                source_id=source_id or "",
                source_name=source_name,
                views=views_raw or None,
                likes=likes_raw or None,
                comments_count=comments_raw or None,
                engagement_rate=eng_rate,
                source_score=src_score,
                created_at=_now(),
            ))
            inserted += 1

            if inserted % 50 == 0:
                db.commit()
                log.info("  committed %d rows so far...", inserted)

        except Exception as exc:
            log.warning("Error inserting mention for %s: %s", base, exc)
            db.rollback()
            errors += 1
            # Re-open transaction
            continue

    db.commit()
    log.info("Backfill complete: inserted=%d errors=%d", inserted, errors)

    return {
        "dry_run": False,
        "affected_entity_count": len(affected_entities),
        "affected_entities_sample": dict(sorted(affected_entities.items(), key=lambda x: -x[1])[:10]),
        "total_suffix_signal_hits": len(candidates),
        "already_present": already_present,
        "missing_count": len(missing),
        "inserted": inserted,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2026-05-01",
                        help="Start date ISO format (default: 2026-05-01)")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Audit only — do not insert rows")
    parser.add_argument("--apply", action="store_true", default=False,
                        help="Actually insert missing entity_mention rows")
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        # Default to dry-run for safety
        args.dry_run = True

    result = run(since=args.since, dry_run=args.dry_run)

    print("\n=== BACKFILL REPORT ===")
    print(f"  Mode:                  {'DRY RUN' if result['dry_run'] else 'APPLIED'}")
    print(f"  Since:                 {args.since}")
    print(f"  Affected entities:     {result['affected_entity_count']}")
    print(f"  Total suffix hits:     {result['total_suffix_signal_hits']}")
    print(f"  Already present:       {result['already_present']}")
    print(f"  Missing (to insert):   {result['missing_count']}")
    print(f"  Inserted:              {result['inserted']}")
    if not result["dry_run"]:
        print(f"  Errors:                {result.get('errors', 0)}")
    if result["affected_entities_sample"]:
        print("\nTop affected entities (name → suffix-hit count):")
        for name, cnt in result["affected_entities_sample"].items():
            print(f"  {cnt:4d}  {name}")


if __name__ == "__main__":
    main()
