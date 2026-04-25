#!/usr/bin/env python3
"""
scripts/reresolve_g2_stale_content.py — G2 Alias Remediation Re-resolver

Re-resolves content items that were processed BEFORE G2 aliases were seeded
(before 2026-04-25 16:59:00 UTC) and contain G2-relevant keyword text.

Root cause: 147+ stale content items were resolved at 16:19–16:20 UTC, before:
  - g2_seed aliases (rouge 540, br540, armaf, rasasi, etc.): seeded 16:59 UTC
  - g2_entity_seed Batch 1 (lattafa oud mood, yara, ajmal evoke): seeded 17:37 UTC
  - g2_entity_seed Batch 2 (armaf club de nuit, rasasi hawas): seeded 17:52 UTC

This script pre-loads ALL resolver aliases into memory (one query) and applies
the sliding window matching locally — avoids per-phrase DB roundtrips over the
public proxy, which would take hours.

Default mode: DRY-RUN (read-only, zero DB writes).
Use --apply to write updated resolved_signals rows.

Idempotent: UPSERT on resolved_signals.content_item_id (PK). Safe to re-run.

Rollback (after --apply):
  resolved_signals stores full JSON; old values are overwritten by the UPSERT.
  To revert, restore from a DB backup or let the aggregation re-derive from scratch.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from collections import defaultdict

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s %(levelname)-7s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# G2 keyword filter (ILIKE patterns used in the DB query)
# Content items must match at least one of these in text_content OR title.
# ---------------------------------------------------------------------------

G2_KEYWORDS: list[str] = [
    "lattafa", "armaf", "rasasi", "al haramain", "ajmal",
    "swiss arabian", "arabian oud",
    "oud mood", "khamrah", "yara", "club de nuit", "hawas",
    "amber oud", "evoke", "angels share", "angel share",
    "kilian", "1 million", "paco rabanne",
    "black opium", "rouge 540", "br540",
    "cedrat boise", "side effect",
]

# Stale cutoff: g2_seed aliases seeded at 16:59:39 UTC.
# Items whose resolved_signals.created_at < this are stale.
G2_SEED_CUTOFF_UTC = "2026-04-25 16:59:00"

# Resolver sliding window (mirrors perfume_resolver.py)
_MAX_WINDOW = 6
RESOLVER_VERSION = "1.1-g2-rereresolve"


# ---------------------------------------------------------------------------
# Normalization (mirrors alias_generator.py exactly)
# ---------------------------------------------------------------------------

def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower().strip()
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"'", " ", text)
    text = re.sub(r"[^\w\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# DB connection (psycopg2)
# ---------------------------------------------------------------------------

def _get_conn():
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    log.info("Connecting to Postgres …")
    return psycopg2.connect(url)


# ---------------------------------------------------------------------------
# Load ALL resolver aliases into memory (single query)
# ---------------------------------------------------------------------------

def load_alias_table(conn) -> dict[str, dict]:
    """
    Returns {normalized_alias_text: {perfume_id, canonical_name, match_type, confidence}}
    for ALL perfume-type aliases in resolver_aliases.

    One query — avoids per-lookup roundtrips.
    """
    sql = """
        SELECT a.normalized_alias_text,
               p.id            AS perfume_id,
               p.canonical_name,
               a.match_type,
               a.confidence
        FROM   resolver_aliases  a
        JOIN   resolver_perfumes p
          ON   a.entity_type = 'perfume'
         AND   a.entity_id   = p.id
    """
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    alias_table: dict[str, dict] = {}
    for norm_alias, perfume_id, canonical_name, match_type, confidence in rows:
        # Keep first occurrence if duplicates (lowest-id entity wins)
        if norm_alias not in alias_table:
            alias_table[norm_alias] = {
                "perfume_id":     int(perfume_id),
                "canonical_name": str(canonical_name),
                "match_type":     str(match_type),
                "confidence":     float(confidence) if confidence is not None else 1.0,
            }
    log.info("Loaded %d aliases into memory", len(alias_table))
    return alias_table


# ---------------------------------------------------------------------------
# Sliding window resolver (in-memory, mirrors perfume_resolver.resolve_text)
# ---------------------------------------------------------------------------

def resolve_text(text: str, alias_table: dict[str, dict]) -> list[dict]:
    normalized = normalize_text(text)
    tokens = normalized.split()
    matches: list[dict] = []
    seen: set[tuple[int, str]] = set()

    for size in range(_MAX_WINDOW, 0, -1):
        for i in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[i: i + size])
            hit = alias_table.get(phrase)
            if hit:
                key = (hit["perfume_id"], hit["canonical_name"])
                if key not in seen:
                    seen.add(key)
                    matches.append(hit)
    return matches


# ---------------------------------------------------------------------------
# Load stale content items
# ---------------------------------------------------------------------------

def _build_keyword_clauses() -> tuple[str, list[str]]:
    clauses = " OR ".join(
        "COALESCE(text_content, '') ILIKE %s OR COALESCE(title, '') ILIKE %s"
        for _ in G2_KEYWORDS
    )
    params = []
    for kw in G2_KEYWORDS:
        params.append(f"%{kw}%")
        params.append(f"%{kw}%")
    return clauses, params


def load_stale_content(conn) -> list[dict]:
    """
    Return canonical_content_items rows resolved BEFORE G2_SEED_CUTOFF_UTC
    that contain G2-relevant text.
    """
    kw_clauses, kw_params = _build_keyword_clauses()

    sql = f"""
        SELECT
            cci.id,
            cci.source_platform,
            cci.title,
            COALESCE(cci.text_content, '') AS text_content,
            rs.resolved_entities_json,
            rs.created_at AS resolved_at
        FROM canonical_content_items cci
        JOIN resolved_signals rs ON rs.content_item_id = cci.id
        WHERE
            rs.created_at < %s
            AND ({kw_clauses})
        ORDER BY cci.id
    """
    params = [G2_SEED_CUTOFF_UTC] + kw_params

    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


# ---------------------------------------------------------------------------
# Compare old vs new resolved entities
# ---------------------------------------------------------------------------

def _entity_set(entities_json: str | None) -> set[str]:
    if not entities_json:
        return set()
    try:
        items = json.loads(entities_json)
        return {e["canonical_name"] for e in items if "canonical_name" in e}
    except (json.JSONDecodeError, TypeError):
        return set()


# ---------------------------------------------------------------------------
# Build new resolved_entities JSON list from alias hits
# ---------------------------------------------------------------------------

def _build_resolved_entities(text: str, hits: list[dict]) -> list[dict]:
    return [
        {
            "entity_type":    "perfume",
            "entity_id":      str(h["perfume_id"]),
            "canonical_name": h["canonical_name"],
            "matched_from":   text[:200],
            "confidence":     h["confidence"],
            "match_type":     h["match_type"],
        }
        for h in hits
    ]


# ---------------------------------------------------------------------------
# Write updated resolved_signals (--apply only)
# ---------------------------------------------------------------------------

def write_resolved_signal(conn, content_item_id: str, resolved_entities: list[dict]) -> None:
    sql = """
        INSERT INTO resolved_signals
            (content_item_id, resolver_version, resolved_entities_json,
             unresolved_mentions_json, alias_candidates_json)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (content_item_id) DO UPDATE SET
            resolver_version       = EXCLUDED.resolver_version,
            resolved_entities_json = EXCLUDED.resolved_entities_json
    """
    cur = conn.cursor()
    cur.execute(sql, (
        content_item_id,
        RESOLVER_VERSION,
        json.dumps(resolved_entities),
        json.dumps([]),   # preserve unresolved empty for now
        json.dumps([]),
    ))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(apply: bool) -> None:
    conn = _get_conn()

    log.info("Loading stale content items (resolved before %s) …", G2_SEED_CUTOFF_UTC)
    rows = load_stale_content(conn)
    log.info("Found %d stale G2-relevant content items", len(rows))

    if not rows:
        log.warning("No stale items — nothing to do.")
        conn.close()
        return

    log.info("Loading resolver alias table into memory …")
    alias_table = load_alias_table(conn)

    # Counters
    items_checked        = 0
    items_gaining        = 0
    total_new_links      = 0
    entity_gain_counts: dict[str, int] = defaultdict(int)
    sample_matches: list[dict] = []

    log.info("Re-resolving %d items in-memory (dry_run=%s) …", len(rows), not apply)

    for row in rows:
        items_checked += 1
        text = (row["title"] or "") + " " + row["text_content"]
        old_entities = _entity_set(row["resolved_entities_json"])

        hits = resolve_text(text, alias_table)
        new_names = {h["canonical_name"] for h in hits}
        gained    = new_names - old_entities

        if gained:
            items_gaining += 1
            total_new_links += len(gained)
            for name in gained:
                entity_gain_counts[name] += 1

            if len(sample_matches) < 20:
                snippet = (row["title"] or row["text_content"] or "")[:80]
                sample_matches.append({
                    "content_id": row["id"],
                    "platform":   row["source_platform"],
                    "snippet":    snippet,
                    "old_count":  len(old_entities),
                    "new_count":  len(new_names),
                    "gained":     sorted(gained),
                })

            if apply:
                new_entities_list = _build_resolved_entities(text, hits)
                write_resolved_signal(conn, row["id"], new_entities_list)

        if items_checked % 25 == 0:
            log.info("  Processed %d/%d — %d gained so far",
                     items_checked, len(rows), items_gaining)

    if apply:
        conn.commit()
        log.info("Committed %d updated resolved_signals rows.", items_gaining)
    else:
        conn.rollback()

    conn.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    sep = "=" * 70
    print()
    print(sep)
    print(f"G2 Re-resolution — {'** DRY RUN ** (no DB writes)' if not apply else 'APPLIED'}")
    print(sep)
    print(f"  Stale items found         : {len(rows)}")
    print(f"  Items checked             : {items_checked}")
    print(f"  Items gaining entities    : {items_gaining}")
    print(f"  Total new entity links    : {total_new_links}")
    print(f"  DB writes                 : {'YES — ' + str(items_gaining) + ' rows updated' if apply else 'NO (dry-run)'}")
    print(sep)

    if entity_gain_counts:
        print("\nTop recovered entities (by content item count):")
        for name, cnt in sorted(entity_gain_counts.items(), key=lambda x: -x[1])[:20]:
            print(f"  {cnt:4d}×  {name}")

    if sample_matches:
        print(f"\nSample recovered matches ({len(sample_matches)} shown):")
        for m in sample_matches:
            gained_str = ", ".join(m["gained"][:3])
            if len(m["gained"]) > 3:
                gained_str += f" (+{len(m['gained']) - 3} more)"
            print(f"  [{m['platform']:8s}] {repr(m['snippet']):.65s}")
            print(f"             old={m['old_count']} → new={m['new_count']} | gained: {gained_str}")

    if not apply:
        print()
        print("Dry-run complete — zero DB writes performed.")
        print("To apply:")
        print("  DATABASE_URL=<prod-url> python3 scripts/reresolve_g2_stale_content.py --apply")
        print()
        print("After --apply, re-run aggregation for 2026-04-25 to generate entity_mentions:")
        print("  python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date 2026-04-25")
        print("Then signal detection:")
        print("  python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date 2026-04-25")
        print()
        print("Rollback note: resolved_signals is updated in-place (UPSERT). Old JSON is")
        print("overwritten. Revert via DB snapshot or by restoring the old JSON manually.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "G2 Re-resolution: re-resolve stale content items processed before G2 aliases "
            "were seeded. Default is DRY-RUN. Pass --apply to write."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write updated resolved_signals rows. Without this flag: dry-run only.",
    )
    args = parser.parse_args()

    if args.apply:
        log.warning("--apply flag active: will update resolved_signals in Postgres.")
    else:
        log.info("Dry-run mode (default): no DB writes will occur.")

    run(apply=args.apply)
