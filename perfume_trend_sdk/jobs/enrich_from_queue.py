from __future__ import annotations

"""Job: enrich_from_queue — Phase 1R Fragrantica Enrichment Recovery

Reads pending/pending_enrichment items from metadata_gap_queue (gap_type IN
missing_fragrantica, missing_notes, missing_accords), fetches and parses
Fragrantica pages, persists enrichment data, then marks each item done/failed.

Root cause fix (Phase 1R):
  FragranticaClient now uses a realistic Chrome User-Agent instead of
  "PTI-SDK/1.0", which Fragrantica's bot detection immediately blocked.
  HTTP 200 confirmed from Railway IPs with realistic User-Agent.

Usage:
    python -m perfume_trend_sdk.jobs.enrich_from_queue
    python -m perfume_trend_sdk.jobs.enrich_from_queue --limit 10
    python -m perfume_trend_sdk.jobs.enrich_from_queue --dry-run
"""

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 10
_GAP_TYPES = {"missing_fragrantica", "missing_notes", "missing_accords"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Queue loader
# ---------------------------------------------------------------------------

def _load_queue_items(db: Session, limit: int) -> List[Dict[str, Any]]:
    """Load pending/pending_enrichment metadata_gap_queue items for Fragrantica gaps.

    Only loads items where a resolver_fragrance_master match exists for the entity,
    ensuring we can build a valid Fragrantica URL. Items without a resolver match
    are left in the queue as pending_enrichment (the run_maintenance job already
    set their status; they require a more sophisticated lookup path).
    """
    rows = db.execute(text("""
        SELECT q.id, q.entity_id, q.entity_type, q.canonical_name, q.gap_type, q.fragrance_id
        FROM metadata_gap_queue q
        JOIN entity_market em ON CAST(em.id AS TEXT) = q.entity_id
        JOIN resolver_fragrance_master rfm
          ON LOWER(rfm.canonical_name) = LOWER(em.canonical_name)
        WHERE q.status IN ('pending', 'pending_enrichment')
          AND q.gap_type IN ('missing_fragrantica', 'missing_notes', 'missing_accords')
        ORDER BY q.priority ASC, q.gap_type
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    return [
        {
            "queue_id": r[0],
            "entity_id": str(r[1]),
            "entity_type": str(r[2]),
            "canonical_name": str(r[3]) if r[3] else None,
            "gap_type": str(r[4]),
            "fragrance_id": str(r[5]) if r[5] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Identity resolution: entity_id (UUID) → canonical_name → resolver FM row
# ---------------------------------------------------------------------------

def _resolve_identity(db: Session, entity_id: str) -> Optional[Dict[str, Any]]:
    """Resolve entity_id (market UUID) → canonical_name → resolver brand/perfume names.

    Lookup path:
      entity_market.id (UUID) → entity_market.canonical_name
      → resolver_fragrance_master JOIN ON LOWER(canonical_name)
      → brand_name, perfume_name

    Note: fragrance_id values in resolver_fragrance_master are internal placeholder
    IDs (fr_001, fr_002...), not real Fragrantica IDs — so URLs are built from
    brand_name + perfume_name slugs instead.
    """
    # Step 1: entity_id (UUID) → entity_market canonical_name
    row = db.execute(text("""
        SELECT canonical_name
        FROM entity_market
        WHERE CAST(id AS TEXT) = :uid
        LIMIT 1
    """), {"uid": entity_id}).fetchone()

    if not row:
        logger.warning("[enrich_from_queue] no entity_market row for entity_id=%s", entity_id)
        return None

    canonical_name = str(row[0])

    # Step 2: canonical_name → resolver_fragrance_master (case-insensitive)
    fm_row = db.execute(text("""
        SELECT brand_name, perfume_name, perfume_id
        FROM resolver_fragrance_master
        WHERE LOWER(canonical_name) = LOWER(:cname)
        LIMIT 1
    """), {"cname": canonical_name}).fetchone()

    if not fm_row:
        logger.warning(
            "[enrich_from_queue] no resolver_fragrance_master row for canonical_name=%r",
            canonical_name,
        )
        return None

    return {
        "canonical_name": canonical_name,
        "brand_name": str(fm_row[0]) if fm_row[0] else None,
        "perfume_name": str(fm_row[1]) if fm_row[1] else None,
        "resolver_id": int(fm_row[2]) if fm_row[2] else None,
    }


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def _build_url(identity: Dict[str, Any], queue_fragrance_id: Optional[str]) -> Optional[str]:
    """Build Fragrantica URL from identity data.

    Priority:
    1. queue fragrance_id if it looks like a real Fragrantica slug (contains digits)
    2. Brand slug + perfume slug from brand_name / perfume_name (most common path)

    Note: resolver_fragrance_master.fragrance_id values are internal placeholder IDs
    (fr_001, fr_002...) and cannot be used to construct Fragrantica URLs directly.
    """
    from perfume_trend_sdk.connectors.fragrantica.urls import slugify, build_perfume_url

    # Option 1: queue fragrance_id with real Fragrantica ID format (has digits at end)
    if queue_fragrance_id and any(ch.isdigit() for ch in queue_fragrance_id):
        from perfume_trend_sdk.connectors.fragrantica.urls import BASE_URL
        return f"{BASE_URL}/perfume/{queue_fragrance_id}.html"

    # Option 2: build from brand + perfume name slugs
    brand = identity.get("brand_name")
    perfume = identity.get("perfume_name")
    if brand and perfume:
        return build_perfume_url(slugify(brand), slugify(perfume))

    return None


# ---------------------------------------------------------------------------
# Queue status updater
# ---------------------------------------------------------------------------

def _update_queue_status(
    db: Session,
    queue_id: int,
    status: str,
    note: str,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    db.execute(text("""
        UPDATE metadata_gap_queue
        SET status           = :status,
            updated_at       = :now,
            last_attempted_at = :now,
            notes_json       = :note
        WHERE id = :id
    """), {"status": status, "now": _now_iso(), "note": note, "id": queue_id})


# ---------------------------------------------------------------------------
# Search-based URL resolution (for slug URLs without numeric ID)
# ---------------------------------------------------------------------------

def _search_for_fragrantica_url(brand_name: str, perfume_name: str) -> Optional[str]:
    """Search for the canonical Fragrantica URL (with numeric ID) for a perfume.

    Fragrantica requires a numeric ID in the URL, e.g.:
      /perfume/Christian-Dior/Sauvage-43439.html
    Slug-only URLs (generated by slugify()) return 404.

    Strategy:
    1. Hit Fragrantica search — for popular perfumes, Fragrantica redirects
       directly to the perfume page. Detect redirect via resp.url.
    2. Fall back to DuckDuckGo HTML search — plain HTML, no JS required,
       extracts Fragrantica URLs with numeric IDs from page text.

    Returns the full canonical URL, or None on failure.
    """
    import re
    import urllib.parse

    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None

    _HEADERS = {
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://www.fragrantica.com/",
    }
    _FRAG_URL_RE = re.compile(
        r"fragrantica\.com/perfume/[A-Za-z0-9%\-]+/[A-Za-z0-9%\-]+-\d+\.html"
    )

    # --- Strategy A: Fragrantica search (works when it redirects to perfume page) ---
    query = f"{perfume_name} {brand_name}".strip()
    search_url = (
        f"https://www.fragrantica.com/search/?query={urllib.parse.quote_plus(query)}"
    )
    logger.info("[enrich_from_queue] Fragrantica search: %r", query)
    try:
        resp = cffi_requests.get(
            search_url,
            impersonate="chrome120",
            headers=_HEADERS,
            timeout=20,
            allow_redirects=True,
        )
        # Check if the request redirected directly to a perfume page
        final_url = str(resp.url)
        if (
            resp.status_code == 200
            and "/perfume/" in final_url
            and final_url.endswith(".html")
            and "search" not in final_url
        ):
            logger.info("[enrich_from_queue] Fragrantica search redirected to: %s", final_url)
            return final_url
        # No redirect — Fragrantica's JS-rendered search results aren't usable
    except Exception as exc:
        logger.warning("[enrich_from_queue] Fragrantica search failed: %s", exc)

    # --- Strategy B: DuckDuckGo HTML search (plain HTML, no JS) ---
    ddg_query = f"site:fragrantica.com/perfume {perfume_name} {brand_name}"
    ddg_url = (
        f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(ddg_query)}"
    )
    logger.info("[enrich_from_queue] DDG search: %r", ddg_query)
    try:
        resp2 = cffi_requests.get(
            ddg_url,
            impersonate="chrome120",
            headers={**_HEADERS, "Referer": "https://duckduckgo.com/"},
            timeout=20,
            allow_redirects=True,
        )
        if resp2.status_code == 200:
            # DDG encodes URLs in uddg= params; also shows them as plain text
            # Match Fragrantica URLs with numeric IDs
            candidates = _FRAG_URL_RE.findall(urllib.parse.unquote(resp2.text))
            # Deduplicate, preserve order
            seen: set = set()
            unique = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    unique.append(c)

            if unique:
                # Prefer URL containing the first word of perfume name
                perfume_fragment = perfume_name.lower().split()[0] if perfume_name else ""
                for candidate in unique:
                    if perfume_fragment and perfume_fragment in candidate.lower():
                        resolved = f"https://www.{candidate}"
                        logger.info("[enrich_from_queue] resolved via DDG: %s", resolved)
                        return resolved
                # Fallback: first candidate with numeric ID
                resolved = f"https://www.{unique[0]}"
                logger.info("[enrich_from_queue] resolved via DDG (first): %s", resolved)
                return resolved

            logger.warning("[enrich_from_queue] no Fragrantica numeric-ID URLs in DDG results")
    except Exception as exc:
        logger.warning("[enrich_from_queue] DDG search failed: %s", exc)

    return None


# ---------------------------------------------------------------------------
# Fetch helper — curl_cffi with search resolution, Playwright fallback
# ---------------------------------------------------------------------------

def _fetch_html(
    url: str,
    brand_name: Optional[str] = None,
    perfume_name: Optional[str] = None,
) -> tuple[str, str, str]:
    """Fetch Fragrantica page HTML. Returns (html, client_name, actual_url).

    Strategy (in order):
    1. curl_cffi (Chrome TLS fingerprint) — fast, lightweight.
       On HTTP 404: perform search-based URL resolution to find the
       canonical URL with numeric ID, then re-fetch that URL.
    2. Playwright: full headless browser — handles JS challenges but heavy.
    3. requests: plain HTTP fallback.

    Returns actual_url which may differ from url when search resolution
    was performed (the resolved URL with numeric ID).

    Raises RuntimeError if all methods fail.
    """
    # --- Strategy 1: curl_cffi (Chrome TLS fingerprint) ---
    try:
        from curl_cffi import requests as cffi_requests

        _HEADERS = {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Referer": "https://www.fragrantica.com/",
        }

        resp = cffi_requests.get(
            url,
            impersonate="chrome120",
            headers=_HEADERS,
            timeout=20,
            allow_redirects=True,
        )

        if resp.status_code == 200:
            return resp.text, "curl_cffi", url

        if resp.status_code == 404 and brand_name and perfume_name:
            # Slug URL lacks numeric ID — resolve via search
            logger.info(
                "[enrich_from_queue] 404 for %s — attempting search resolution for %r %r",
                url, brand_name, perfume_name,
            )
            resolved_url = _search_for_fragrantica_url(brand_name, perfume_name)
            if resolved_url:
                resp2 = cffi_requests.get(
                    resolved_url,
                    impersonate="chrome120",
                    headers=_HEADERS,
                    timeout=20,
                    allow_redirects=True,
                )
                if resp2.status_code == 200:
                    return resp2.text, "curl_cffi_search", resolved_url
                logger.warning(
                    "[enrich_from_queue] resolved URL returned HTTP %d: %s",
                    resp2.status_code, resolved_url,
                )

        logger.warning(
            "[enrich_from_queue] curl_cffi got HTTP %d for %s", resp.status_code, url
        )
    except Exception as cffi_exc:
        logger.warning("[enrich_from_queue] curl_cffi failed (%s)", cffi_exc)

    # --- Strategy 2: Playwright headless browser ---
    import os
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/ms-playwright"

    try:
        from perfume_trend_sdk.connectors.fragrantica.playwright_client import (
            PlaywrightFragranticaClient,
        )
        pw_client = PlaywrightFragranticaClient(
            timeout_ms=30_000,
            max_retries=1,
            backoff_seconds=5,
            raw_html_dir=None,
        )
        html = pw_client.fetch_page(url)
        return html, "playwright", url
    except Exception as pw_exc:
        logger.warning("[enrich_from_queue] Playwright failed (%s)", pw_exc)

    # --- Strategy 3: plain requests ---
    from perfume_trend_sdk.connectors.fragrantica.client import FragranticaClient

    http_client = FragranticaClient(timeout=20, max_retries=2, backoff_seconds=5)
    html = http_client.fetch_page(url)
    return html, "requests", url


# ---------------------------------------------------------------------------
# Main enrichment logic per item
# ---------------------------------------------------------------------------

def _enrich_item(
    db: Session,
    item: Dict[str, Any],
    dry_run: bool,
) -> str:
    """Attempt enrichment for one queue item. Returns outcome string."""
    from perfume_trend_sdk.connectors.fragrantica.parser import FragranticaParser
    from perfume_trend_sdk.normalizers.fragrantica.normalizer import FragranticaNormalizer
    from perfume_trend_sdk.storage.entities.fragrantica_enrichment_store import (
        FragranticaEnrichmentStore,
    )
    from perfume_trend_sdk.db.market.session import get_database_url

    entity_id = item["entity_id"]
    queue_id = item["queue_id"]
    canonical_name = item.get("canonical_name") or entity_id[:16]

    # 1. Resolve identity
    identity = _resolve_identity(db, entity_id)
    if not identity:
        note = f"no identity map entry for entity_id={entity_id}"
        logger.warning("[enrich_from_queue] SKIP %s: %s", canonical_name, note)
        _update_queue_status(db, queue_id, "failed", note, dry_run)
        return "failed_no_identity"

    # 2. Build URL
    url = _build_url(identity, item.get("fragrance_id"))
    if not url:
        note = (
            f"cannot build URL: brand={identity.get('brand_name')!r} "
            f"perfume={identity.get('perfume_name')!r} "
            f"fragrance_id={identity.get('fragrance_id')!r}"
        )
        logger.warning("[enrich_from_queue] SKIP %s: %s", canonical_name, note)
        _update_queue_status(db, queue_id, "failed", note, dry_run)
        return "failed_no_url"

    logger.info(
        "[enrich_from_queue] Processing %s → %s", canonical_name, url
    )

    if dry_run:
        logger.info("[enrich_from_queue] DRY-RUN: would fetch %s", url)
        return "dry_run"

    # 3. Fetch — curl_cffi with search-based URL resolution on 404,
    #    fall back to Playwright / plain requests.
    try:
        html, fetch_client, actual_url = _fetch_html(
            url,
            brand_name=identity.get("brand_name"),
            perfume_name=identity.get("perfume_name"),
        )
        if actual_url != url:
            logger.info(
                "[enrich_from_queue] URL resolved: %s → %s", url, actual_url
            )
            url = actual_url  # use resolved URL for persist + queue note
        logger.info("[enrich_from_queue] fetched via %s (%d bytes)", fetch_client, len(html))
    except Exception as exc:
        note = f"fetch failed: {exc}"
        logger.error("[enrich_from_queue] FETCH FAIL %s: %s", canonical_name, exc)
        _update_queue_status(db, queue_id, "failed", note, dry_run=False)
        return "failed_fetch"

    # 4. Parse + normalize
    try:
        parser = FragranticaParser()
        parsed = parser.parse(html, url)
        normalizer = FragranticaNormalizer()
        record = normalizer.normalize(parsed, url)
    except Exception as exc:
        note = f"parse/normalize failed: {exc}"
        logger.error("[enrich_from_queue] PARSE FAIL %s: %s", canonical_name, exc)
        _update_queue_status(db, queue_id, "failed", note, dry_run=False)
        return "failed_parse"

    # 5. Persist
    try:
        database_url = get_database_url()
        store = FragranticaEnrichmentStore(database_url)

        fragrance_id = identity.get("fragrance_id") or f"auto_{entity_id}"
        store.persist(
            fragrance_id=fragrance_id,
            market_perfume_uuid=entity_id,
            source_url=url,
            raw_payload_ref="",
            brand_name=identity.get("brand_name"),
            perfume_name=identity.get("perfume_name"),
            record=record,
        )
    except Exception as exc:
        note = f"persist failed: {exc}"
        logger.error("[enrich_from_queue] PERSIST FAIL %s: %s", canonical_name, exc)
        _update_queue_status(db, queue_id, "failed", note, dry_run=False)
        return "failed_persist"

    # 6. Mark done
    has_notes = bool(record.notes_top or record.notes_middle or record.notes_base)
    has_accords = bool(record.accords)
    note = (
        f"enriched. notes={has_notes} accords={has_accords} "
        f"brand={identity.get('brand_name')!r} url={url}"
    )
    _update_queue_status(db, queue_id, "done", note, dry_run=False)
    logger.info(
        "[enrich_from_queue] DONE %s (notes=%s, accords=%s)",
        canonical_name, has_notes, has_accords,
    )
    return "done"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(
    db: Session,
    limit: int = _DEFAULT_LIMIT,
    dry_run: bool = False,
) -> Dict[str, Any]:
    items = _load_queue_items(db, limit)
    logger.info(
        "[enrich_from_queue] %d items loaded from metadata_gap_queue (limit=%d)",
        len(items), limit,
    )

    outcomes: Dict[str, int] = {}
    for item in items:
        outcome = _enrich_item(db, item, dry_run)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        db.flush()

    return {
        "items_loaded": len(items),
        "outcomes": outcomes,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1R: enrich perfumes from metadata_gap_queue")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                        help=f"Max items to process (default: {_DEFAULT_LIMIT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve identity and build URLs but do not fetch or write")
    args = parser.parse_args()

    from perfume_trend_sdk.storage.postgres.db import session_scope

    with session_scope() as db:
        results = run(db, limit=args.limit, dry_run=args.dry_run)

    print()
    print("=== Fragrantica Enrichment from Queue ===")
    print(f"  Items loaded              : {results['items_loaded']}")
    print(f"  Dry run                   : {results['dry_run']}")
    print()
    for outcome, count in results["outcomes"].items():
        print(f"  {outcome:<30}: {count}")


if __name__ == "__main__":
    main()
