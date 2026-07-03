#!/usr/bin/env python3
"""IndexNow CLI — submit public canonical URLs to Bing-compatible engines."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEPLOY_URL", "https://cartozo.ai")


def cmd_submit_all() -> int:
    from app.db import get_db
    from app.indexnow import submit_all_public_urls

    with get_db() as db:
        result = submit_all_public_urls(db)
    print(json.dumps(result, indent=2))
    if result.get("skipped"):
        print("IndexNow skipped:", result.get("reason", "unknown"), file=sys.stderr)
        return 0 if result.get("reason") else 1
    if result.get("failed_count"):
        print(f"Failed URLs: {result.get('failed_count')}", file=sys.stderr)
        for url in result.get("failed_urls") or []:
            print(f"  - {url}", file=sys.stderr)
        return 1
    print(f"Submitted {result.get('submitted', 0)} URLs; rejected {result.get('rejected', 0)} private/non-production URLs.")
    return 0


def cmd_submit_one(url: str) -> int:
    from app.indexnow import submit_indexnow_urls

    result = submit_indexnow_urls([url])
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") or result.get("submitted") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Cartozo.ai IndexNow submission")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("submit-indexnow-all-public", help="Submit all public sitemap URLs")
    one = sub.add_parser("submit-indexnow-url", help="Submit a single public URL")
    one.add_argument("url", help="Canonical public URL")
    args = parser.parse_args()
    if args.command == "submit-indexnow-all-public":
        return cmd_submit_all()
    if args.command == "submit-indexnow-url":
        return cmd_submit_one(args.url)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
