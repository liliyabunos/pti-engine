from __future__ import annotations

"""
SC1.2A — TikTok Creator Watchlist service layer.

Pure functions operating on SQLAlchemy sessions. No HTTP, no platform API calls.
All TikTok watchlist rows live in creator_platform_accounts where platform='tiktok'.

Public API:
  normalize_handle(raw)          → str  (strips @, URL, whitespace)
  list_accounts(db, **filters)   → list[dict]
  get_account(db, handle)        → dict | None
  add_account(db, handle, ...)   → dict  (insert or update-on-conflict)
  change_status(db, handle, new_status, note) → dict
  bulk_import(db, rows)          → BulkResult

Valid statuses:    pending_review | active | paused | rejected | error
Valid methods:     manual_seed | cross_platform_link | content_mention
                   | user_submission | operator_review
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLATFORM = "tiktok"

VALID_STATUSES = frozenset({
    "pending_review",
    "active",
    "paused",
    "rejected",
    "error",
})

VALID_SOURCE_METHODS = frozenset({
    "manual_seed",
    "cross_platform_link",
    "content_mention",
    "user_submission",
    "operator_review",
})

# TikTok handle: alphanumeric, underscore, dot — 2–24 chars
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,24}$")

# TikTok profile URL patterns
_PROFILE_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9._]{1,24})/?$",
    re.IGNORECASE,
)
# TikTok video URL — must NOT be accepted as a creator
_VIDEO_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._]+/video/\d+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Handle normalization
# ---------------------------------------------------------------------------

def normalize_handle(raw: str) -> str:
    """
    Normalize a TikTok creator handle into a bare handle string.

    Accepts:
        @creator        → creator
        creator         → creator
        https://www.tiktok.com/@creator   → creator
        https://www.tiktok.com/@creator/  → creator

    Raises ValueError for:
        - empty / blank input
        - TikTok video URLs (caller passed a video, not a profile)
        - Unrecognized URL that isn't a TikTok profile
        - Handle contains invalid characters
    """
    if not raw or not raw.strip():
        raise ValueError("handle must not be empty")

    raw = raw.strip()

    # Reject video URLs early
    if _VIDEO_URL_RE.search(raw):
        raise ValueError(f"URL appears to be a TikTok video, not a creator profile: {raw!r}")

    # Handle URL inputs
    if raw.startswith("http://") or raw.startswith("https://"):
        m = _PROFILE_URL_RE.match(raw)
        if not m:
            raise ValueError(f"Not a recognized TikTok profile URL: {raw!r}")
        raw = m.group(1)

    # Strip leading @
    raw = raw.lstrip("@")

    if not raw:
        raise ValueError("handle must not be empty after stripping @")

    if not _HANDLE_RE.match(raw):
        raise ValueError(
            f"Invalid TikTok handle characters: {raw!r}. "
            "Handles must be 1–24 characters: letters, digits, underscore, dot."
        )

    return raw


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class BulkResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    return dict(row._mapping)


def _write_audit(
    db: Session,
    *,
    platform_handle: str,
    action: str,
    old_status: Optional[str],
    new_status: Optional[str],
    source_method: Optional[str],
    note: Optional[str],
) -> None:
    db.execute(
        text("""
            INSERT INTO creator_watchlist_audit_log
                (platform, platform_handle, action, old_status, new_status, source_method, note, created_at)
            VALUES
                (:platform, :handle, :action, :old_status, :new_status, :source_method, :note, :now)
        """),
        {
            "platform": PLATFORM,
            "handle": platform_handle,
            "action": action,
            "old_status": old_status,
            "new_status": new_status,
            "source_method": source_method,
            "note": note,
            "now": _now(),
        },
    )


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def list_accounts(
    db: Session,
    *,
    status: Optional[str] = None,
    source_method: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[dict]:
    """List TikTok watchlist accounts with optional filters."""
    where = ["platform = :platform"]
    params: dict = {"platform": PLATFORM, "limit": limit, "offset": offset}

    if status:
        where.append("status = :status")
        params["status"] = status
    if source_method:
        where.append("source_method = :source_method")
        params["source_method"] = source_method

    where_sql = " AND ".join(where)
    rows = db.execute(
        text(f"""
            SELECT * FROM creator_platform_accounts
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_account(db: Session, platform_handle: str) -> Optional[dict]:
    """Fetch a single TikTok watchlist account by normalized handle."""
    row = db.execute(
        text("""
            SELECT * FROM creator_platform_accounts
            WHERE platform = :platform AND platform_handle = :handle
        """),
        {"platform": PLATFORM, "handle": platform_handle},
    ).fetchone()
    return _row_to_dict(row)


def add_account(
    db: Session,
    *,
    handle: str,
    platform_url: Optional[str] = None,
    display_name: Optional[str] = None,
    category: Optional[str] = None,
    tier: Optional[str] = None,
    status: str = "pending_review",
    seed_source: Optional[str] = None,
    source_method: str = "manual_seed",
    confidence: Optional[float] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    Add a TikTok creator to the watchlist.

    If the handle already exists:
      - Updates only NULL/missing metadata fields (display_name, category, tier, notes)
      - Does NOT change status or seed_source
      - Returns the existing row (no duplicate created)

    Returns the final account dict.
    Raises ValueError on invalid handle/status/source_method.
    """
    normalized = normalize_handle(handle)

    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {sorted(VALID_STATUSES)}")
    if source_method not in VALID_SOURCE_METHODS:
        raise ValueError(f"Invalid source_method: {source_method!r}. Must be one of {sorted(VALID_SOURCE_METHODS)}")

    # Construct canonical profile URL
    if not platform_url:
        platform_url = f"https://www.tiktok.com/@{normalized}"

    now = _now()

    existing = get_account(db, normalized)

    if existing:
        # Update only fields that are currently NULL — preserve status/seed_source
        db.execute(
            text("""
                UPDATE creator_platform_accounts SET
                    display_name = COALESCE(display_name, :display_name),
                    category     = COALESCE(category, :category),
                    tier         = COALESCE(tier, :tier),
                    notes        = COALESCE(notes, :notes),
                    platform_url = COALESCE(platform_url, :platform_url),
                    updated_at   = :now
                WHERE platform = :platform AND platform_handle = :handle
            """),
            {
                "display_name": display_name,
                "category": category,
                "tier": tier,
                "notes": notes,
                "platform_url": platform_url,
                "now": now,
                "platform": PLATFORM,
                "handle": normalized,
            },
        )
        _write_audit(
            db,
            platform_handle=normalized,
            action="update_metadata",
            old_status=existing["status"],
            new_status=existing["status"],
            source_method=source_method,
            note="metadata update on duplicate seed attempt",
        )
        _log.info("[tiktok_watchlist] updated existing handle=%s", normalized)
    else:
        db.execute(
            text("""
                INSERT INTO creator_platform_accounts
                    (platform, platform_handle, platform_url, display_name,
                     category, tier, status, seed_source, source_method,
                     confidence, notes, created_at, updated_at)
                VALUES
                    (:platform, :handle, :platform_url, :display_name,
                     :category, :tier, :status, :seed_source, :source_method,
                     :confidence, :notes, :now, :now)
            """),
            {
                "platform": PLATFORM,
                "handle": normalized,
                "platform_url": platform_url,
                "display_name": display_name,
                "category": category,
                "tier": tier,
                "status": status,
                "seed_source": seed_source,
                "source_method": source_method,
                "confidence": confidence,
                "notes": notes,
                "now": now,
            },
        )
        _write_audit(
            db,
            platform_handle=normalized,
            action="insert",
            old_status=None,
            new_status=status,
            source_method=source_method,
            note=None,
        )
        _log.info("[tiktok_watchlist] inserted handle=%s status=%s", normalized, status)

    db.commit()
    return get_account(db, normalized)


def change_status(
    db: Session,
    platform_handle: str,
    new_status: str,
    *,
    note: Optional[str] = None,
) -> dict:
    """Change status of a TikTok watchlist account. Raises ValueError if not found."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {new_status!r}")

    existing = get_account(db, platform_handle)
    if not existing:
        raise ValueError(f"TikTok account not found: @{platform_handle}")

    old_status = existing["status"]
    now = _now()

    db.execute(
        text("""
            UPDATE creator_platform_accounts
            SET status = :new_status, updated_at = :now
            WHERE platform = :platform AND platform_handle = :handle
        """),
        {"new_status": new_status, "now": now, "platform": PLATFORM, "handle": platform_handle},
    )
    _write_audit(
        db,
        platform_handle=platform_handle,
        action="status_change",
        old_status=old_status,
        new_status=new_status,
        source_method=None,
        note=note,
    )
    db.commit()
    _log.info("[tiktok_watchlist] status change handle=%s %s→%s", platform_handle, old_status, new_status)
    return get_account(db, platform_handle)


def bulk_import(db: Session, rows: List[dict]) -> BulkResult:
    """
    Import multiple TikTok creators from a list of dicts.

    Each dict must have 'handle'. Optional: platform_url, display_name,
    category, tier, status, seed_source, source_method, confidence, notes.

    Errors per row are collected; other rows continue.
    """
    result = BulkResult()
    for i, row in enumerate(rows):
        raw_handle = row.get("handle", "").strip()
        try:
            existing_before = get_account(db, normalize_handle(raw_handle)) if raw_handle else None
        except ValueError:
            existing_before = None

        try:
            add_account(
                db,
                handle=raw_handle,
                platform_url=row.get("platform_url"),
                display_name=row.get("display_name"),
                category=row.get("category"),
                tier=row.get("tier"),
                status=row.get("status", "pending_review"),
                seed_source=row.get("seed_source"),
                source_method=row.get("source_method", "manual_seed"),
                confidence=row.get("confidence"),
                notes=row.get("notes"),
            )
            if existing_before:
                result.updated += 1
            else:
                result.inserted += 1
        except Exception as exc:
            result.errors.append(f"row {i} handle={raw_handle!r}: {exc}")
            result.skipped += 1

    return result
