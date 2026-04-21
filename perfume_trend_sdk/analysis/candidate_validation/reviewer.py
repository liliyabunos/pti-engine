from __future__ import annotations

"""Phase 4a — Candidate Review & Approval helper layer.

Public API::

    from perfume_trend_sdk.analysis.candidate_validation.reviewer import (
        get_candidates_for_review,
        approve_candidate,
        reject_candidate,
        mark_candidate_normalized,
        propose_normalized_form,
        bulk_approve_accepted,
        review_summary,
    )

Review status values
--------------------
  pending_review          — not yet reviewed (default)
  approved_for_promotion  — explicitly approved, ready for Phase 4b
  rejected_final          — explicitly rejected, not for promotion
  needs_normalization     — text needs manual normalization before approval

IMPORTANT: This module NEVER writes to fragrance_master, aliases, or brands.
All writes go to fragrance_candidates only.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from .rules import STOPWORDS

# ---------------------------------------------------------------------------
# Review status constants
# ---------------------------------------------------------------------------

STATUS_PENDING = "pending_review"
STATUS_APPROVED = "approved_for_promotion"
STATUS_REJECTED = "rejected_final"
STATUS_NEEDS_NORM = "needs_normalization"

VALID_REVIEW_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_NEEDS_NORM}

# Allowed approved_entity_type values
VALID_ENTITY_TYPES = {"perfume", "brand", "note", "unknown"}

# ---------------------------------------------------------------------------
# Normalization — context-word stripping
# ---------------------------------------------------------------------------

# Leading tokens that are review/comparison context words, not entity words.
# Kept minimal and explicit — only clear non-entity verbs/descriptors.
_CONTEXT_LEAD_TOKENS: frozenset = frozenset({
    "review", "reviews", "reviewed", "reviewing",
    "compares", "compared", "compare", "comparing",
    "similar",
    "inspired",
    "featuring", "features",
    "unboxing",
    "watch", "watching",
    "check",
    "best", "top", "worst",
    "vs",
})


def propose_normalized_form(text: str) -> tuple:
    """Propose a cleaned normalization of a candidate phrase for promotion.

    Applies two safe transformations:
      1. Strip leading context tokens (known review-context verbs + stopwords)
      2. Strip trailing stopwords (conjunctions, prepositions left at the end)

    Returns:
        (normalized_text: str, changed: bool)

    If stripping would produce a result that is too short (<= 3 chars) or
    identical to the input, returns (original_text, False) — conservative fallback.

    Examples:
        "review the baccarat rouge"    -> ("baccarat rouge", True)
        "compares to baccarat rouge"   -> ("baccarat rouge", True)
        "baccarat rouge scent dna and" -> ("baccarat rouge scent dna", True)
        "xerjoff erba"                 -> ("xerjoff erba", False)
        "dior homme parfum"            -> ("dior homme parfum", False)
    """
    tokens = text.strip().split()
    if not tokens:
        return text, False

    # Step 1: strip leading context tokens (stopwords OR known context verbs)
    start = 0
    while start < len(tokens) and (
        tokens[start] in STOPWORDS or tokens[start] in _CONTEXT_LEAD_TOKENS
    ):
        start += 1

    # Step 2: strip trailing stopwords
    end = len(tokens)
    while end > start and tokens[end - 1] in STOPWORDS:
        end -= 1

    # No change
    if start == 0 and end == len(tokens):
        return text, False

    result = " ".join(tokens[start:end])

    # Safety: if result is too short, keep original
    if len(result) <= 3:
        return text, False

    return result, True


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_candidates_for_review(
    db: Session,
    *,
    validation_status: Optional[str] = None,
    review_status: Optional[str] = None,
    candidate_type: Optional[str] = None,
    min_occurrences: int = 1,
    limit: int = 100,
    order_by: str = "occurrences",
) -> List[Dict[str, Any]]:
    """Return candidates matching the given filters.

    Args:
        validation_status: Filter by Phase 3B status (e.g. 'accepted_rule_based', 'review').
        review_status:      Filter by Phase 4a review status.
        candidate_type:     Filter by type ('perfume', 'brand', 'note', 'unknown').
        min_occurrences:    Minimum occurrence count (default 1 = all).
        limit:              Maximum rows to return.
        order_by:           'occurrences' | 'confidence_score' | 'normalized_text'

    Returns:
        List of dicts with all fragrance_candidates columns.
    """
    allowed_order = {"occurrences", "confidence_score", "normalized_text"}
    if order_by not in allowed_order:
        order_by = "occurrences"

    conditions = ["occurrences >= :min_occ"]
    params: Dict[str, Any] = {"min_occ": min_occurrences, "limit": limit}

    if validation_status:
        conditions.append("validation_status = :vs")
        params["vs"] = validation_status

    if review_status:
        conditions.append("review_status = :rs")
        params["rs"] = review_status

    if candidate_type:
        conditions.append("candidate_type = :ct")
        params["ct"] = candidate_type

    where_clause = " AND ".join(conditions)
    sql = (
        f"SELECT id, normalized_text, raw_text, candidate_type, validation_status, "
        f"  review_status, normalized_candidate_text, approved_entity_type, "
        f"  review_notes, reviewed_at, occurrences, confidence_score, source_platform "
        f"FROM fragrance_candidates "
        f"WHERE {where_clause} "
        f"ORDER BY {order_by} DESC "
        f"LIMIT :limit"
    )
    rows = db.execute(sa_text(sql), params).fetchall()
    keys = [
        "id", "normalized_text", "raw_text", "candidate_type", "validation_status",
        "review_status", "normalized_candidate_text", "approved_entity_type",
        "review_notes", "reviewed_at", "occurrences", "confidence_score", "source_platform",
    ]
    return [dict(zip(keys, row)) for row in rows]


# ---------------------------------------------------------------------------
# Review decision actions
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def approve_candidate(
    db: Session,
    candidate_id: int,
    *,
    entity_type: Optional[str] = None,
    normalized_text: Optional[str] = None,
    notes: Optional[str] = None,
) -> bool:
    """Mark a candidate as approved_for_promotion.

    Args:
        candidate_id:    Row ID in fragrance_candidates.
        entity_type:     Intended KB type ('perfume', 'brand', 'note', 'unknown').
        normalized_text: Cleaned text to use for promotion (overrides auto-proposal).
        notes:           Optional reviewer annotation.

    Returns:
        True if a row was updated, False if candidate not found.
    """
    if entity_type and entity_type not in VALID_ENTITY_TYPES:
        raise ValueError(f"Invalid entity_type: {entity_type!r}. Must be one of {VALID_ENTITY_TYPES}")

    # Auto-propose normalization if none provided
    if normalized_text is None:
        row = db.execute(
            sa_text("SELECT normalized_text FROM fragrance_candidates WHERE id = :id"),
            {"id": candidate_id},
        ).fetchone()
        if not row:
            return False
        proposed, changed = propose_normalized_form(row[0])
        normalized_text = proposed if changed else None  # only set if meaningfully different

    result = db.execute(
        sa_text(
            "UPDATE fragrance_candidates SET "
            "  review_status = :rs, "
            "  approved_entity_type = :et, "
            "  normalized_candidate_text = :nt, "
            "  reviewed_at = :ra, "
            "  review_notes = :rn "
            "WHERE id = :id"
        ),
        {
            "rs": STATUS_APPROVED,
            "et": entity_type,
            "nt": normalized_text,
            "ra": _now_iso(),
            "rn": notes,
            "id": candidate_id,
        },
    )
    db.flush()
    return result.rowcount > 0


def reject_candidate(
    db: Session,
    candidate_id: int,
    *,
    notes: Optional[str] = None,
) -> bool:
    """Mark a candidate as rejected_final.

    Returns:
        True if a row was updated, False if candidate not found.
    """
    result = db.execute(
        sa_text(
            "UPDATE fragrance_candidates SET "
            "  review_status = :rs, "
            "  reviewed_at = :ra, "
            "  review_notes = :rn "
            "WHERE id = :id"
        ),
        {
            "rs": STATUS_REJECTED,
            "ra": _now_iso(),
            "rn": notes,
            "id": candidate_id,
        },
    )
    db.flush()
    return result.rowcount > 0


def mark_candidate_normalized(
    db: Session,
    candidate_id: int,
    normalized_text: str,
    *,
    notes: Optional[str] = None,
) -> bool:
    """Store a normalized promotion form and flag as needs_normalization.

    Use this when a candidate has a clear entity name buried in context words
    but the reviewer wants to flag it for a second-pass before final approval.

    Returns:
        True if a row was updated, False if candidate not found.
    """
    result = db.execute(
        sa_text(
            "UPDATE fragrance_candidates SET "
            "  review_status = :rs, "
            "  normalized_candidate_text = :nt, "
            "  reviewed_at = :ra, "
            "  review_notes = :rn "
            "WHERE id = :id"
        ),
        {
            "rs": STATUS_NEEDS_NORM,
            "nt": normalized_text.strip(),
            "ra": _now_iso(),
            "rn": notes,
            "id": candidate_id,
        },
    )
    db.flush()
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Batch operations (explicit opt-in only — not called by default)
# ---------------------------------------------------------------------------

def bulk_approve_accepted(
    db: Session,
    *,
    min_occurrences: int = 2,
    candidate_types: Optional[List[str]] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Auto-approve accepted_rule_based candidates above an occurrence threshold.

    IMPORTANT: This function is conservative by design.
      - Only operates on validation_status = 'accepted_rule_based'
      - Only operates on candidates still in review_status = 'pending_review'
      - Always applies propose_normalized_form() to set normalized_candidate_text
        when context stripping produces a cleaner form
      - dry_run=True (default) — prints what would change without writing

    Args:
        min_occurrences:  Minimum occurrences to qualify (default: 2).
        candidate_types:  Restrict to these types (default: perfume + brand + note).
        dry_run:          If True, no DB writes — report only.

    Returns:
        Summary dict with counts and examples.
    """
    if candidate_types is None:
        candidate_types = ["perfume", "brand", "note"]

    placeholders = ", ".join(f":t{i}" for i in range(len(candidate_types)))
    params: Dict[str, Any] = {
        "min_occ": min_occurrences,
        **{f"t{i}": t for i, t in enumerate(candidate_types)},
    }

    sql = (
        f"SELECT id, normalized_text, candidate_type, occurrences, source_platform "
        f"FROM fragrance_candidates "
        f"WHERE validation_status = 'accepted_rule_based' "
        f"  AND review_status = 'pending_review' "
        f"  AND occurrences >= :min_occ "
        f"  AND candidate_type IN ({placeholders}) "
        f"ORDER BY occurrences DESC"
    )
    rows = db.execute(sa_text(sql), params).fetchall()

    approved = []
    normalized_examples = []

    for row_id, norm_text, ctype, occ, source in rows:
        proposed, changed = propose_normalized_form(norm_text)
        norm_for_db = proposed if changed else None

        if changed:
            normalized_examples.append({
                "original": norm_text,
                "normalized": proposed,
                "type": ctype,
                "occurrences": occ,
            })

        approved.append({
            "id": row_id,
            "text": norm_text,
            "normalized": norm_for_db,
            "type": ctype,
            "occurrences": occ,
            "source": source,
        })

        if not dry_run:
            db.execute(
                sa_text(
                    "UPDATE fragrance_candidates SET "
                    "  review_status = :rs, "
                    "  approved_entity_type = :et, "
                    "  normalized_candidate_text = :nt, "
                    "  reviewed_at = :ra "
                    "WHERE id = :id"
                ),
                {
                    "rs": STATUS_APPROVED,
                    "et": ctype,
                    "nt": norm_for_db,
                    "ra": _now_iso(),
                    "id": row_id,
                },
            )

    if not dry_run:
        db.flush()

    return {
        "total_approved": len(approved),
        "dry_run": dry_run,
        "min_occurrences": min_occurrences,
        "candidate_types": candidate_types,
        "approved": approved,
        "normalized_examples": normalized_examples,
    }


# ---------------------------------------------------------------------------
# Summary query
# ---------------------------------------------------------------------------

def review_summary(db: Session) -> Dict[str, Any]:
    """Return a count summary of the current review state."""
    rows = db.execute(
        sa_text(
            "SELECT review_status, COUNT(*) "
            "FROM fragrance_candidates "
            "GROUP BY review_status"
        )
    ).fetchall()
    counts = {r[0]: r[1] for r in rows}

    type_approved = db.execute(
        sa_text(
            "SELECT approved_entity_type, COUNT(*) "
            "FROM fragrance_candidates "
            "WHERE review_status = 'approved_for_promotion' "
            "GROUP BY approved_entity_type"
        )
    ).fetchall()

    total = db.execute(
        sa_text("SELECT COUNT(*) FROM fragrance_candidates")
    ).scalar()

    return {
        "total": total,
        "pending_review": counts.get(STATUS_PENDING, 0),
        "approved_for_promotion": counts.get(STATUS_APPROVED, 0),
        "rejected_final": counts.get(STATUS_REJECTED, 0),
        "needs_normalization": counts.get(STATUS_NEEDS_NORM, 0),
        "approved_by_type": {r[0]: r[1] for r in type_approved},
    }
