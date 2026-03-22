"""
Database repository for settings, users, feedback, pending uploads.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, and_, delete, update

from ..db_models import Setting, User, Feedback, PendingUpload, ChatSession, ContactSubmission, OnboardingSession


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


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    if not email:
        return None
    return db.execute(select(User).where(User.email == email)).scalars().one_or_none()


def get_merchant_connection_status(db: Session, email: str) -> Dict[str, Any]:
    row = get_user_by_email(db, email)
    if not row:
        return {"connected": False, "merchant_id": None}
    return {
        "connected": bool(row.merchant_refresh_token),
        "merchant_id": row.merchant_id or None,
    }


def save_google_merchant_oauth(
    db: Session,
    email: str,
    refresh_token: Optional[str],
    merchant_id: Optional[str],
) -> None:
    """Persist Merchant API refresh token and optional merchant account id."""
    row = get_user_by_email(db, email)
    if not row:
        return
    now = datetime.now(timezone.utc)
    if refresh_token:
        row.merchant_refresh_token = refresh_token
    if merchant_id:
        row.merchant_id = merchant_id
    row.merchant_connected_at = now


def clear_google_merchant_oauth(db: Session, email: str) -> None:
    row = get_user_by_email(db, email)
    if not row:
        return
    row.merchant_refresh_token = None
    row.merchant_id = None
    row.merchant_connected_at = None


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


# ─── Contact submissions ────────────────────────────────────────────────────

def save_contact_submission(db: Session, name: str, surname: str, email: str, phone: str = "") -> None:
    """Save contact form submission."""
    db.add(ContactSubmission(
        name=name.strip(),
        surname=surname.strip(),
        email=email.strip(),
        phone=(phone or "").strip(),
    ))


def get_all_contact_submissions(db: Session) -> List[Dict]:
    """Get all contact submissions (newest first)."""
    rows = db.execute(select(ContactSubmission).order_by(ContactSubmission.id.desc())).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name or "",
            "surname": r.surname or "",
            "email": r.email or "",
            "phone": r.phone or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
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

def create_batch(
    db: Session,
    batch_id: str,
    products_json: list,
    status: str,
    product_type: str,
    user_email: Optional[str] = None,
) -> None:
    """Create a new batch."""
    from ..db_models import Batch as BatchModel

    owner = (user_email or "").strip().lower() or None
    db.add(
        BatchModel(
            batch_id=batch_id,
            status=status,
            products_json=products_json,
            product_type=product_type or "standard",
            user_email=owner,
        )
    )


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
        "user_email": getattr(row, "user_email", None) or "",
        "merchant_pushed_at": row.merchant_pushed_at.isoformat()
        if getattr(row, "merchant_pushed_at", None)
        else None,
        "closed_at": row.closed_at.isoformat() if getattr(row, "closed_at", None) else None,
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


def list_batches_for_user(db: Session, user_email: str, limit: int = 200) -> List[dict]:
    """Batches owned by this user, newest first."""
    from ..db_models import Batch as BatchModel

    email = (user_email or "").strip().lower()
    if not email:
        return []
    rows = (
        db.execute(
            select(BatchModel)
            .where(BatchModel.user_email == email)
            .order_by(BatchModel.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    out: List[dict] = []
    for r in rows:
        pj = r.products_json or []
        n = len(pj) if isinstance(pj, list) else 0
        out.append(
            {
                "batch_id": r.batch_id,
                "status": r.status,
                "product_type": r.product_type or "standard",
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "merchant_pushed_at": r.merchant_pushed_at.isoformat()
                if getattr(r, "merchant_pushed_at", None)
                else None,
                "closed_at": r.closed_at.isoformat() if getattr(r, "closed_at", None) else None,
                "product_count": n,
            }
        )
    return out


def mark_batch_merchant_pushed(db: Session, batch_id: str) -> None:
    from ..db_models import Batch as BatchModel

    row = db.execute(select(BatchModel).where(BatchModel.batch_id == batch_id)).scalars().one_or_none()
    if row:
        row.merchant_pushed_at = datetime.now(timezone.utc)


def mark_batch_closed(db: Session, batch_id: str) -> None:
    from ..db_models import Batch as BatchModel

    row = db.execute(select(BatchModel).where(BatchModel.batch_id == batch_id)).scalars().one_or_none()
    if row:
        row.closed_at = datetime.now(timezone.utc)


# ─── Chat sessions ───────────────────────────────────────────────────────────

def create_chat_session(db: Session, session_id: str, user_email: str = None) -> None:
    """Create a new chat session."""
    db.add(ChatSession(session_id=session_id, messages=[], user_email=user_email))


def get_chat_session(db: Session, session_id: str) -> Optional[Dict]:
    """Get chat session by id."""
    row = db.execute(select(ChatSession).where(ChatSession.session_id == session_id)).scalars().one_or_none()
    if not row:
        return None
    return {
        "session_id": row.session_id,
        "messages": row.messages or [],
        "user_email": row.user_email or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def update_chat_session(db: Session, session_id: str, messages: list) -> None:
    """Update chat session messages."""
    row = db.execute(select(ChatSession).where(ChatSession.session_id == session_id)).scalars().one_or_none()
    if not row:
        return
    row.messages = messages
    row.updated_at = datetime.now(timezone.utc)


def get_all_chat_sessions(db: Session) -> List[Dict]:
    """Get all chat sessions (newest first) for admin."""
    rows = db.execute(select(ChatSession).order_by(ChatSession.updated_at.desc())).scalars().all()
    return [
        {
            "session_id": r.session_id,
            "messages": r.messages or [],
            "user_email": r.user_email or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in rows
    ]


# ─── Onboarding sessions ─────────────────────────────────────────────────────

def create_onboarding_session(
    db: Session,
    email: Optional[str] = None,
    name: Optional[str] = None,
    source: Optional[str] = None,
) -> str:
    """Create a new onboarding session; returns public_id."""
    public_id = uuid.uuid4().hex
    src = (source or "").strip() or None
    if src:
        src = src[:128]
    db.add(
        OnboardingSession(
            public_id=public_id,
            email=(email or "").strip() or None,
            name=(name or "").strip() or None,
            source=src,
            max_step=1,
            status="in_progress",
        )
    )
    db.flush()
    return public_id


def delete_all_onboarding_sessions(db: Session) -> None:
    """Remove all onboarding rows (admin maintenance)."""
    db.execute(delete(OnboardingSession))


def clear_onboarding_designation_values(db: Session) -> None:
    """Set designation to NULL for all rows (legacy cleanup; column kept for DB compatibility)."""
    db.execute(update(OnboardingSession).values(designation=None))


def get_onboarding_by_public_id(db: Session, public_id: str) -> Optional[OnboardingSession]:
    return (
        db.execute(select(OnboardingSession).where(OnboardingSession.public_id == public_id))
        .scalars()
        .one_or_none()
    )


def update_onboarding_progress(
    db: Session,
    public_id: str,
    step: int,
    source: Optional[str] = None,
) -> bool:
    """Advance onboarding step (1–7). Returns False if session missing."""
    row = get_onboarding_by_public_id(db, public_id)
    if not row:
        return False
    step = max(1, min(7, int(step)))
    row.max_step = max(row.max_step, step)
    if source is not None:
        s = source.strip()
        row.source = s if s else None
    row.updated_at = datetime.now(timezone.utc)
    return True


def complete_onboarding(db: Session, public_id: str) -> bool:
    """Mark session completed and record duration (signup → complete). Idempotent."""
    row = get_onboarding_by_public_id(db, public_id)
    if not row:
        return False
    if row.status == "completed":
        return True
    now = datetime.now(timezone.utc)
    row.status = "completed"
    row.max_step = max(row.max_step, 7)
    row.completed_at = now
    row.updated_at = now
    started = row.started_at
    if started:
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        dur = max(0, int((now - started).total_seconds()))
        row.duration_seconds = max(1, dur) if dur == 0 else dur
    else:
        row.duration_seconds = 1
    return True


def _onboarding_base_query(
    q: Optional[str],
    source: Optional[str],
    status: Optional[str],
):
    stmt = select(OnboardingSession)
    cond = []
    if q:
        qq = f"%{q.strip()}%"
        cond.append(
            or_(
                OnboardingSession.email.ilike(qq),
                OnboardingSession.name.ilike(qq),
            )
        )
    if source and source != "all":
        cond.append(OnboardingSession.source == source)
    if status and status != "all":
        cond.append(OnboardingSession.status == status)
    if cond:
        stmt = stmt.where(and_(*cond))
    return stmt


def get_onboarding_analytics_summary(db: Session) -> Dict[str, Any]:
    """Aggregates for admin dashboard: funnel, charts, totals, total time sum."""
    total_started = db.execute(select(func.count()).select_from(OnboardingSession)).scalar() or 0
    completed = (
        db.execute(
            select(func.count()).select_from(OnboardingSession).where(OnboardingSession.status == "completed")
        ).scalar()
        or 0
    )
    total_time_sec = (
        db.execute(
            select(func.coalesce(func.sum(OnboardingSession.duration_seconds), 0)).where(
                OnboardingSession.duration_seconds.isnot(None)
            )
        ).scalar()
        or 0
    )

    funnel = []
    for step in range(1, 8):
        c = (
            db.execute(
                select(func.count()).select_from(OnboardingSession).where(OnboardingSession.max_step >= step)
            ).scalar()
            or 0
        )
        funnel.append(c)

    biggest_drop_label = "—"
    if len(funnel) >= 2:
        drops = [funnel[i] - funnel[i + 1] for i in range(len(funnel) - 1)]
        if drops and max(drops) > 0:
            idx = drops.index(max(drops))
            biggest_drop_label = f"Step {idx + 1}"

    completion_rate = round(100.0 * completed / total_started, 1) if total_started else 0.0

    def _group_counts(column_attr):
        rows = (
            db.execute(
                select(column_attr, func.count())
                .select_from(OnboardingSession)
                .where(and_(column_attr.isnot(None), column_attr != ""))
                .group_by(column_attr)
                .order_by(func.count().desc())
            )
            .all()
        )
        return [{"label": r[0] or "—", "count": r[1]} for r in rows]

    by_source = _group_counts(OnboardingSession.source)

    return {
        "started": total_started,
        "completed": completed,
        "completion_rate": completion_rate,
        "biggest_drop_step": biggest_drop_label,
        "total_time_seconds": int(total_time_sec),
        "funnel": funnel,
        "by_source": by_source,
    }


def list_onboarding_sessions(
    db: Session,
    q: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    stmt = _onboarding_base_query(q, source, status).order_by(OnboardingSession.started_at.desc())
    stmt = stmt.limit(min(max(1, limit), 2000))
    rows = db.execute(stmt).scalars().all()
    out = []
    for r in rows:
        dur = r.duration_seconds
        dur_label = "—"
        if dur is not None:
            if dur == 0:
                dur_label = "<1m"
            elif dur >= 86400:
                dur_label = f"{dur // 86400}d {dur % 86400 // 3600}h"
            elif dur >= 3600:
                dur_label = f"{dur // 3600}h {dur % 3600 // 60}m"
            else:
                dur_label = f"{max(1, dur // 60)}m"
        started = r.started_at
        date_label = ""
        if started:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            date_label = started.strftime("%d/%m/%Y")
        out.append(
            {
                "public_id": r.public_id,
                "name": r.name or "",
                "email": r.email or "",
                "source": r.source or "",
                "steps": f"{min(r.max_step, 7)}/7",
                "max_step": r.max_step,
                "status": r.status,
                "duration_label": dur_label,
                "duration_seconds": r.duration_seconds,
                "date": date_label,
            }
        )
    return out


def get_onboarding_source_filter_options(db: Session) -> List[str]:
    """Distinct source values (How they found us) for filter dropdown."""
    return [
        r[0]
        for r in db.execute(
            select(OnboardingSession.source)
            .where(OnboardingSession.source.isnot(None))
            .where(OnboardingSession.source != "")
            .distinct()
            .order_by(OnboardingSession.source)
        ).all()
        if r[0]
    ]
