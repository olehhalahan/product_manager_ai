"""
PostgreSQL database connection and session management.
"""
import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/product_manager",
)


def get_engine():
    """Create SQLAlchemy engine for PostgreSQL."""
    url = os.getenv("DATABASE_URL", _DATABASE_URL)
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
    from . import db_models  # noqa: F401 - register models
    Base.metadata.create_all(bind=engine)
