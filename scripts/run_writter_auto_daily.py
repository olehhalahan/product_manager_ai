"""
Run the daily automatic Writer job from CLI (same logic as cron / admin).

Usage:
  python scripts/run_writter_auto_daily.py
  python scripts/run_writter_auto_daily.py --force --count 5
"""
from __future__ import annotations

import argparse
import os
import sys

# Ensure project root is on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    p = argparse.ArgumentParser(description="Run Writter auto-daily SEO pipeline")
    p.add_argument("--force", action="store_true", help="Ignore today's published quota (test batch)")
    p.add_argument("--count", type=int, default=None, help="Override number of articles for this run (1–15)")
    args = p.parse_args()

    os.chdir(_ROOT)
    from app.db import init_db

    init_db()
    from app.services.writter_auto_job import run_writter_auto_daily

    out = run_writter_auto_daily(
        "cli",
        force_full_count=bool(args.force),
        override_count=args.count,
    )
    print(out)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
