"""FTG-1/KB1-MIN — BrandProfile ORM model + DB lookup helpers.

Provides:
  BrandProfile  — SQLAlchemy model for the brand_profiles table
  get_brand_tier(db, brand_name) -> Optional[str]
    Looks up the brand's tier classification from brand_profiles.
    Returns one of: 'designer' | 'niche' | 'clone_house' | 'celebrity' | 'indie'
    Returns None if the brand is not yet in brand_profiles.
  get_brand_profile(db, brand_name) -> Optional[dict]
    Returns full canonical profile including node_type and parent_brand_normalized.
    Added in KB-CAT1-B (migration 048).
  fetch_brand_hierarchy_map(db) -> dict
    Returns {normalized_brand_name: {node_type, parent_normalized}} for all
    non-root brands (collections + sub_brands). Cheap: ~4 rows currently.
    Added in KB-CAT1-D.
  format_brand_hierarchy_label(brand_name, hierarchy_map) -> Optional[str]
    Returns compact label e.g. "Xerjoff · Join the Club" for hierarchy brands.
    Returns None for root brands or brands not in the hierarchy map.
    Added in KB-CAT1-D.

This module is intentionally narrow — it is the Encyclopedia / Canonical
Classification layer in the FTG 4-layer model.  It must not import from the
analysis layer (no circular dependencies).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from perfume_trend_sdk.db.market.base import Base


class BrandProfile(Base):
    """Canonical brand classification record.

    brand_name_normalized — pre-normalized lookup key; matches the output of
        entity_role._normalize(brand_name) exactly.
    brand_tier — one of: 'designer' | 'niche' | 'clone_house' | 'celebrity' | 'indie' | 'mass_market'
    node_type — KB-CAT1-B: 'brand' | 'collection' | 'sub_brand' (default 'brand')
    parent_brand_normalized — KB-CAT1-B: normalized name of parent brand, or NULL
    notes — optional operator annotation
    """

    __tablename__ = "brand_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_name_normalized: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    brand_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, default="brand")
    parent_brand_normalized: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


def _normalize_key(brand_name: str | None) -> Optional[str]:
    """Normalize brand_name using entity_role._normalize(); returns None if empty."""
    if not brand_name:
        return None
    from perfume_trend_sdk.analysis.topic_intelligence.entity_role import _normalize
    return _normalize(brand_name) or None


def get_brand_tier(db: Session, brand_name: str | None) -> Optional[str]:
    """Return the brand's canonical tier from brand_profiles, or None.

    Normalizes brand_name using the same algorithm as entity_role._normalize()
    before querying.  Returns None if the brand is absent from brand_profiles
    (caller should fall back to frozenset lookup in classify_entity_role).

    Safe to call even when brand_name is None or empty.
    """
    key = _normalize_key(brand_name)
    if not key:
        return None
    try:
        row = db.execute(
            sa.text(
                "SELECT brand_tier FROM brand_profiles WHERE brand_name_normalized = :key LIMIT 1"
            ),
            {"key": key},
        ).fetchone()
        return row[0] if row else None
    except Exception:
        # Non-fatal: if table missing or query fails, fall back to frozensets.
        return None


def get_brand_profile(db: Session, brand_name: str | None) -> Optional[dict]:
    """Return full canonical brand profile dict, or None.

    Returns:
        {
            "brand_tier": str,
            "node_type": str,           # 'brand' | 'collection' | 'sub_brand'
            "parent_brand_normalized": str | None,
        }
    or None if the brand is not in brand_profiles.

    Non-fatal: returns None on any DB error.
    Added: KB-CAT1-B (migration 048).
    """
    key = _normalize_key(brand_name)
    if not key:
        return None
    try:
        row = db.execute(
            sa.text(
                "SELECT brand_tier, node_type, parent_brand_normalized "
                "FROM brand_profiles WHERE brand_name_normalized = :key LIMIT 1"
            ),
            {"key": key},
        ).fetchone()
        if not row:
            return None
        return {
            "brand_tier": row[0],
            "node_type": row[1] if row[1] else "brand",
            "parent_brand_normalized": row[2],
        }
    except Exception:
        return None


def fetch_brand_hierarchy_map(db: Session) -> Dict[str, dict]:
    """Return hierarchy map for non-root brands. KB-CAT1-D.

    Returns {brand_name_normalized: {"node_type": str, "parent_normalized": str}}
    only for rows where node_type != 'brand' (collections + sub_brands).
    Result is tiny (currently ~4 rows) — safe to fetch per-request.
    Non-fatal: returns empty dict on any DB error.
    """
    try:
        rows = db.execute(
            sa.text(
                "SELECT brand_name_normalized, node_type, parent_brand_normalized "
                "FROM brand_profiles WHERE node_type != 'brand'"
            )
        ).fetchall()
    except Exception:
        return {}
    return {
        row[0]: {"node_type": row[1], "parent_normalized": row[2]}
        for row in rows
        if row[2]  # parent_brand_normalized must be non-null
    }


def format_brand_hierarchy_label(
    brand_name: Optional[str],
    hierarchy_map: Dict[str, dict],
) -> Optional[str]:
    """Return compact hierarchy label e.g. "Xerjoff · Join the Club". KB-CAT1-D.

    Uses a pre-fetched hierarchy_map (from fetch_brand_hierarchy_map) rather than
    issuing a DB query per brand — safe for bulk use in dashboard / screener rows.

    Returns None for root brands or brands absent from the hierarchy map.
    """
    if not brand_name:
        return None
    from perfume_trend_sdk.analysis.topic_intelligence.entity_role import _normalize
    normalized = _normalize(brand_name) or ""
    info = hierarchy_map.get(normalized)
    if not info:
        return None
    parent_norm: str = info.get("parent_normalized") or ""
    if not parent_norm:
        return None
    # Title-case the normalized parent name
    parent_display = " ".join(w.capitalize() for w in parent_norm.split())
    # Short node name: strip "Parent Brand - " prefix from the original brand_name
    prefix = parent_display + " - "
    if brand_name.startswith(prefix):
        node_short = brand_name[len(prefix):]
    elif brand_name.lower().startswith(prefix.lower()):
        node_short = brand_name[len(prefix):]
    else:
        node_short = brand_name
    return f"{parent_display} · {node_short}"
