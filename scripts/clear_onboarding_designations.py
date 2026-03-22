#!/usr/bin/env python3
"""
Set designation = NULL for all onboarding_sessions rows (legacy column no longer used in UI).

Run: python -m scripts.clear_onboarding_designations
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
from app.services.db_repository import clear_onboarding_designation_values


def main():
    with get_db() as db:
        clear_onboarding_designation_values(db)
    print("Cleared designation column on all onboarding_sessions rows.")


if __name__ == "__main__":
    main()
