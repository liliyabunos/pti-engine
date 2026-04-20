from __future__ import annotations

"""Query layer — read-only access to notes & brand intelligence tables.

All functions accept a SQLAlchemy Session and return plain dicts/lists.
No ORM models are returned — consumers see only JSON-serializable data.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Note queries
# ---------------------------------------------------------------------------

def get_top_notes(session: Session, limit: int = 20) -> List[Dict[str, Any]]:
    """Return top N canonical notes by perfume_count (descending).

    Each dict: {canonical_name, normalized_name, note_family, perfume_count,
                brand_count, top_count, middle_count, base_count}
    """
    rows = session.execute(
        text(
            "SELECT nc.canonical_name, nc.normalized_name, nc.note_family, "
            "ns.perfume_count, ns.brand_count, "
            "ns.top_position_count, ns.middle_position_count, ns.base_position_count "
            "FROM note_stats ns "
            "JOIN notes_canonical nc ON nc.id = ns.canonical_note_id "
            "WHERE ns.perfume_count > 0 "
            "ORDER BY ns.perfume_count DESC, ns.brand_count DESC "
            "LIMIT :lim"
        ),
        {"lim": limit},
    ).fetchall()

    return [
        {
            "canonical_name": r[0],
            "normalized_name": r[1],
            "note_family": r[2],
            "perfume_count": r[3],
            "brand_count": r[4],
            "top_position_count": r[5],
            "middle_position_count": r[6],
            "base_position_count": r[7],
        }
        for r in rows
    ]


def get_top_accords(session: Session, limit: int = 10) -> List[Dict[str, Any]]:
    """Return top N accords by perfume_count."""
    rows = session.execute(
        text(
            "SELECT a.name, a.normalized_name, s.perfume_count, s.brand_count "
            "FROM accord_stats s "
            "JOIN accords a ON a.id = s.accord_id "
            "WHERE s.perfume_count > 0 "
            "ORDER BY s.perfume_count DESC "
            "LIMIT :lim"
        ),
        {"lim": limit},
    ).fetchall()

    return [
        {
            "accord_name": r[0],
            "normalized_name": r[1],
            "perfume_count": r[2],
            "brand_count": r[3],
        }
        for r in rows
    ]


def get_notes_by_brand(session: Session, brand_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Return notes most used by a specific brand, ordered by perfume_count."""
    rows = session.execute(
        text(
            "SELECT nc.canonical_name, nc.note_family, nbs.perfume_count, nbs.share "
            "FROM note_brand_stats nbs "
            "JOIN notes_canonical nc ON nc.id = nbs.canonical_note_id "
            "WHERE nbs.brand_id = :bid "
            "ORDER BY nbs.perfume_count DESC "
            "LIMIT :lim"
        ),
        {"bid": brand_id, "lim": limit},
    ).fetchall()

    return [
        {
            "canonical_name": r[0],
            "note_family": r[1],
            "perfume_count": r[2],
            "share": r[3],
        }
        for r in rows
    ]


def get_brands_by_note(session: Session, canonical_note_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Return brands that use a specific canonical note, ordered by perfume_count."""
    rows = session.execute(
        text(
            "SELECT b.name, b.slug, nbs.perfume_count, nbs.share "
            "FROM note_brand_stats nbs "
            "JOIN brands b ON CAST(b.id AS text) = nbs.brand_id "
            "WHERE nbs.canonical_note_id = :cid "
            "ORDER BY nbs.perfume_count DESC "
            "LIMIT :lim"
        ),
        {"cid": canonical_note_id, "lim": limit},
    ).fetchall()

    return [
        {
            "brand_name": r[0],
            "brand_slug": r[1],
            "perfume_count": r[2],
            "share": r[3],
        }
        for r in rows
    ]


def get_brands_by_note_name(
    session: Session, normalized_note_name: str, limit: int = 20
) -> List[Dict[str, Any]]:
    """Convenience wrapper — look up brands by canonical note normalized name."""
    row = session.execute(
        text("SELECT id FROM notes_canonical WHERE normalized_name = :n"),
        {"n": normalized_note_name},
    ).fetchone()
    if not row:
        return []
    return get_brands_by_note(session, row[0], limit=limit)


def get_perfumes_by_note(
    session: Session, canonical_note_id: str, limit: int = 50
) -> List[Dict[str, Any]]:
    """Return perfumes that contain a specific canonical note."""
    rows = session.execute(
        text(
            "SELECT p.name, p.slug, b.name as brand_name, pn.note_position "
            "FROM perfume_notes pn "
            "JOIN note_canonical_map ncm ON ncm.note_id = pn.note_id "
            "JOIN perfumes p ON CAST(p.id AS text) = pn.perfume_id "
            "LEFT JOIN brands b ON CAST(b.id AS text) = CAST(p.brand_id AS text) "
            "WHERE ncm.canonical_note_id = :cid "
            "ORDER BY b.name, p.name "
            "LIMIT :lim"
        ),
        {"cid": canonical_note_id, "lim": limit},
    ).fetchall()

    return [
        {
            "perfume_name": r[0],
            "perfume_slug": r[1],
            "brand_name": r[2],
            "note_position": r[3],
        }
        for r in rows
    ]


def get_perfumes_by_note_name(
    session: Session, normalized_note_name: str, limit: int = 50
) -> List[Dict[str, Any]]:
    """Convenience wrapper — look up perfumes by canonical note normalized name."""
    row = session.execute(
        text("SELECT id FROM notes_canonical WHERE normalized_name = :n"),
        {"n": normalized_note_name},
    ).fetchone()
    if not row:
        return []
    return get_perfumes_by_note(session, row[0], limit=limit)


# ---------------------------------------------------------------------------
# Brand intelligence queries
# ---------------------------------------------------------------------------

def get_brand_note_profile(session: Session, brand_id: str) -> Optional[Dict[str, Any]]:
    """Return a full note/accord profile for a brand.

    Returns dict with:
      brand_id, brand_name, perfume_count, top_notes, top_accords
    """
    brand_row = session.execute(
        text("SELECT id, name, slug FROM brands WHERE CAST(id AS text) = :bid"),
        {"bid": brand_id},
    ).fetchone()
    if not brand_row:
        return None

    # Count perfumes for this brand that have notes
    perfume_count_row = session.execute(
        text(
            "SELECT COUNT(DISTINCT pn.perfume_id) "
            "FROM perfume_notes pn "
            "JOIN perfumes p ON CAST(p.id AS text) = pn.perfume_id "
            "WHERE CAST(p.brand_id AS text) = :bid"
        ),
        {"bid": brand_id},
    ).fetchone()
    perfume_count = perfume_count_row[0] if perfume_count_row else 0

    top_notes = get_notes_by_brand(session, brand_id, limit=10)

    # Top accords for this brand
    accord_rows = session.execute(
        text(
            "SELECT a.name, COUNT(DISTINCT pa.perfume_id) as cnt "
            "FROM perfume_accords pa "
            "JOIN accords a ON a.id = pa.accord_id "
            "JOIN perfumes p ON CAST(p.id AS text) = pa.perfume_id "
            "WHERE CAST(p.brand_id AS text) = :bid "
            "GROUP BY a.name "
            "ORDER BY cnt DESC "
            "LIMIT 5"
        ),
        {"bid": brand_id},
    ).fetchall()
    top_accords = [{"accord_name": r[0], "perfume_count": r[1]} for r in accord_rows]

    return {
        "brand_id": brand_id,
        "brand_name": brand_row[1],
        "brand_slug": brand_row[2],
        "enriched_perfume_count": perfume_count,
        "top_notes": top_notes,
        "top_accords": top_accords,
    }


def get_brands_with_most_notes(session: Session, limit: int = 10) -> List[Dict[str, Any]]:
    """Return brands ranked by number of distinct canonical notes used."""
    rows = session.execute(
        text(
            "SELECT b.name, b.slug, COUNT(DISTINCT nbs.canonical_note_id) as note_count, "
            "SUM(nbs.perfume_count) as total_perfume_note_links "
            "FROM note_brand_stats nbs "
            "JOIN brands b ON CAST(b.id AS text) = nbs.brand_id "
            "GROUP BY b.id, b.name, b.slug "
            "ORDER BY note_count DESC, total_perfume_note_links DESC "
            "LIMIT :lim"
        ),
        {"lim": limit},
    ).fetchall()

    return [
        {
            "brand_name": r[0],
            "brand_slug": r[1],
            "distinct_canonical_notes": r[2],
            "total_perfume_note_links": r[3],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate(session: Session) -> Dict[str, Any]:
    """Run validation checks. Returns dict with pass/fail status per check."""
    def count(tbl: str) -> int:
        return session.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar() or 0

    def has_rows(tbl: str) -> bool:
        return count(tbl) > 0

    top_notes = get_top_notes(session, limit=1)
    brand_stats = get_brands_with_most_notes(session, limit=1)
    top_accords = get_top_accords(session, limit=1)

    # Check for note duplicates in note_canonical_map
    dup_check = session.execute(
        text("SELECT COUNT(*) FROM (SELECT note_id FROM note_canonical_map GROUP BY note_id HAVING COUNT(*) > 1)")
    ).scalar() or 0

    return {
        "notes_canonical_populated": has_rows("notes_canonical"),
        "note_canonical_map_populated": has_rows("note_canonical_map"),
        "note_stats_populated": has_rows("note_stats"),
        "accord_stats_populated": has_rows("accord_stats"),
        "note_brand_stats_populated": has_rows("note_brand_stats"),
        "top_notes_returns_result": len(top_notes) > 0,
        "brand_stats_returns_result": len(brand_stats) > 0,
        "top_accords_returns_result": len(top_accords) > 0,
        "no_duplicate_note_mappings": dup_check == 0,
        "counts": {
            "notes_canonical": count("notes_canonical"),
            "note_canonical_map": count("note_canonical_map"),
            "note_stats": count("note_stats"),
            "accord_stats": count("accord_stats"),
            "note_brand_stats": count("note_brand_stats"),
        },
    }
