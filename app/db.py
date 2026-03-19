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
_DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "app.db").replace("\\", "/")

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
    """Create all tables if they don't exist."""
    url = os.getenv("DATABASE_URL", _DATABASE_URL)
    if url.startswith("sqlite") and ":///" in url:
        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
    from . import db_models  # noqa: F401 - register models
    Base.metadata.create_all(bind=engine)
