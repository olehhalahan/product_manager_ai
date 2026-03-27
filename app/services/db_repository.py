"""
Database repository for settings, users, feedback, pending uploads.
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Dict, List
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, and_, delete, update

_UNSET = object()

from ..db_models import (
    Setting,
    User,
    Feedback,
    PendingUpload,
    ChatSession,
    ContactSubmission,
    OnboardingSession,
    BlogArticle,
    BlogArticleVersion,
    ContentCluster,
)


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
    # Blog / Writter: optional extra instructions per article type (empty = use defaults only)
    for _wk in (
        "writter_prompt_problem_solving",
        "writter_prompt_feature_presentation",
        "writter_prompt_informational",
        "writter_prompt_use_cases",
        "writter_prompt_comparison",
        "writter_prompt_checklist_template",
    ):
        if _wk not in settings:
            settings[_wk] = ""
    # Homepage hero chat: optional system prompt (empty = built-in default in AIProvider)
    if "homepage_chat_system_prompt" not in settings:
        settings["homepage_chat_system_prompt"] = ""
    # Writter workspace defaults (optional — used when admin leaves fields blank)
    if "writter_default_country_language" not in settings:
        settings["writter_default_country_language"] = "US / English"
    if "writter_default_audience" not in settings:
        settings["writter_default_audience"] = "SMB e-commerce merchants and catalog managers"
    if "writter_default_cta" not in settings:
        settings["writter_default_cta"] = "Try Cartozo on your product feed"
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
    from .google_merchant import canonical_merchant_id

    row = get_user_by_email(db, email)
    if not row:
        return {"connected": False, "merchant_id": None}
    mid = row.merchant_id or None
    if mid:
        mid = canonical_merchant_id(mid) or mid
    return {
        "connected": bool(row.merchant_refresh_token),
        "merchant_id": mid,
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
        from .google_merchant import canonical_merchant_id

        row.merchant_id = canonical_merchant_id(merchant_id) or merchant_id
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


# ─── Blog articles (Writter) ───────────────────────────────────────────────────


def blog_article_to_dict(row: BlogArticle) -> Dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "title": row.title,
        "article_type": row.article_type,
        "topic": row.topic or "",
        "keywords": row.keywords or "",
        "rules_json": row.rules_json,
        "content_html": row.content_html or "",
        "meta_description": row.meta_description or "",
        "structure_json": row.structure_json,
        "visual_html": row.visual_html,
        "metrics_json": row.metrics_json,
        "planning_json": row.planning_json,
        "internal_links_json": row.internal_links_json,
        "status": row.status or "draft",
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "views": row.views or 0,
        "cta_clicks": row.cta_clicks or 0,
        "analytics_sessions": row.analytics_sessions or 0,
        "total_time_ms": row.total_time_ms or 0,
        "total_scroll_pct": float(row.total_scroll_pct or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "author_email": row.author_email or "",
        "cluster_id": row.cluster_id,
        "cluster_role": row.cluster_role or "",
        "writter_refresh_status": row.writter_refresh_status or "",
    }


def list_blog_articles_admin(db: Session, limit: int = 500) -> List[Dict[str, Any]]:
    rows = (
        db.execute(select(BlogArticle).order_by(BlogArticle.created_at.desc()).limit(min(max(1, limit), 2000)))
        .scalars()
        .all()
    )
    return [blog_article_to_dict(r) for r in rows]


def list_blog_articles_published(db: Session, limit: int = 200) -> List[Dict[str, Any]]:
    rows = (
        db.execute(
            select(BlogArticle)
            .where(BlogArticle.status == "published")
            .order_by(BlogArticle.created_at.desc())
            .limit(min(max(1, limit), 500))
        )
        .scalars()
        .all()
    )
    return [blog_article_to_dict(r) for r in rows]


def list_blog_articles_published_search(db: Session, *, search: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    """
    Published articles only. Optional search: whitespace-separated terms; each term must match
    title, topic, keywords, or meta description (case-insensitive).
    """
    lim = min(max(1, limit), 500)
    stmt = select(BlogArticle).where(BlogArticle.status == "published")
    raw = (search or "").strip()
    if raw:
        terms = [t.strip() for t in raw.split() if t.strip()][:24]
        for term in terms:
            safe = term.replace("%", "").replace("_", "").replace("\\", "")
            if not safe:
                continue
            pat = f"%{safe}%"
            stmt = stmt.where(
                or_(
                    BlogArticle.title.ilike(pat),
                    BlogArticle.topic.ilike(pat),
                    BlogArticle.keywords.ilike(pat),
                    BlogArticle.meta_description.ilike(pat),
                )
            )
    stmt = stmt.order_by(BlogArticle.created_at.desc()).limit(lim)
    rows = db.execute(stmt).scalars().all()
    return [blog_article_to_dict(r) for r in rows]


def get_blog_article_by_slug(db: Session, slug: str) -> Optional[BlogArticle]:
    return db.execute(select(BlogArticle).where(BlogArticle.slug == slug)).scalars().one_or_none()


def get_blog_article_by_id(db: Session, article_id: int) -> Optional[BlogArticle]:
    return db.execute(select(BlogArticle).where(BlogArticle.id == article_id)).scalars().one_or_none()


def get_published_slugs_titles_excluding(
    db: Session, exclude_slug: Optional[str] = None, limit: int = 50
) -> List[Dict[str, str]]:
    """For internal linking prompts."""
    q = select(BlogArticle.slug, BlogArticle.title).where(BlogArticle.status == "published")
    if exclude_slug:
        q = q.where(BlogArticle.slug != exclude_slug)
    rows = db.execute(q.order_by(BlogArticle.published_at.desc()).limit(limit)).all()
    return [{"slug": r[0], "title": r[1]} for r in rows]


def count_blog_articles_same_topic(db: Session, topic: str) -> int:
    """Scaled-content guard: count articles with identical topic (case-insensitive trim)."""
    t = (topic or "").strip().lower()
    if not t:
        return 0
    n = db.execute(
        select(func.count()).select_from(BlogArticle).where(func.lower(BlogArticle.topic) == t)
    ).scalar_one_or_none()
    return int(n or 0)


def create_blog_article(
    db: Session,
    *,
    slug: str,
    title: str,
    article_type: str,
    topic: str,
    keywords: str,
    rules_json: Optional[List[Dict[str, Any]]],
    content_html: str,
    meta_description: str,
    structure_json: Optional[Any],
    visual_html: Optional[str],
    metrics_json: Optional[Dict[str, Any]],
    planning_json: Optional[Dict[str, Any]],
    internal_links_json: Optional[List[Dict[str, str]]],
    status: str,
    author_email: str,
    published_at: Optional[datetime],
    cluster_id: Optional[int] = None,
    cluster_role: Optional[str] = None,
    writter_refresh_status: Optional[str] = None,
) -> BlogArticle:
    row = BlogArticle(
        slug=slug,
        title=title,
        article_type=article_type,
        topic=topic,
        keywords=keywords,
        rules_json=rules_json,
        content_html=content_html,
        meta_description=meta_description,
        structure_json=structure_json,
        visual_html=visual_html,
        metrics_json=metrics_json,
        planning_json=planning_json,
        internal_links_json=internal_links_json,
        status=status,
        published_at=published_at,
        author_email=author_email or None,
        cluster_id=cluster_id,
        cluster_role=cluster_role,
        writter_refresh_status=writter_refresh_status,
    )
    db.add(row)
    db.flush()
    return row


def update_blog_article(
    db: Session,
    row: BlogArticle,
    *,
    title: Optional[str] = None,
    content_html: Optional[str] = None,
    meta_description: Optional[str] = None,
    structure_json: Optional[Any] = None,
    visual_html: Optional[str] = None,
    metrics_json: Optional[Dict[str, Any]] = None,
    planning_json: Optional[Dict[str, Any]] = None,
    internal_links_json: Optional[List[Dict[str, str]]] = None,
    status: Optional[str] = None,
    published_at: Optional[datetime] = None,
    cluster_id: Any = _UNSET,
    cluster_role: Any = _UNSET,
    writter_refresh_status: Any = _UNSET,
) -> None:
    now = datetime.now(timezone.utc)
    if title is not None:
        row.title = title
    if content_html is not None:
        row.content_html = content_html
    if meta_description is not None:
        row.meta_description = meta_description
    if structure_json is not None:
        row.structure_json = structure_json
    if visual_html is not None:
        row.visual_html = visual_html
    if metrics_json is not None:
        row.metrics_json = metrics_json
    if planning_json is not None:
        row.planning_json = planning_json
    if internal_links_json is not None:
        row.internal_links_json = internal_links_json
    if cluster_id is not _UNSET:
        row.cluster_id = cluster_id
    if cluster_role is not _UNSET:
        row.cluster_role = cluster_role
    if writter_refresh_status is not _UNSET:
        row.writter_refresh_status = writter_refresh_status
    if status is not None:
        row.status = status
        if status == "draft":
            row.published_at = None
        elif status == "published" and row.published_at is None:
            row.published_at = now
    if published_at is not None:
        row.published_at = published_at
    row.updated_at = now


def increment_blog_views(db: Session, slug: str) -> None:
    row = get_blog_article_by_slug(db, slug)
    if not row or row.status != "published":
        return
    row.views = (row.views or 0) + 1
    row.updated_at = datetime.now(timezone.utc)


def record_blog_analytics(
    db: Session,
    slug: str,
    *,
    time_ms: Optional[int] = None,
    scroll_pct: Optional[float] = None,
    cta_click: bool = False,
) -> None:
    row = get_blog_article_by_slug(db, slug)
    if not row or row.status != "published":
        return
    now = datetime.now(timezone.utc)
    row.analytics_sessions = (row.analytics_sessions or 0) + 1
    if time_ms is not None and time_ms > 0:
        row.total_time_ms = (row.total_time_ms or 0) + int(min(time_ms, 3_600_000))
    if scroll_pct is not None and scroll_pct >= 0:
        row.total_scroll_pct = float(row.total_scroll_pct or 0) + min(float(scroll_pct), 100.0)
    if cta_click:
        row.cta_clicks = (row.cta_clicks or 0) + 1
    row.updated_at = now


def slug_exists(db: Session, slug: str, exclude_id: Optional[int] = None) -> bool:
    q = select(BlogArticle.id).where(BlogArticle.slug == slug)
    if exclude_id is not None:
        q = q.where(BlogArticle.id != exclude_id)
    return db.execute(q).scalar_one_or_none() is not None


def delete_blog_article(db: Session, article_id: int) -> bool:
    row = get_blog_article_by_id(db, article_id)
    if not row:
        return False
    db.execute(delete(BlogArticleVersion).where(BlogArticleVersion.article_id == article_id))
    db.delete(row)
    return True


def count_articles_sharing_primary_keyword(db: Session, keywords: str) -> int:
    parts = [x.strip().lower() for x in (keywords or "").split(",") if len(x.strip()) > 2]
    if not parts:
        return 0
    pk = parts[0]
    n = db.execute(
        select(func.count()).select_from(BlogArticle).where(func.lower(BlogArticle.keywords).like(f"%{pk}%"))
    ).scalar_one_or_none()
    return int(n or 0)


def count_articles_by_author_since(db: Session, email: str, hours: int = 24) -> int:
    if not (email or "").strip():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    n = db.execute(
        select(func.count())
        .select_from(BlogArticle)
        .where(BlogArticle.author_email == email.strip(), BlogArticle.created_at >= cutoff)
    ).scalar_one_or_none()
    return int(n or 0)


def count_near_duplicate_titles(db: Session, title: str) -> int:
    """Rough guard: same normalized prefix (first 48 chars) as existing titles."""
    t = (title or "").strip().lower()[:48]
    if len(t) < 12:
        return 0
    n = db.execute(
        select(func.count()).select_from(BlogArticle).where(func.lower(BlogArticle.title).like(f"{t}%"))
    ).scalar_one_or_none()
    return int(n or 0)


def list_content_clusters(db: Session) -> List[Dict[str, Any]]:
    rows = (
        db.execute(select(ContentCluster).order_by(ContentCluster.name.asc())).scalars().all()
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "slug": r.slug,
                "name": r.name,
                "description": r.description or "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def get_content_cluster_by_id(db: Session, cluster_id: int) -> Optional[ContentCluster]:
    return db.execute(select(ContentCluster).where(ContentCluster.id == cluster_id)).scalars().one_or_none()


def get_content_cluster_by_slug(db: Session, slug: str) -> Optional[ContentCluster]:
    return db.execute(select(ContentCluster).where(ContentCluster.slug == slug)).scalars().one_or_none()


def create_content_cluster(
    db: Session,
    *,
    slug: str,
    name: str,
    description: str = "",
) -> ContentCluster:
    import re

    s = re.sub(r"[^a-z0-9]+", "-", (slug or "").lower()).strip("-")[:120] or "cluster"
    base = s
    n = 2
    while get_content_cluster_by_slug(db, s):
        s = f"{base[:100]}-{n}"
        n += 1
    row = ContentCluster(slug=s, name=name[:255], description=description or None)
    db.add(row)
    db.flush()
    return row


def list_blog_article_versions(db: Session, article_id: int, limit: int = 80) -> List[Dict[str, Any]]:
    rows = (
        db.execute(
            select(BlogArticleVersion)
            .where(BlogArticleVersion.article_id == article_id)
            .order_by(BlogArticleVersion.created_at.desc())
            .limit(min(max(1, limit), 500))
        )
        .scalars()
        .all()
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "article_id": r.article_id,
                "title": r.title,
                "meta_description": r.meta_description or "",
                "content_html": (r.content_html or "")[:400] + ("…" if len(r.content_html or "") > 400 else ""),
                "content_len": len(r.content_html or ""),
                "author_email": r.author_email or "",
                "note": r.note or "",
                "change_summary": r.change_summary or "",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def get_blog_article_version_full(db: Session, version_id: int) -> Optional[BlogArticleVersion]:
    return db.execute(select(BlogArticleVersion).where(BlogArticleVersion.id == version_id)).scalars().one_or_none()


def add_blog_article_version(
    db: Session,
    *,
    article_id: int,
    title: str,
    content_html: str,
    meta_description: str,
    author_email: str,
    note: str = "",
    change_summary: str = "",
) -> BlogArticleVersion:
    row = BlogArticleVersion(
        article_id=article_id,
        title=title[:500],
        content_html=content_html or "",
        meta_description=meta_description or None,
        author_email=author_email or None,
        note=note or None,
        change_summary=(change_summary or None)[:255],
    )
    db.add(row)
    db.flush()
    return row


def list_articles_in_cluster(db: Session, cluster_id: int) -> List[Dict[str, Any]]:
    rows = (
        db.execute(
            select(BlogArticle)
            .where(BlogArticle.cluster_id == cluster_id)
            .order_by(BlogArticle.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return [blog_article_to_dict(r) for r in rows]
