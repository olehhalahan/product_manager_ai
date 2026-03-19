#!/usr/bin/env python3
"""
Initialize PostgreSQL database - create tables.
Run: python -m scripts.init_db
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.db import init_db

if __name__ == "__main__":
    print("Creating database tables...")
    init_db()
    print("Done.")
