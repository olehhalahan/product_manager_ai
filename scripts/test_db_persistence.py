#!/usr/bin/env python3
"""
Test that important data persists to DB, not RAM.
Runs write in one process, read in a fresh process - proves data is on disk.
Run: python -m scripts.test_db_persistence
"""
import os
import sys
import subprocess
import uuid

# Add project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Load env before any app imports
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))
load_dotenv(os.path.join(ROOT, ".env.local"))

# Check we're not using in-memory DB
DATABASE_URL = os.getenv("DATABASE_URL", "")
if ":memory:" in DATABASE_URL.lower():
    print("FAIL: DATABASE_URL uses :memory: - data will not persist")
    sys.exit(1)

# Run writer and reader as separate subprocesses (no shared memory)
def run_script(script: str, extra_env: dict = None) -> tuple[bool, str]:
    """Run Python script in subprocess, return (success, output)."""
    env = {**os.environ, "PYTHONPATH": ROOT}
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    out = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, out


# ─── Writer: write test data to DB ───────────────────────────────────────────
WRITER_SCRIPT = '''
import os, sys
sys.path.insert(0, os.environ.get("PYTHONPATH", "."))
from dotenv import load_dotenv
load_dotenv(".env"); load_dotenv(".env.local")

from app.db import init_db, get_db
from app.services.db_repository import (
    set_setting, save_pending_upload, save_contact_submission,
    add_feedback, create_batch, create_chat_session, update_chat_session,
)
from app.services.postgres_storage import PostgresStorage
from app.models import NormalizedProduct, ProductAction

init_db()
test_id = os.environ.get("TEST_ID", "test-unknown")

# 1. Settings
with get_db() as db:
    set_setting(db, "_test_api_key", "sk-test-12345")
    set_setting(db, "_test_prompt", "Test prompt for persistence")

# 2. Pending upload
with get_db() as db:
    save_pending_upload(db, f"_test_upload_{test_id}", [{"id": "1", "title": "Test"}], "optimize", "en", "standard")

# 3. Contact submission
with get_db() as db:
    save_contact_submission(db, "TestName", "TestSurname", "test@example.com", "+123")

# 4. Feedback
with get_db() as db:
    add_feedback(db, 5, "Great!", f"batch_{test_id}", "fb@test.com", "Feedbacker")

# 5. Batch (minimal) + test product field update persistence
storage = PostgresStorage()
prod = NormalizedProduct(id="p1", title="T", description="D", link="", image_link="", brand="", category="", product_type="")
storage.create_batch(f"_test_batch_{test_id}", [prod], {"p1": ProductAction.SKIP}, "standard")
# Simulate inline edit - must persist
batch = storage.get_batch(f"_test_batch_{test_id}")
if batch and batch.products:
    batch.products[0].optimized_title = "PersistedTitle"
    storage._save_batch(batch)

# 6. Chat session (create then update in separate transactions)
with get_db() as db:
    create_chat_session(db, f"_test_chat_{test_id}", "chat@test.com")
with get_db() as db:
    update_chat_session(db, f"_test_chat_{test_id}", [{"role": "user", "content": "Hello"}])

print("WRITE_OK")
'''

# ─── Reader: verify data exists (fresh process, no shared memory) ──────────────
READER_SCRIPT = '''
import os, sys
sys.path.insert(0, os.environ.get("PYTHONPATH", "."))
from dotenv import load_dotenv
load_dotenv(".env"); load_dotenv(".env.local")

from app.db import init_db, get_db
from app.services.db_repository import (
    get_settings, get_pending_upload, get_all_contact_submissions,
    get_all_feedback, get_chat_session,
)
from app.services.postgres_storage import PostgresStorage

init_db()
test_id = os.environ.get("TEST_ID", "test-unknown")
errors = []

# 1. Settings
with get_db() as db:
    s = get_settings(db)
    if s.get("_test_api_key") != "sk-test-12345":
        errors.append("Settings: API key not found")
    if s.get("_test_prompt") != "Test prompt for persistence":
        errors.append("Settings: Prompt not found")

# 2. Pending upload
with get_db() as db:
    p = get_pending_upload(db, f"_test_upload_{test_id}")
    if not p or p.get("records", [{}])[0].get("title") != "Test":
        errors.append("Pending upload: not found or wrong data")

# 3. Contact
with get_db() as db:
    contacts = get_all_contact_submissions(db)
    if not any(c.get("email") == "test@example.com" for c in contacts):
        errors.append("Contact submission: not found")

# 4. Feedback
with get_db() as db:
    fb = get_all_feedback(db)
    if not any(f.get("email") == "fb@test.com" for f in fb):
        errors.append("Feedback: not found")

# 5. Batch + product field edit persistence
storage = PostgresStorage()
batch = storage.get_batch(f"_test_batch_{test_id}")
if not batch or len(batch.products) != 1:
    errors.append("Batch: not found or wrong product count")
elif batch.products[0].optimized_title != "PersistedTitle":
    errors.append("Batch: product field edit not persisted")

# 6. Chat session
with get_db() as db:
    chat = get_chat_session(db, f"_test_chat_{test_id}")
    msgs = chat.get("messages") or []
    if not chat or not msgs:
        errors.append("Chat session: not found or empty")
    elif msgs[0].get("content") != "Hello":
        errors.append("Chat session: wrong message content")

if errors:
    print("FAIL:", " | ".join(errors))
    sys.exit(1)
print("READ_OK")
'''


def cleanup(test_id: str) -> None:
    """Remove test data."""
    cleanup_script = f'''
import os, sys
sys.path.insert(0, os.environ.get("PYTHONPATH", "."))
from dotenv import load_dotenv
load_dotenv(".env"); load_dotenv(".env.local")
from app.db import init_db, get_db
from app.db_models import Setting, PendingUpload, ContactSubmission, Feedback, Batch, ChatSession
from sqlalchemy import select, delete

init_db()
tid = "{test_id}"
with get_db() as db:
    db.execute(delete(Setting).where(Setting.key.in_(["_test_api_key", "_test_prompt"])))
    db.execute(delete(PendingUpload).where(PendingUpload.upload_id == f"_test_upload_{{tid}}"))
    db.execute(delete(ContactSubmission).where(ContactSubmission.email == "test@example.com"))
    db.execute(delete(Feedback).where(Feedback.email == "fb@test.com"))
    db.execute(delete(ChatSession).where(ChatSession.session_id == f"_test_chat_{{tid}}"))
    row = db.execute(select(Batch).where(Batch.batch_id == f"_test_batch_{{tid}}")).scalar_one_or_none()
    if row:
        db.delete(row)
'''
    run_script(cleanup_script, {"TEST_ID": test_id})


def main():
    test_id = str(uuid.uuid4())[:8]
    os.environ["TEST_ID"] = test_id

    print("Testing DB persistence (write in process 1, read in process 2)...")
    print()

    # Write (test_id passed via TEST_ID env)
    ok_write, out_write = run_script(WRITER_SCRIPT, {"TEST_ID": test_id})
    if not ok_write or "WRITE_OK" not in out_write:
        print("Write failed:", out_write)
        sys.exit(1)
    print("  Write: OK")

    # Read in fresh process (proves data is on disk, not RAM)
    ok_read, out_read = run_script(READER_SCRIPT, {"TEST_ID": test_id})
    if not ok_read or "READ_OK" not in out_read:
        print("Read failed (data not persisted):", out_read)
        cleanup(test_id)
        sys.exit(1)
    print("  Read (fresh process): OK")

    # Cleanup
    cleanup(test_id)
    print()
    print("All persistence tests passed:")
    print("  - Settings (API key, prompts)")
    print("  - Pending uploads")
    print("  - Contact submissions")
    print("  - Feedback")
    print("  - Batches (including product field edits)")
    print("  - Chat sessions")
    print()
    print("Data is stored in database, not RAM.")


if __name__ == "__main__":
    main()
