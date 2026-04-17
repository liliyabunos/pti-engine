#!/usr/bin/env python3
"""
One-time admin workaround: generate a Supabase magic link without sending email.
Uses the Supabase Admin API (service role key) — never exposes the key to the browser.

Usage:
    SUPABASE_URL=https://xxx.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=eyJ... \
    python3 scripts/generate_magic_link.py --email contact@liliyasaroma.com
"""

import argparse
import os
import sys
import urllib.request
import urllib.error
import json

REDIRECT_TO = "https://pti-frontend-production.up.railway.app/auth/callback"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url:
        sys.exit("ERROR: SUPABASE_URL env var is not set.")
    if not service_role_key:
        sys.exit("ERROR: SUPABASE_SERVICE_ROLE_KEY env var is not set.")

    url = f"{supabase_url}/auth/v1/admin/users/{_get_user_id(supabase_url, service_role_key, args.email)}/magiclink" \
          if False else f"{supabase_url}/auth/v1/admin/generate_link"

    payload = json.dumps({
        "type": "magiclink",
        "email": args.email,
        "options": {
            "redirect_to": REDIRECT_TO,
        },
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        sys.exit(f"Supabase API error {e.code}: {error_body}")

    action_link = body.get("action_link") or body.get("properties", {}).get("action_link")
    if not action_link:
        sys.exit(f"No action_link in response. Full response:\n{json.dumps(body, indent=2)}")

    print("\n=== MAGIC LINK (open this in your browser) ===\n")
    print(action_link)
    print("\n=== expires in ~1 hour ===\n")


def _get_user_id(supabase_url: str, key: str, email: str) -> str:
    """Not used — kept for reference only."""
    return ""


if __name__ == "__main__":
    main()
