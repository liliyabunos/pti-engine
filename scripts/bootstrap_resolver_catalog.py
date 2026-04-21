"""
Phase 5 — Resolver Catalog Bootstrap (idempotent, one-time guarded job).

Purpose:
    Seed the resolver KB with the Parfumo/TidyTuesday catalog (~59k perfumes)
    if it has not been seeded yet. Safe to run multiple times.

Guard:
    Checks SELECT COUNT(*) FROM fragrance_master WHERE source='kaggle_v1'.
    If > 0 → logs "SKIPPED" and exits immediately (no download, no write).
    If = 0 → downloads CSV, runs full import, logs "IMPORTED".

Usage:
    # Local
    python3 scripts/bootstrap_resolver_catalog.py

    # On Railway (explicit one-time trigger)
    railway run --service pipeline-daily python3 scripts/bootstrap_resolver_catalog.py

    # Dry-run (shows what would happen, no writes)
    python3 scripts/bootstrap_resolver_catalog.py --dry-run

Exit codes:
    0  — SKIPPED (already seeded) or IMPORTED (success)
    1  — ERROR (download failed, import failed, DB unreachable)
"""

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE_TAG = "kaggle_v1"
CATALOG_URL = (
    "https://raw.githubusercontent.com/rfordatascience/tidytuesday"
    "/main/data/2024/2024-12-10/parfumo_data_clean.csv"
)
_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "resolver" / "pti.db"
DB_PATH = Path(os.environ.get("RESOLVER_DB_PATH", str(_DEFAULT_DB)))


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[bootstrap_resolver_catalog] {ts} {msg}", flush=True)


def existing_count(db_path: Path) -> int:
    con = sqlite3.connect(str(db_path))
    try:
        return con.execute(
            "SELECT COUNT(*) FROM fragrance_master WHERE source=?", (SOURCE_TAG,)
        ).fetchone()[0]
    finally:
        con.close()


def download_csv(url: str, dest: Path) -> None:
    log(f"Downloading catalog from {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "PTI-bootstrap/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        total = 0
        while chunk := resp.read(65536):
            out.write(chunk)
            total += len(chunk)
    log(f"Download complete ({total / 1024 / 1024:.1f} MB)")


def run_import(csv_path: Path, dry_run: bool) -> int:
    import_script = Path(__file__).resolve().parent / "import_kaggle_v1.py"
    cmd = [sys.executable, str(import_script), "--csv", str(csv_path)]
    if dry_run:
        cmd.append("--dry-run")
    log(f"Running import: {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without writing")
    parser.add_argument("--force", action="store_true",
                        help="Run import even if kaggle_v1 rows already exist")
    args = parser.parse_args()

    log(f"Starting — DB: {DB_PATH}")

    if not DB_PATH.exists():
        log(f"ERROR: Resolver DB not found at {DB_PATH}")
        sys.exit(1)

    count = existing_count(DB_PATH)

    if count > 0 and not args.force:
        log(
            f"SKIPPED — kaggle_v1 already seeded "
            f"({count:,} rows in fragrance_master). "
            f"Pass --force to re-run."
        )
        sys.exit(0)

    if count > 0 and args.force:
        log(f"WARNING: --force specified — {count:,} existing kaggle_v1 rows will be skipped by dedup")

    if args.dry_run:
        log("DRY-RUN mode — will download but not write")

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        csv_path = Path(tmp.name)

    try:
        download_csv(CATALOG_URL, csv_path)
        exit_code = run_import(csv_path, dry_run=args.dry_run)
    except Exception as exc:
        log(f"ERROR: {exc}")
        sys.exit(1)
    finally:
        csv_path.unlink(missing_ok=True)

    if exit_code != 0:
        log(f"ERROR: import script exited with code {exit_code}")
        sys.exit(1)

    final_count = existing_count(DB_PATH)
    log(
        f"IMPORTED — kaggle_v1 rows in fragrance_master: {final_count:,}"
        if not args.dry_run
        else "DRY-RUN complete — no writes performed"
    )


if __name__ == "__main__":
    main()
