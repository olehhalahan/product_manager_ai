#!/usr/bin/env python3
"""
Migrate existing users.json and feedback.json to database (SQLite/PostgreSQL).
Run once if upgrading from file-based storage.
Run: python -m scripts.migrate_json_to_db
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")
load_dotenv(_root / ".env.local")

from app.db import init_db, get_db
from app.db_models import Setting
from app.services.db_repository import (
    DEFAULT_PROMPT_TITLE,
    DEFAULT_PROMPT_DESCRIPTION,
    upsert_user,
    add_feedback,
    set_setting,
)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_USERS_FILE = os.path.join(_DATA_DIR, "users.json")
_FEEDBACK_FILE = os.path.join(_DATA_DIR, "feedback.json")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main():
    init_db()
    with get_db() as db:
        # Seed default settings if empty
        from sqlalchemy import select
        count = db.execute(select(Setting)).scalars().all()
        if not count:
            set_setting(db, "prompt_title", DEFAULT_PROMPT_TITLE)
            set_setting(db, "prompt_description", DEFAULT_PROMPT_DESCRIPTION)
            set_setting(db, "openai_api_key", "")
            print("Seeded default settings.")

        # Migrate users
        users = load_json(_USERS_FILE, {})
        for email, u in users.items():
            upsert_user(db, {
                "email": u.get("email", email),
                "name": u.get("name", ""),
                "provider": u.get("provider", ""),
                "role": u.get("role", "customer"),
            })
        if users:
            print(f"Migrated {len(users)} users.")

        # Migrate feedback
        feedback_list = load_json(_FEEDBACK_FILE, [])
        for fb in feedback_list:
            add_feedback(
                db,
                fb.get("rating", 0),
                fb.get("text", ""),
                fb.get("batch_id", ""),
                fb.get("email", ""),
                fb.get("name", ""),
                timestamp=fb.get("timestamp"),
            )
        if feedback_list:
            print(f"Migrated {len(feedback_list)} feedback entries.")

    print("Migration complete.")


if __name__ == "__main__":
    main()
