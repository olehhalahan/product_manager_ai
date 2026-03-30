"""
Customer subscription: 3-day free trial, paid plans via WayForPay.
Admins bypass checks (see ``is_admin`` at call sites).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

FREE_TRIAL_DAYS = 3  # re-export for db_repository / docs
PAID_SUBSCRIPTION_DAYS = 31
ADMIN_MONTHLY_CAP = 999_999

_DEFAULT_LIMITS = {"free": 50, "starter": 500, "growth": 2000, "pro": 6000}
_PLAN_LIMITS_CACHE: Optional[Dict[str, int]] = None


def monthly_limits_by_plan() -> Dict[str, int]:
    global _PLAN_LIMITS_CACHE
    if _PLAN_LIMITS_CACHE is not None:
        return _PLAN_LIMITS_CACHE
    out = dict(_DEFAULT_LIMITS)
    try:
        from ..pricing_page import load_pricing_config

        for p in load_pricing_config().get("plans") or []:
            pid = p.get("id")
            lim = p.get("monthly_product_limit")
            if pid and isinstance(lim, int) and lim > 0:
                out[str(pid)] = lim
    except Exception:
        pass
    _PLAN_LIMITS_CACHE = out
    return out


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_PLAN_LABEL_UK = {
    "free": "FREE",
    "starter": "STARTER",
    "growth": "GROWTH",
    "pro": "PRO",
}


def format_admin_subscription_cell_uk(
    *,
    role: str,
    subscription_plan: str,
    subscription_status: str,
    free_trial_ends_at: Optional[datetime],
    subscription_valid_until: Optional[datetime],
    now: Optional[datetime] = None,
) -> str:
    """Short Ukrainian label for admin Users table (Settings → Users)."""
    now = _as_utc(now) or _utcnow()
    if (role or "").lower().strip() == "admin":
        return "Адмін (без обмежень підписки)"

    plan = (subscription_plan or "free").strip().lower()
    name = _PLAN_LABEL_UK.get(plan, plan.upper() or "—")
    paid_until = _as_utc(subscription_valid_until)
    trial_end = _as_utc(free_trial_ends_at)

    paid_ok = paid_until is not None and paid_until > now and plan in ("starter", "growth", "pro")
    trial_ok = trial_end is not None and trial_end > now and not paid_ok

    def _fmt(d: datetime) -> str:
        return d.strftime("%d.%m.%Y %H:%M UTC")

    if paid_ok:
        return f"Оплачено · {name} · до {_fmt(paid_until)}"
    if trial_ok:
        return f"Пробний · {name} · до {_fmt(trial_end)}"
    if plan in ("starter", "growth", "pro") and paid_until is not None and paid_until <= now:
        return f"Закінчилось · {name} (було до {_fmt(paid_until)})"
    if trial_end is not None and trial_end <= now:
        return "Пробний закінчився · оплати немає"
    return "Немає активної підписки"


@dataclass
class SubscriptionAccess:
    can_use_service: bool
    is_admin_bypass: bool
    effective_plan: str
    subscription_plan: str
    subscription_status: str
    free_trial_ends_at: Optional[str] = None
    subscription_valid_until: Optional[str] = None
    monthly_product_limit: int = 0
    products_used_this_month: int = 0
    message_uk: str = ""


def build_subscription_access(
    db: Session,
    email: str,
    *,
    is_admin: bool,
    product_count_hint: int = 0,
    enforce_monthly_cap: bool = True,
) -> SubscriptionAccess:
    if is_admin:
        return SubscriptionAccess(
            can_use_service=True,
            is_admin_bypass=True,
            effective_plan="pro",
            subscription_plan="pro",
            subscription_status="active",
            monthly_product_limit=ADMIN_MONTHLY_CAP,
            products_used_this_month=0,
            message_uk="",
        )

    from ..services import db_repository as repo

    em = (email or "").strip().lower()
    row = repo.fetch_user_orm_by_email(db, em)
    if not row:
        return SubscriptionAccess(
            can_use_service=False,
            is_admin_bypass=False,
            effective_plan="expired",
            subscription_plan="free",
            subscription_status="trial",
            message_uk="Користувача не знайдено.",
        )

    repo.ensure_user_subscription_defaults(db, row)
    now = _utcnow()

    lim_map = monthly_limits_by_plan()
    used = repo.count_user_products_in_month(db, em)

    paid_until = _as_utc(getattr(row, "subscription_valid_until", None))
    trial_end = _as_utc(getattr(row, "free_trial_ends_at", None))
    stored_plan = (getattr(row, "subscription_plan", None) or "free").strip()
    stored_status = (getattr(row, "subscription_status", None) or "trial").strip()

    paid_active = (
        paid_until is not None
        and paid_until > now
        and stored_plan in ("starter", "growth", "pro")
    )
    trial_active = trial_end is not None and trial_end > now and not paid_active

    if paid_active:
        eff = stored_plan
        can = True
        msg = ""
        limit = lim_map.get(eff, lim_map.get("pro", 6000))
    elif trial_active:
        eff = "free"
        can = True
        limit = lim_map.get("free", 50)
        days_left = max(0, (trial_end - now).days) if trial_end else 0
        msg = f"Безкоштовний період: залишилось орієнтовно {days_left} дн. Після цього оберіть платний план."
    else:
        eff = "expired"
        can = False
        limit = 0
        msg = "Термін безкоштовного доступу закінчився або підписку не продовжено. Оберіть платний план на сторінці тарифів."

    if (
        enforce_monthly_cap
        and can
        and limit > 0
        and used + product_count_hint > limit
    ):
        can = False
        msg = (
            f"Ліміт товарів на місяць для вашого плану вичерпано ({used} з {limit}). "
            "Очікуйте наступного місяця або оновіть підписку."
        )

    return SubscriptionAccess(
        can_use_service=can,
        is_admin_bypass=False,
        effective_plan=eff,
        subscription_plan=stored_plan,
        subscription_status=stored_status,
        free_trial_ends_at=trial_end.isoformat() if trial_end else None,
        subscription_valid_until=paid_until.isoformat() if paid_until else None,
        monthly_product_limit=limit,
        products_used_this_month=used,
        message_uk=msg,
    )
