from __future__ import annotations

"""
Job: send_daily_digest

Sends the daily market intelligence email digest.
Runs at 00:00 UTC via Railway cron (pipeline-email service).
Summarises the previous UTC day's top movers, signals, and market highlights.

Usage:
    python3 -m perfume_trend_sdk.jobs.send_daily_digest

Behaviour:
    - Derives report_date as yesterday UTC (no --date argument needed).
    - Checks deduplication table before sending — will not send twice for the
      same report_date.
    - Exits 0 on success or deduplicated skip.
    - Exits 1 on send failure (Railway will retry up to maxRetries).

Environment variables required:
    DATABASE_URL        Railway Postgres connection string
    RESEND_API_KEY      Transactional email API key (Resend)
    DIGEST_FROM_EMAIL   Sender address (e.g. reports@yourdomain.com)
    DIGEST_TO_EMAIL     Recipient address or comma-separated list

NOT YET IMPLEMENTED.
This stub reserves the module path and documents the interface.
Remove this notice and implement when email delivery is ready.
"""

import logging
import sys

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logger.error(
        "send_daily_digest is not yet implemented. "
        "Implement this job before activating the pipeline-email Railway service."
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
