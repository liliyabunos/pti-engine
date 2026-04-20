from __future__ import annotations

"""Job: Build Notes & Brand Intelligence Layer (Phase 2).

Reads existing notes/accords/perfume_notes/brands/perfumes data and populates:
  - notes_canonical      (canonical note groups)
  - note_canonical_map   (note → canonical mapping)
  - note_stats           (per-canonical-note usage statistics)
  - accord_stats         (per-accord usage statistics)
  - note_brand_stats     (note × brand relationship)

Safe to run multiple times — fully idempotent.

CLI:
    python3 -m perfume_trend_sdk.jobs.build_notes_intelligence
    python3 -m perfume_trend_sdk.jobs.build_notes_intelligence --validate
"""

import argparse
import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from perfume_trend_sdk.analysis.notes_intelligence.query_layer import validate
from perfume_trend_sdk.analysis.notes_intelligence.stats_builder import run_all
from perfume_trend_sdk.storage.postgres.db import session_scope

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Notes & Brand Intelligence Layer (Phase 2)"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        default=False,
        help="Only run validation checks, do not rebuild stats",
    )
    args = parser.parse_args()

    with session_scope() as session:
        if args.validate:
            result = validate(session)
            print("\n=== Phase 2 Validation ===")
            for k, v in result.items():
                if k == "counts":
                    print("\n  Table row counts:")
                    for tbl, cnt in v.items():
                        print(f"    {tbl:<30} : {cnt}")
                else:
                    status = "✅" if v else "❌"
                    print(f"  {status}  {k}")
            all_pass = all(v for k, v in result.items() if k != "counts")
            print(f"\n  Overall: {'PASS' if all_pass else 'FAIL'}")
            sys.exit(0 if all_pass else 1)
        else:
            summary = run_all(session)

            print("\n=== Notes & Brand Intelligence Build Complete ===")
            print(f"  notes_canonical      : {summary['notes_canonical']}")
            print(f"  note_canonical_map   : {summary['note_canonical_map']}")
            print(f"  note_stats           : {summary['note_stats']}")
            print(f"  accord_stats         : {summary['accord_stats']}")
            print(f"  note_brand_stats     : {summary['note_brand_stats']}")
            print("=================================================\n")


if __name__ == "__main__":
    main()
