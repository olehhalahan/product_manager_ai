"""
Database connection and session management.
Supports SQLite (default) and PostgreSQL via DATABASE_URL.
"""
import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_DEFAULT_DB_PATH = os.path.join(_DATA_DIR, "app.db").replace("\\", "/")
os.makedirs(_DATA_DIR, exist_ok=True)

_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{_DEFAULT_DB_PATH}",
)


def get_engine():
    """Create SQLAlchemy engine. SQLite by default, PostgreSQL if DATABASE_URL starts with postgresql://."""
    url = os.getenv("DATABASE_URL", _DATABASE_URL)
    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=False,
        )
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db():
    """Context manager for database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Create all tables if they don't exist. Migrate batches table if schema is outdated."""
    url = os.getenv("DATABASE_URL", _DATABASE_URL)
    if url.startswith("sqlite") and ":///" in url:
        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
    from . import db_models  # noqa: F401 - register models
    from sqlalchemy import inspect

    # Migration: batches table may have old schema (missing batch_id)
    inspector = inspect(engine)
    if "batches" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("batches")]
        if "batch_id" not in cols:
            from .db_models import Batch
            Batch.__table__.drop(engine)
            Batch.__table__.create(engine)

    # Migration: users.merchant_* columns (Google Merchant Center OAuth)
    if "users" in inspector.get_table_names():
        from sqlalchemy import text

        ucols = {c["name"] for c in inspector.get_columns("users")}
        dialect = engine.dialect.name
        with engine.begin() as conn:
            if "merchant_refresh_token" not in ucols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE users ADD COLUMN merchant_refresh_token TEXT"))
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN merchant_refresh_token TEXT"))
            if "merchant_id" not in ucols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE users ADD COLUMN merchant_id VARCHAR(64)"))
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN merchant_id VARCHAR(64)"))
            if "merchant_connected_at" not in ucols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE users ADD COLUMN merchant_connected_at TIMESTAMP"))
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN merchant_connected_at TIMESTAMP"))

    # Migration: batches — user ownership + Merchant push / closed timestamps
    if "batches" in inspector.get_table_names():
        from sqlalchemy import text

        bcols = {c["name"] for c in inspector.get_columns("batches")}
        dialect = engine.dialect.name
        with engine.begin() as conn:
            if "user_email" not in bcols:
                conn.execute(text("ALTER TABLE batches ADD COLUMN user_email VARCHAR(255)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_batches_user_email ON batches (user_email)"))
            if "merchant_pushed_at" not in bcols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE batches ADD COLUMN merchant_pushed_at TIMESTAMP"))
                else:
                    conn.execute(text("ALTER TABLE batches ADD COLUMN merchant_pushed_at TIMESTAMP WITH TIME ZONE"))
            if "closed_at" not in bcols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE batches ADD COLUMN closed_at TIMESTAMP"))
                else:
                    conn.execute(text("ALTER TABLE batches ADD COLUMN closed_at TIMESTAMP WITH TIME ZONE"))

    # Migration: blog_articles.planning_json (Writter opportunity + evidence inputs)
    if "blog_articles" in inspector.get_table_names():
        from sqlalchemy import text

        bcols = {c["name"] for c in inspector.get_columns("blog_articles")}
        dialect = engine.dialect.name
        with engine.begin() as conn:
            if "planning_json" not in bcols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE blog_articles ADD COLUMN planning_json TEXT"))
                else:
                    conn.execute(text("ALTER TABLE blog_articles ADD COLUMN planning_json JSONB"))

    # Migration: content clusters + article versions + cluster columns on blog_articles
    if "blog_articles" in inspector.get_table_names():
        from sqlalchemy import text

        bcols = {c["name"] for c in inspector.get_columns("blog_articles")}
        dialect = engine.dialect.name
        with engine.begin() as conn:
            if "cluster_id" not in bcols:
                conn.execute(text("ALTER TABLE blog_articles ADD COLUMN cluster_id INTEGER"))
            if "cluster_role" not in bcols:
                conn.execute(text("ALTER TABLE blog_articles ADD COLUMN cluster_role VARCHAR(32)"))
            if "writter_refresh_status" not in bcols:
                conn.execute(text("ALTER TABLE blog_articles ADD COLUMN writter_refresh_status VARCHAR(64)"))

    inspector = inspect(engine)
    if "content_clusters" not in inspector.get_table_names():
        from .db_models import ContentCluster

        ContentCluster.__table__.create(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    if "blog_article_versions" not in inspector.get_table_names():
        from .db_models import BlogArticleVersion

        BlogArticleVersion.__table__.create(bind=engine, checkfirst=True)

    Base.metadata.create_all(bind=engine)
