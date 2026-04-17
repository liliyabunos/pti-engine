#!/usr/bin/env python3
"""
Approve (or upsert) a user in the app_users access control table.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/approve_user.py \
        --email user@example.com --role admin

Roles:  viewer (default) | admin
The script is idempotent — safe to re-run.
"""

import argparse
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve a PTI user")
    parser.add_argument("--email", required=True, help="User email (case-insensitive)")
    parser.add_argument("--role", default="viewer", choices=["viewer", "admin"])
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("ERROR: DATABASE_URL env var is not set.")

    email = args.email.strip().lower()
    now = datetime.now(timezone.utc)

    engine = create_engine(database_url)
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id, access_status FROM app_users WHERE email = :email"),
            {"email": email},
        ).fetchone()

        if existing:
            conn.execute(
                text(
                    "UPDATE app_users "
                    "SET role = :role, access_status = 'approved', "
                    "    approved_at = :now, updated_at = :now "
                    "WHERE email = :email"
                ),
                {"role": args.role, "now": now, "email": email},
            )
            print(f"Updated: {email} → role={args.role}, access_status=approved")
        else:
            conn.execute(
                text(
                    "INSERT INTO app_users "
                    "(id, email, role, access_status, invited_at, approved_at, created_at, updated_at) "
                    "VALUES (:id, :email, :role, 'approved', :now, :now, :now, :now)"
                ),
                {"id": str(uuid.uuid4()), "email": email, "role": args.role, "now": now},
            )
            print(f"Inserted: {email} → role={args.role}, access_status=approved")

    print("Done. User can now log in.")


if __name__ == "__main__":
    main()
