#!/usr/bin/env python3
"""
Verify that data persists to the database.
Run: python -m scripts.verify_db_persistence
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")
load_dotenv(_root / ".env.local")

from app.db import init_db, _DEFAULT_DB_PATH, _DATABASE_URL
from app.db import get_db
from app.services.db_repository import get_settings, set_setting

def main():
    init_db()
    print(f"Database: {_DATABASE_URL}")
    if "memory" in _DATABASE_URL.lower():
        print("WARNING: Using in-memory database! Data will not persist.")
        print("Set DATABASE_URL to sqlite:///./data/app.db or omit for default.")
        sys.exit(1)
    print(f"DB path: {_DEFAULT_DB_PATH}")
    print(f"File exists: {os.path.exists(_DEFAULT_DB_PATH)}")

    # Test write and read
    with get_db() as db:
        set_setting(db, "_verify_test", "ok")
    with get_db() as db:
        s = get_settings(db)
        if s.get("_verify_test") == "ok":
            print("Persistence: OK (settings save/load works)")
            with get_db() as db:
                from app.db_models import Setting
                from sqlalchemy import select
                r = db.execute(select(Setting).where(Setting.key == "_verify_test")).scalar_one_or_none()
                if r:
                    db.delete(r)
        else:
            print("Persistence: FAILED")
            sys.exit(1)

if __name__ == "__main__":
    main()
