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


class ContentCluster(Base):
    """Topical cluster (pillar + supporting articles) for Writter SEO strategy."""
    __tablename__ = "content_clusters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BlogArticle(Base):
    """SEO blog articles (Writter admin + public /blog/{slug})."""
    __tablename__ = "blog_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    article_type = Column(String(64), nullable=False)
    topic = Column(Text, nullable=True)
    keywords = Column(Text, nullable=True)
    rules_json = Column(JSON, nullable=True)
    content_html = Column(Text, nullable=False, default="")
    meta_description = Column(Text, nullable=True)
    structure_json = Column(JSON, nullable=True)
    visual_html = Column(Text, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    planning_json = Column(JSON, nullable=True)
    internal_links_json = Column(JSON, nullable=True)
    status = Column(String(32), default="draft")
    published_at = Column(DateTime, nullable=True)
    views = Column(Integer, default=0)
    cta_clicks = Column(Integer, default=0)
    analytics_sessions = Column(Integer, default=0)
    total_time_ms = Column(Integer, default=0)
    total_scroll_pct = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    author_email = Column(String(255), nullable=True)
    cluster_id = Column(Integer, ForeignKey("content_clusters.id"), nullable=True)
    cluster_role = Column(String(32), nullable=True)
    writter_refresh_status = Column(String(64), nullable=True)
    auto_generation_batch_id = Column(String(64), nullable=True, index=True)


class WritterFutureArticle(Base):
    """Admin queue: AI-suggested article briefs pending approval before generation."""

    __tablename__ = "writter_future_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic = Column(String(500), nullable=False)
    keywords = Column(Text, nullable=True)
    article_type = Column(String(64), nullable=False, default="informational")
    primary_goal = Column(String(64), nullable=False, default="organic_traffic")
    briefing_json = Column(JSON, nullable=True)
    status = Column(String(32), nullable=False, default="pending")  # pending, approved, rejected, done
    generated_article_id = Column(Integer, ForeignKey("blog_articles.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class WritterAutoRun(Base):
    """Log + idempotency metadata for daily automatic SEO article runs (cron / manual)."""

    __tablename__ = "writter_auto_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    trigger = Column(String(32), nullable=False, default="cron")
    timezone = Column(String(64), nullable=False, default="UTC")
    local_date = Column(String(10), nullable=False, index=True)
    target_count = Column(Integer, nullable=False, default=5)
    success_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    status = Column(String(24), nullable=False, default="running")
    log_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)


class BlogArticleVersion(Base):
    """Snapshot of article HTML/title/meta for version history."""
    __tablename__ = "blog_article_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("blog_articles.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    content_html = Column(Text, nullable=False, default="")
    meta_description = Column(Text, nullable=True)
    author_email = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    change_summary = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
