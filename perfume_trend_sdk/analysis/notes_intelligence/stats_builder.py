from __future__ import annotations

"""Stats builder — populates note_stats, accord_stats, note_brand_stats.

Reads from: notes, accords, perfume_notes, perfume_accords, perfumes, brands
Writes to:  notes_canonical, note_canonical_map, note_stats, accord_stats, note_brand_stats

All writes use upsert (INSERT OR REPLACE for SQLite, ON CONFLICT DO UPDATE for Postgres).
Safe to run multiple times — fully idempotent.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.analysis.notes_intelligence.canonicalizer import (
    build_canonical_entries,
    build_note_mapping,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Step 1 — Upsert notes_canonical
# ---------------------------------------------------------------------------

def build_notes_canonical(session: Session) -> Dict[str, str]:
    """Populate notes_canonical from notes table.

    Returns:
        Dict mapping canonical_normalized_name → canonical_note_id (UUID string)
    """
    rows = session.execute(
        text("SELECT id, name, normalized_name FROM notes ORDER BY normalized_name")
    ).fetchall()
    all_notes: List[Tuple[str, str, str]] = [(r[0], r[1], r[2]) for r in rows]

    canonical_entries = build_canonical_entries(all_notes)
    logger.info("[stats_builder] canonical entries to upsert: %d", len(canonical_entries))

    canonical_id_map: Dict[str, str] = {}  # normalized_name → id

    for entry in canonical_entries:
        # Check existing
        existing = session.execute(
            text("SELECT id FROM notes_canonical WHERE normalized_name = :n"),
            {"n": entry["normalized_name"]},
        ).fetchone()

        if existing:
            canonical_id_map[entry["normalized_name"]] = existing[0]
        else:
            new_id = str(uuid.uuid4())
            session.execute(
                text(
                    "INSERT INTO notes_canonical (id, canonical_name, normalized_name, note_family, created_at) "
                    "VALUES (:id, :canonical_name, :normalized_name, :note_family, :created_at)"
                ),
                {
                    "id": new_id,
                    "canonical_name": entry["canonical_name"],
                    "normalized_name": entry["normalized_name"],
                    "note_family": entry["note_family"],
                    "created_at": _now(),
                },
            )
            canonical_id_map[entry["normalized_name"]] = new_id

    session.flush()
    logger.info("[stats_builder] notes_canonical populated: %d entries", len(canonical_id_map))
    return canonical_id_map


# ---------------------------------------------------------------------------
# Step 2 — Populate note_canonical_map
# ---------------------------------------------------------------------------

def build_note_canonical_map(
    session: Session,
    canonical_id_map: Dict[str, str],
) -> Dict[str, str]:
    """Map every note.id → its canonical_note_id.

    Returns:
        Dict note_id → canonical_note_id
    """
    rows = session.execute(
        text("SELECT id, name, normalized_name FROM notes ORDER BY normalized_name")
    ).fetchall()
    all_notes = [(r[0], r[1], r[2]) for r in rows]

    note_to_canonical_norm = build_note_mapping(all_notes)  # note_id → canonical_normalized
    note_id_to_canonical_id: Dict[str, str] = {}

    for note_id, canonical_norm in note_to_canonical_norm.items():
        canonical_note_id = canonical_id_map.get(canonical_norm)
        if not canonical_note_id:
            logger.warning("[stats_builder] no canonical_id for %s — skipping", canonical_norm)
            continue

        note_id_to_canonical_id[note_id] = canonical_note_id

        existing = session.execute(
            text("SELECT id FROM note_canonical_map WHERE note_id = :nid"),
            {"nid": note_id},
        ).fetchone()

        if not existing:
            session.execute(
                text(
                    "INSERT INTO note_canonical_map (id, note_id, canonical_note_id, created_at) "
                    "VALUES (:id, :note_id, :canonical_note_id, :created_at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "note_id": note_id,
                    "canonical_note_id": canonical_note_id,
                    "created_at": _now(),
                },
            )

    session.flush()
    logger.info("[stats_builder] note_canonical_map populated: %d entries", len(note_id_to_canonical_id))
    return note_id_to_canonical_id


# ---------------------------------------------------------------------------
# Step 3 — Compute note_stats
# ---------------------------------------------------------------------------

def build_note_stats(
    session: Session,
    note_id_to_canonical_id: Dict[str, str],
) -> None:
    """Compute and upsert note_stats from perfume_notes."""
    # Load all perfume_notes with their perfume's brand_id
    rows = session.execute(
        text(
            "SELECT pn.note_id, pn.note_position, pn.perfume_id, p.brand_id "
            "FROM perfume_notes pn "
            "JOIN perfumes p ON p.id = pn.perfume_id"
        )
    ).fetchall()

    # Aggregate by canonical_note_id
    perfumes_by_canon: Dict[str, set] = defaultdict(set)
    brands_by_canon: Dict[str, set] = defaultdict(set)
    pos_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for note_id, position, perfume_id, brand_id in rows:
        cid = note_id_to_canonical_id.get(note_id)
        if not cid:
            continue
        perfumes_by_canon[cid].add(perfume_id)
        if brand_id:
            brands_by_canon[cid].add(brand_id)
        pos = (position or "unknown").lower()
        pos_counts[cid][pos] += 1

    now = _now()
    for canonical_note_id in set(note_id_to_canonical_id.values()):
        perfume_count = len(perfumes_by_canon.get(canonical_note_id, set()))
        brand_count = len(brands_by_canon.get(canonical_note_id, set()))
        pc = pos_counts.get(canonical_note_id, {})
        top_count = pc.get("top", 0)
        middle_count = pc.get("middle", 0)
        base_count = pc.get("base", 0)
        unknown_count = pc.get("unknown", 0)

        existing = session.execute(
            text("SELECT id FROM note_stats WHERE canonical_note_id = :cid"),
            {"cid": canonical_note_id},
        ).fetchone()

        if existing:
            session.execute(
                text(
                    "UPDATE note_stats SET "
                    "perfume_count=:pc, brand_count=:bc, "
                    "top_position_count=:tc, middle_position_count=:mc, "
                    "base_position_count=:bsc, unknown_position_count=:uc, "
                    "computed_at=:at "
                    "WHERE canonical_note_id=:cid"
                ),
                {
                    "pc": perfume_count, "bc": brand_count,
                    "tc": top_count, "mc": middle_count,
                    "bsc": base_count, "uc": unknown_count,
                    "at": now, "cid": canonical_note_id,
                },
            )
        else:
            session.execute(
                text(
                    "INSERT INTO note_stats "
                    "(id, canonical_note_id, perfume_count, brand_count, "
                    "top_position_count, middle_position_count, base_position_count, "
                    "unknown_position_count, computed_at) "
                    "VALUES (:id,:cid,:pc,:bc,:tc,:mc,:bsc,:uc,:at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "cid": canonical_note_id,
                    "pc": perfume_count, "bc": brand_count,
                    "tc": top_count, "mc": middle_count,
                    "bsc": base_count, "uc": unknown_count,
                    "at": now,
                },
            )

    session.flush()
    logger.info("[stats_builder] note_stats upserted: %d canonical notes", len(set(note_id_to_canonical_id.values())))


# ---------------------------------------------------------------------------
# Step 4 — Compute accord_stats
# ---------------------------------------------------------------------------

def build_accord_stats(session: Session) -> None:
    """Compute and upsert accord_stats from perfume_accords."""
    rows = session.execute(
        text(
            "SELECT pa.accord_id, pa.perfume_id, p.brand_id "
            "FROM perfume_accords pa "
            "JOIN perfumes p ON p.id = pa.perfume_id"
        )
    ).fetchall()

    perfumes_by_accord: Dict[str, set] = defaultdict(set)
    brands_by_accord: Dict[str, set] = defaultdict(set)

    for accord_id, perfume_id, brand_id in rows:
        perfumes_by_accord[accord_id].add(perfume_id)
        if brand_id:
            brands_by_accord[accord_id].add(brand_id)

    now = _now()
    for accord_id, perfumes in perfumes_by_accord.items():
        perfume_count = len(perfumes)
        brand_count = len(brands_by_accord.get(accord_id, set()))

        existing = session.execute(
            text("SELECT id FROM accord_stats WHERE accord_id = :aid"),
            {"aid": accord_id},
        ).fetchone()

        if existing:
            session.execute(
                text(
                    "UPDATE accord_stats SET perfume_count=:pc, brand_count=:bc, computed_at=:at "
                    "WHERE accord_id=:aid"
                ),
                {"pc": perfume_count, "bc": brand_count, "at": now, "aid": accord_id},
            )
        else:
            session.execute(
                text(
                    "INSERT INTO accord_stats (id, accord_id, perfume_count, brand_count, computed_at) "
                    "VALUES (:id, :aid, :pc, :bc, :at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "aid": accord_id,
                    "pc": perfume_count,
                    "bc": brand_count,
                    "at": now,
                },
            )

    session.flush()
    logger.info("[stats_builder] accord_stats upserted: %d accords", len(perfumes_by_accord))


# ---------------------------------------------------------------------------
# Step 5 — Compute note_brand_stats
# ---------------------------------------------------------------------------

def build_note_brand_stats(
    session: Session,
    note_id_to_canonical_id: Dict[str, str],
) -> None:
    """Compute and upsert note_brand_stats (canonical_note × brand)."""
    rows = session.execute(
        text(
            "SELECT pn.note_id, pn.perfume_id, p.brand_id "
            "FROM perfume_notes pn "
            "JOIN perfumes p ON p.id = pn.perfume_id "
            "WHERE p.brand_id IS NOT NULL"
        )
    ).fetchall()

    # Aggregate: (canonical_note_id, brand_id) → set of perfume_ids
    pair_perfumes: Dict[Tuple[str, str], set] = defaultdict(set)
    # Also track total perfumes per brand (for share calculation)
    brand_total_perfumes: Dict[str, set] = defaultdict(set)

    for note_id, perfume_id, brand_id in rows:
        cid = note_id_to_canonical_id.get(note_id)
        if not cid:
            continue
        pair_perfumes[(cid, brand_id)].add(perfume_id)
        brand_total_perfumes[brand_id].add(perfume_id)

    now = _now()
    for (canonical_note_id, brand_id), perfumes in pair_perfumes.items():
        perfume_count = len(perfumes)
        brand_total = len(brand_total_perfumes.get(brand_id, set()))
        share = round(perfume_count / brand_total, 4) if brand_total > 0 else 0.0

        existing = session.execute(
            text(
                "SELECT id FROM note_brand_stats "
                "WHERE canonical_note_id=:cid AND brand_id=:bid"
            ),
            {"cid": canonical_note_id, "bid": brand_id},
        ).fetchone()

        if existing:
            session.execute(
                text(
                    "UPDATE note_brand_stats SET perfume_count=:pc, share=:sh, computed_at=:at "
                    "WHERE canonical_note_id=:cid AND brand_id=:bid"
                ),
                {
                    "pc": perfume_count, "sh": share, "at": now,
                    "cid": canonical_note_id, "bid": brand_id,
                },
            )
        else:
            session.execute(
                text(
                    "INSERT INTO note_brand_stats "
                    "(id, canonical_note_id, brand_id, perfume_count, share, computed_at) "
                    "VALUES (:id,:cid,:bid,:pc,:sh,:at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "cid": canonical_note_id, "bid": brand_id,
                    "pc": perfume_count, "sh": share, "at": now,
                },
            )

    session.flush()
    logger.info(
        "[stats_builder] note_brand_stats upserted: %d note×brand pairs",
        len(pair_perfumes),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all(session: Session) -> Dict[str, Any]:
    """Run all stats builders in order. Returns a summary dict."""
    logger.info("[stats_builder] starting full build")

    canonical_id_map = build_notes_canonical(session)
    note_id_to_canonical_id = build_note_canonical_map(session, canonical_id_map)
    build_note_stats(session, note_id_to_canonical_id)
    build_accord_stats(session)
    build_note_brand_stats(session, note_id_to_canonical_id)

    # Collect row counts
    def count(tbl: str) -> int:
        return session.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar() or 0

    summary = {
        "notes_canonical": count("notes_canonical"),
        "note_canonical_map": count("note_canonical_map"),
        "note_stats": count("note_stats"),
        "accord_stats": count("accord_stats"),
        "note_brand_stats": count("note_brand_stats"),
    }
    logger.info("[stats_builder] build complete: %s", summary)
    return summary
