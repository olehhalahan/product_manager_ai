#!/usr/bin/env python3
"""
Remove all rows from onboarding_sessions (test/seed data or full reset).
Uses the same DATABASE_URL as the app (.env / .env.local).

Run: python -m scripts.clear_onboarding_data
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")
load_dotenv(_root / ".env.local")

from app.db import get_db
from app.services.db_repository import delete_all_onboarding_sessions


def main():
    with get_db() as db:
        delete_all_onboarding_sessions(db)
    print("Table onboarding_sessions is now empty.")


if __name__ == "__main__":
    main()
