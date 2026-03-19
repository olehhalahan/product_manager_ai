"""
Database repository for settings, users, feedback, pending uploads.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..db_models import Setting, User, Feedback, PendingUpload


# ─── Settings ────────────────────────────────────────────────────────────────

DEFAULT_PROMPT_TITLE = """You are an SEO expert. Optimize the following product title for search engines.
Keep it under 120 characters. Include relevant keywords. Use a pipe separator for secondary phrases.

Original title: {title}
Category: {category}
Brand: {brand}
Attributes: {attributes}

Return only the optimized title, nothing else."""

DEFAULT_PROMPT_DESCRIPTION = """You are an e-commerce copywriter. Write a compelling product description.
Keep it 2-3 paragraphs. Focus on benefits and features. Do not mention price.

Product: {title}
Category: {category}
Brand: {brand}
Attributes: {attributes}
Original description: {description}

Return only the description, nothing else."""


DEFAULT_SEO_META_TITLE = "Cartozo.ai — AI-Powered Product Feed Optimization"
DEFAULT_SEO_META_DESCRIPTION = "AI-powered optimization for your product titles and descriptions. Boost search rankings, increase clicks, and drive more sales. Ready for Google Merchant Center."


def get_settings(db: Session) -> Dict[str, str]:
    """Get settings as dict. Returns defaults if not in DB."""
    rows = db.execute(select(Setting)).scalars().all() or []
    settings = {r.key: (r.value or "") for r in rows}
    if "prompt_title" not in settings:
        settings["prompt_title"] = DEFAULT_PROMPT_TITLE
    if "prompt_description" not in settings:
        settings["prompt_description"] = DEFAULT_PROMPT_DESCRIPTION
    if "openai_api_key" not in settings:
        settings["openai_api_key"] = ""
    # SEO defaults
    if "seo_meta_title" not in settings:
        settings["seo_meta_title"] = DEFAULT_SEO_META_TITLE
    if "seo_meta_description" not in settings:
        settings["seo_meta_description"] = DEFAULT_SEO_META_DESCRIPTION
    if "seo_og_title" not in settings:
        settings["seo_og_title"] = DEFAULT_SEO_META_TITLE
    if "seo_og_description" not in settings:
        settings["seo_og_description"] = DEFAULT_SEO_META_DESCRIPTION
    if "seo_og_image" not in settings:
        settings["seo_og_image"] = ""
    if "seo_og_site_name" not in settings:
        settings["seo_og_site_name"] = "Cartozo.ai"
    return settings


def set_setting(db: Session, key: str, value: str) -> None:
    """Set a single setting."""
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(Setting(key=key, value=value))


def set_settings(db: Session, data: Dict[str, str]) -> None:
    """Set multiple settings."""
    for k, v in data.items():
        set_setting(db, k, v)


# ─── Users ───────────────────────────────────────────────────────────────────

def get_user_by_email(db: Session, email: str) -> Optional[Dict]:
    """Get user by email."""
    row = db.execute(select(User).where(User.email == email)).scalars().one_or_none()
    if not row:
        return None
    return {
        "email": row.email,
        "name": row.name or "",
        "provider": row.provider or "",
        "role": row.role or "customer",
        "first_seen": row.first_seen.isoformat() if row.first_seen else "",
        "last_login": row.last_login.isoformat() if row.last_login else "",
    }


def upsert_user(db: Session, user: dict) -> None:
    """Create or update user on login."""
    email = user.get("email", "")
    now = datetime.now(timezone.utc)
    row = db.execute(select(User).where(User.email == email)).scalars().one_or_none()
    if row:
        row.name = user.get("name", row.name)
        row.last_login = now
    else:
        db.add(User(
            email=email,
            name=user.get("name", ""),
            provider=user.get("provider", ""),
            role=user.get("role", "customer"),
            first_seen=now,
            last_login=now,
        ))


def get_all_users(db: Session) -> List[Dict]:
    """Get all users."""
    rows = db.execute(select(User).order_by(User.last_login.desc())).scalars().all()
    return [
        {
            "email": r.email,
            "name": r.name or "",
            "provider": r.provider or "",
            "role": r.role or "customer",
            "first_seen": r.first_seen.isoformat() if r.first_seen else "",
            "last_login": r.last_login.isoformat() if r.last_login else "",
        }
        for r in rows
    ]


# ─── Feedback ────────────────────────────────────────────────────────────────

def add_feedback(db: Session, rating: int, text: str, batch_id: str, email: str, name: str, timestamp=None) -> None:
    """Add feedback entry. timestamp can be datetime or ISO string."""
    ts = timestamp
    if ts is None:
        ts = datetime.now(timezone.utc)
    elif isinstance(ts, str) and ts:
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc)
    db.add(Feedback(
        rating=rating,
        text=text,
        batch_id=batch_id[:20] if batch_id else "",
        email=email,
        name=name,
        timestamp=ts,
    ))


def get_all_feedback(db: Session) -> List[Dict]:
    """Get all feedback entries (newest first)."""
    rows = db.execute(select(Feedback).order_by(Feedback.id.desc())).scalars().all()
    return [
        {
            "rating": r.rating,
            "text": r.text or "",
            "batch_id": r.batch_id or "",
            "email": r.email or "",
            "name": r.name or "",
            "timestamp": r.timestamp.isoformat() if r.timestamp else "",
        }
        for r in rows
    ]


# ─── Pending uploads ─────────────────────────────────────────────────────────

def save_pending_upload(db: Session, upload_id: str, records: List[Dict], mode: str, target_language: str, product_type: str) -> None:
    """Save pending upload."""
    db.add(PendingUpload(
        upload_id=upload_id,
        records=records,
        mode=mode,
        target_language=target_language or "",
        product_type=product_type or "standard",
    ))


def get_pending_upload(db: Session, upload_id: str) -> Optional[Dict]:
    """Get pending upload by id."""
    row = db.execute(select(PendingUpload).where(PendingUpload.upload_id == upload_id)).scalars().one_or_none()
    if not row:
        return None
    return {
        "records": row.records,
        "mode": row.mode or "optimize",
        "target_language": row.target_language or "",
        "product_type": row.product_type or "standard",
    }


def delete_pending_upload(db: Session, upload_id: str) -> Optional[Dict]:
    """Get and delete pending upload."""
    row = db.execute(select(PendingUpload).where(PendingUpload.upload_id == upload_id)).scalars().one_or_none()
    if not row:
        return None
    data = {"records": row.records, "mode": row.mode or "optimize", "target_language": row.target_language or "", "product_type": row.product_type or "standard"}
    db.delete(row)
    return data


# ─── Batches ──────────────────────────────────────────────────────────────────

def create_batch(db: Session, batch_id: str, products_json: list, status: str, product_type: str) -> None:
    """Create a new batch."""
    from ..db_models import Batch as BatchModel
    db.add(BatchModel(
        batch_id=batch_id,
        status=status,
        products_json=products_json,
        product_type=product_type or "standard",
    ))


def get_batch(db: Session, batch_id: str) -> Optional[dict]:
    """Get batch by id. Returns dict with products_json."""
    from ..db_models import Batch as BatchModel
    row = db.execute(select(BatchModel).where(BatchModel.batch_id == batch_id)).scalars().one_or_none()
    if not row:
        return None
    return {
        "batch_id": row.batch_id,
        "status": row.status,
        "products_json": row.products_json,
        "product_type": row.product_type or "standard",
        "total_cost_usd": row.total_cost_usd or 0.0,
        "client_id": row.client_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def update_batch(db: Session, batch_id: str, status: str, products_json: list, completed_at=None) -> None:
    """Update batch status and products."""
    from ..db_models import Batch as BatchModel
    from datetime import datetime, timezone
    row = db.execute(select(BatchModel).where(BatchModel.batch_id == batch_id)).scalars().one_or_none()
    if not row:
        return
    row.status = status
    row.products_json = products_json
    if completed_at is not None:
        row.completed_at = datetime.now(timezone.utc) if completed_at else None
