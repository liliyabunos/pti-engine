from __future__ import annotations

"""
SC1.2B — TikTok Creator Seed Import Script.

Usage:
    python3 -m perfume_trend_sdk.scripts.seed_tiktok_creators \\
        --file data/tiktok_creators_seed.csv [--dry-run] [--activate]

CSV columns (header required):
    handle          — required: @creator, creator, or full profile URL
    profile_url     — optional: TikTok profile URL
    display_name    — optional
    category        — optional (e.g. "fragrance_reviewer")
    tier            — optional (e.g. "tier_1", "tier_2")
    notes           — optional
    seed_source     — optional (e.g. "manual_seed_v1")

Behaviors:
    --dry-run     Print insert/update/skip counts without writing to DB.
    --activate    Import with status=active (default: pending_review).
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from perfume_trend_sdk.db.market.session import _make_engine, get_database_url
from perfume_trend_sdk.services import tiktok_watchlist as svc

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger(__name__)

_REQUIRED_COLS = {"handle"}
_OPTIONAL_COLS = {"profile_url", "display_name", "category", "tier", "notes", "seed_source"}
_ALL_COLS = _REQUIRED_COLS | _OPTIONAL_COLS


def _load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        missing = _REQUIRED_COLS - {f.strip().lower() for f in reader.fieldnames}
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")
        rows = []
        for i, row in enumerate(reader, start=2):  # 2 = first data row
            clean = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            clean["_line"] = i
            rows.append(clean)
    return rows


def _validate_row(row: dict) -> str | None:
    """Return error string or None if valid."""
    handle = row.get("handle", "")
    if not handle:
        return "empty handle"
    try:
        svc.normalize_handle(handle)
    except ValueError as exc:
        return str(exc)
    return None


def run(file: Path, dry_run: bool, activate: bool) -> None:
    default_status = "active" if activate else "pending_review"
    _log.info("seed_tiktok_creators file=%s dry_run=%s status=%s", file, dry_run, default_status)

    rows = _load_csv(file)
    _log.info("loaded %d row(s) from CSV", len(rows))

    # Pre-validate all rows before touching DB
    invalid = []
    valid_rows = []
    for row in rows:
        err = _validate_row(row)
        if err:
            invalid.append((row.get("_line", "?"), row.get("handle", ""), err))
        else:
            valid_rows.append(row)

    if invalid:
        _log.warning("Validation errors (%d rows rejected):", len(invalid))
        for line, handle, err in invalid:
            _log.warning("  line=%s handle=%r: %s", line, handle, err)

    if dry_run:
        # Simulate: count existing handles to predict insert vs update
        url = get_database_url()
        engine = _make_engine(url)
        with Session(engine) as db:
            would_insert = 0
            would_update = 0
            for row in valid_rows:
                try:
                    norm = svc.normalize_handle(row["handle"])
                    existing = svc.get_account(db, norm)
                    if existing:
                        would_update += 1
                    else:
                        would_insert += 1
                except Exception:
                    pass

        _log.info(
            "[dry-run] would_insert=%d would_update=%d would_skip=%d total_valid=%d total_invalid=%d",
            would_insert, would_update, 0, len(valid_rows), len(invalid),
        )
        print(
            f"\nDRY RUN COMPLETE\n"
            f"  Valid rows:    {len(valid_rows)}\n"
            f"  Would insert:  {would_insert}\n"
            f"  Would update:  {would_update}\n"
            f"  Invalid/skip:  {len(invalid)}\n"
            f"  Errors:        {len(invalid)}\n"
        )
        return

    # Live import
    url = get_database_url()
    engine = _make_engine(url)
    with Session(engine) as db:
        import_rows = [
            {
                "handle": row["handle"],
                "platform_url": row.get("profile_url") or None,
                "display_name": row.get("display_name") or None,
                "category": row.get("category") or None,
                "tier": row.get("tier") or None,
                "notes": row.get("notes") or None,
                "seed_source": row.get("seed_source") or None,
                "status": default_status,
                "source_method": "manual_seed",
            }
            for row in valid_rows
        ]

        result = svc.bulk_import(db, import_rows)

    print(
        f"\nIMPORT COMPLETE\n"
        f"  Inserted:  {result.inserted}\n"
        f"  Updated:   {result.updated}\n"
        f"  Skipped:   {result.skipped}\n"
        f"  Errors:    {len(result.errors)}\n"
    )
    if result.errors:
        _log.warning("Import errors:")
        for e in result.errors:
            _log.warning("  %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed TikTok creator watchlist from CSV")
    parser.add_argument("--file", required=True, type=Path, help="Path to CSV file")
    parser.add_argument("--dry-run", action="store_true", help="Preview only — no DB writes")
    parser.add_argument("--activate", action="store_true",
                        help="Import with status=active (default: pending_review)")
    args = parser.parse_args()

    if not args.file.exists():
        _log.error("File not found: %s", args.file)
        sys.exit(1)

    run(args.file, dry_run=args.dry_run, activate=args.activate)


if __name__ == "__main__":
    main()
