#!/usr/bin/env python3
"""
DEV ONLY: fake onboarding rows for UI testing.
Production analytics should use real events from the app (see _onboarding_track in main.py).
Run: python -m scripts.seed_onboarding_demo
"""
import os
import random
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")
load_dotenv(_root / ".env.local")

from datetime import datetime, timedelta, timezone

from app.db import get_db
from app.db_models import OnboardingSession

SOURCES = ["google_search", "linkedin", "friend_colleague", "utm:newsletter", "reddit"]


def main():
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    with get_db() as db:
        for i in range(24):
            started = now - timedelta(minutes=rng.randint(10, 8000))
            public_id = uuid.uuid4().hex
            max_step = rng.randint(1, 7)
            completed = rng.random() < 0.88 and max_step >= 6
            if completed:
                max_step = 7
                status = "completed"
                completed_at = started + timedelta(minutes=rng.randint(1, 120))
                dur = max(1, int((completed_at - started).total_seconds()))
            else:
                status = "in_progress"
                completed_at = None
                dur = None

            db.add(
                OnboardingSession(
                    public_id=public_id,
                    email=f"demo{i + 1}@example.com",
                    name=f"Demo User {i + 1}",
                    source=rng.choice(SOURCES),
                    max_step=max_step,
                    status=status,
                    started_at=started,
                    updated_at=now,
                    completed_at=completed_at,
                    duration_seconds=dur,
                )
            )
    print("Inserted 24 demo onboarding sessions.")


if __name__ == "__main__":
    main()
