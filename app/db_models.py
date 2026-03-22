"""
SQLAlchemy ORM models. Compatible with SQLite and PostgreSQL.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from .db import Base


class Setting(Base):
    """App settings (prompts, API key). Single-row or key-value."""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(64), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class User(Base):
    """User accounts (from OAuth)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    provider = Column(String(64), nullable=True)
    role = Column(String(32), default="customer")
    first_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # Google Merchant Center (Merchant API) — OAuth refresh token for server-side uploads
    merchant_refresh_token = Column(Text, nullable=True)
    merchant_id = Column(String(64), nullable=True)
    merchant_connected_at = Column(DateTime, nullable=True)


class Feedback(Base):
    """Customer feedback entries."""
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rating = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    batch_id = Column(String(64), nullable=True)
    email = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PendingUpload(Base):
    """Temporary upload data before column mapping confirmation."""
    __tablename__ = "pending_uploads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_id = Column(String(64), unique=True, nullable=False, index=True)
    records = Column(JSON, nullable=False)  # list of dicts
    mode = Column(String(32), nullable=True)
    target_language = Column(String(16), nullable=True)
    product_type = Column(String(32), default="standard")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Batch(Base):
    """Processing batches."""
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False)
    product_type = Column(String(32), default="standard")
    products_json = Column(JSON, nullable=False)  # list of ProductResult dicts
    total_cost_usd = Column(Float, default=0.0)
    client_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    # Owner + Merchant Center push / archive (per-user batch history on review page)
    user_email = Column(String(255), nullable=True, index=True)
    merchant_pushed_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)


class ChatSession(Base):
    """Chat sessions for AI agent on homepage."""
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    messages = Column(JSON, nullable=False)  # list of {role, content} dicts
    user_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ContactSubmission(Base):
    """Contact form submissions."""
    __tablename__ = "contact_submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    surname = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class OnboardingSession(Base):
    """User onboarding wizard progress (steps 1–7)."""
    __tablename__ = "onboarding_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=True)
    designation = Column(String(128), nullable=True)
    source = Column(String(128), nullable=True)
    max_step = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="in_progress")  # in_progress, completed, abandoned
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
