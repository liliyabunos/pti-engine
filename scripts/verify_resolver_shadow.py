"""
Phase R1 — Shadow verification: compare SQLite resolver vs Postgres resolver.

Checks:
  1. Row count parity (brands, perfumes, aliases, fragrance_master)
  2. Resolver output parity for a fixed sample of known queries
  3. Spot-check that Postgres hot path (get_perfume_by_alias) returns results

Run after migrate_resolver_to_postgres.py to confirm Postgres resolver is
equivalent to SQLite before cutting over production pipelines.

Usage:
    DATABASE_URL=... python3 scripts/verify_resolver_shadow.py
    DATABASE_URL=... python3 scripts/verify_resolver_shadow.py --sqlite data/resolver/pti.db
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_SQLITE = str(Path(__file__).resolve().parent.parent / "data" / "resolver" / "pti.db")

# Fixed sample queries — well-known perfumes that must resolve in both stores.
SAMPLE_QUERIES = [
    # Common short-form aliases
    "br540",
    "sauvage",
    "aventus",
    "delina",
    # Full canonical forms
    "baccarat rouge 540",
    "dior sauvage",
    "creed aventus",
    "parfums de marly delina",
    # Abbreviations
    "oud wood",
    "black orchid",
    "by the fireplace",
    "lost cherry",
    "tobacco vanille",
    "erba pura",
    "good girl",
    "ysl libre",
]

_PASS = "✅"
_FAIL = "❌"
_WARN = "⚠️ "


def _compare_counts(sqlite_store, pg_store) -> list[str]:
    failures = []
    tables = ["brands", "perfumes", "aliases", "fragrance_master"]
    print("\n── Row count parity ────────────────────────────────────────────")
    print(f"  {'Table':<25} {'SQLite':>10} {'Postgres':>10} {'Match':>8}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*8}")
    for t in tables:
        sq = sqlite_store.count_rows(t)
        pg = pg_store.count_rows(t)
        match = sq == pg
        icon = _PASS if match else _WARN
        print(f"  {t:<25} {sq:>10,} {pg:>10,} {icon:>8}")
        if not match:
            # Counts may differ slightly due to idempotent upserts on collision;
            # flag but don't hard-fail — the hot path test is the real signal.
            failures.append(f"count mismatch: {t} SQLite={sq} Postgres={pg}")
    return failures


def _compare_resolver_output(sqlite_store, pg_store) -> list[str]:
    failures = []
    print("\n── Resolver output parity ──────────────────────────────────────")
    print(f"  {'Query':<35} {'SQLite hit':^15} {'Postgres hit':^15} {'Match':>8}")
    print(f"  {'-'*35} {'-'*15} {'-'*15} {'-'*8}")
    for query in SAMPLE_QUERIES:
        sq_result = sqlite_store.get_perfume_by_alias(query)
        pg_result = pg_store.get_perfume_by_alias(query)

        sq_name = sq_result["canonical_name"] if sq_result else "—"
        pg_name = pg_result["canonical_name"] if pg_result else "—"

        # Match: both None OR both have the same canonical_name
        match = (sq_result is None and pg_result is None) or (
            sq_result is not None
            and pg_result is not None
            and sq_result["canonical_name"] == pg_result["canonical_name"]
        )
        icon = _PASS if match else _FAIL
        print(f"  {query:<35} {sq_name[:15]:^15} {pg_name[:15]:^15} {icon:>8}")
        if not match:
            failures.append(
                f"resolver mismatch for {query!r}: "
                f"SQLite={sq_result!r} Postgres={pg_result!r}"
            )

    # Known aliases that MUST resolve in both
    must_resolve = [q for q in SAMPLE_QUERIES if q in ("br540", "sauvage", "aventus", "delina")]
    for q in must_resolve:
        pg_result = pg_store.get_perfume_by_alias(q)
        if pg_result is None:
            failures.append(f"critical alias not found in Postgres: {q!r}")

    return failures


def verify(sqlite_path: str) -> bool:
    from perfume_trend_sdk.storage.entities.fragrance_master_store import FragranceMasterStore
    from perfume_trend_sdk.storage.entities.pg_resolver_store import PgResolverStore

    if not os.environ.get("DATABASE_URL"):
        print("[verify] ERROR: DATABASE_URL is not set.")
        sys.exit(1)

    if not Path(sqlite_path).exists():
        print(f"[verify] ERROR: SQLite file not found: {sqlite_path}")
        sys.exit(1)

    print(f"[verify] SQLite: {sqlite_path}")
    print(f"[verify] Postgres: {os.environ['DATABASE_URL'].split('@')[-1]}")

    sqlite_store = FragranceMasterStore(sqlite_path)
    pg_store = PgResolverStore()

    failures: list[str] = []
    failures += _compare_counts(sqlite_store, pg_store)
    failures += _compare_resolver_output(sqlite_store, pg_store)

    print("\n── Summary ─────────────────────────────────────────────────────")
    if not failures:
        print(f"  {_PASS} All checks passed — Postgres resolver is equivalent to SQLite.")
        print("  Production cutover is safe.")
        return True
    else:
        print(f"  {_FAIL} {len(failures)} check(s) failed:")
        for f in failures:
            print(f"    - {f}")
        print("\n  Run migrate_resolver_to_postgres.py first, then re-verify.")
        return False


def main() -> None:
    p = argparse.ArgumentParser(
        description="Shadow-verify Postgres resolver against SQLite source."
    )
    p.add_argument(
        "--sqlite",
        default=DEFAULT_SQLITE,
        help="Path to SQLite resolver DB (default: data/resolver/pti.db)",
    )
    args = p.parse_args()
    ok = verify(args.sqlite)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
