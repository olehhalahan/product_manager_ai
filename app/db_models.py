"""
SQLAlchemy ORM models for PostgreSQL.
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
