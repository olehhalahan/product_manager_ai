from dotenv import load_dotenv
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")
load_dotenv(_root / ".env.local", override=True)  # local overrides (gitignored); must override .env

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.middleware.sessions import SessionMiddleware
from typing import List, Optional
import io
import csv
import uuid

from .models import NormalizedProduct, BatchStatus, BatchSummary
from .services.importer import parse_csv_file
from .services.csv_security import validate_csv_content
from .services.normalizer import normalize_records, guess_mapping, INTERNAL_FIELDS
from .services.rule_engine import decide_actions_for_products
from .services.exporter import generate_result_csv
from .services.postgres_storage import PostgresStorage
from .auth import (
    get_session_secret,
    get_oauth,
    get_current_user,
    get_user_role,
    is_admin,
    require_login_redirect,
    require_login_http,
    require_admin_redirect,
    require_admin_http,
)
import json
from datetime import datetime, timezone

from .writter_routes import register_writter_routes
from .admin_nav import ADMIN_MERCHANT_SCRIPT, ADMIN_THEME_SCRIPT, admin_top_nav_html

app = FastAPI(title="Product Content Optimizer", docs_url=None)

# Favicon + GTM container (GA4 via GTM: Google Tag / GA4 Config, Trigger: All Pages)
import os as _os
_GTM_ID = _os.getenv("GTM_CONTAINER_ID", "GTM-W25B668S")
# Google Search Console — HTML tag verification (homepage <head>); override via GOOGLE_SITE_VERIFICATION in .env
_GOOGLE_SITE_VERIFICATION = _os.getenv("GOOGLE_SITE_VERIFICATION", "PBIv7Juyd9qX3pFJ-8NbZXkVKhMy0jdQZd3YvG1WiB8").strip()
_GSC_META_LINE = (
    f'    <meta name="google-site-verification" content="{_GOOGLE_SITE_VERIFICATION}" />\n'
    if _GOOGLE_SITE_VERIFICATION
    else ""
)
_GTM_HEAD = f"""    <link rel="icon" href="/assets/favicon.png" type="image/png" />
    <link rel="shortcut icon" href="/assets/favicon.png" type="image/png" />
{_GSC_META_LINE}    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
    <!-- Google Tag Manager -->
    <script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{_GTM_ID}');</script>
    <!-- End Google Tag Manager -->
"""
_GTM_BODY = f"""    <!-- Google Tag Manager (noscript) -->
    <noscript><iframe src="https://www.googletagmanager.com/ns.html?id={_GTM_ID}"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
    <!-- End Google Tag Manager (noscript) -->
"""
GTM_HEAD = _GTM_HEAD
GTM_BODY = _GTM_BODY
app.add_middleware(SessionMiddleware, secret_key=get_session_secret())


@app.on_event("startup")
def startup():
    """Create database tables on startup."""
    import logging

    logging.getLogger("uvicorn.error").info("app.main loaded from: %s", __file__)
    from .db import init_db
    init_db()
    from .google_cloud import log_google_cloud_startup

    log_google_cloud_startup()


storage = PostgresStorage()


def _batch_history_label(status: str, merchant_pushed_at: Optional[str], closed_at: Optional[str]) -> str:
    """English label for batch history (review page)."""
    if closed_at:
        return "Closed"
    if merchant_pushed_at:
        return "Sent"
    if status in ("normalized", "processing", "partially_done"):
        return "Pending processing"
    return "New"


def _ensure_batch_owner_from_batch(request: Request, batch) -> None:
    """403 if the batch belongs to another user. Batches with no owner (legacy) stay accessible."""
    user = get_current_user(request)
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    owner = (getattr(batch, "user_email", None) or "").strip().lower()
    if owner and owner != email:
        raise HTTPException(status_code=403, detail="Access denied.")


_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA_DIR = _os.path.join(_PROJECT_ROOT, "data")
_os.makedirs(_DATA_DIR, exist_ok=True)


def _get_db_session():
    """Yield a DB session for the current request."""
    from .db import get_db
    with get_db() as db:
        yield db


def _get_settings():
    """Load settings from DB."""
    from .db import get_db
    from .services.db_repository import get_settings as db_get_settings
    with get_db() as db:
        return db_get_settings(db)


def _build_batch_history_html(current_batch_id: str, user_email: str) -> str:
    """HTML block: table of the user's batches (newest first)."""
    import html as html_module

    from .db import get_db
    from .services.db_repository import list_batches_for_user

    email = (user_email or "").strip().lower()
    if not email:
        return (
            '<section class="batch-history batch-history--empty" aria-label="Your batches">'
            '<h2 class="batch-history-title">Your batches</h2>'
            '<p class="batch-history-empty">Sign in to see your batch history.</p>'
            "</section>"
        )
    with get_db() as db:
        rows = list_batches_for_user(db, email, limit=50)
    if not rows:
        return (
            '<section class="batch-history batch-history--empty" aria-label="Your batches">'
            '<h2 class="batch-history-title">Your batches</h2>'
            '<p class="batch-history-empty">No batches yet. <a class="batch-history-empty-link" href="/upload">Upload a feed</a> to get started.</p>'
            "</section>"
        )
    status_class = {
        "Closed": "closed",
        "Sent": "sent",
        "Pending processing": "pending",
        "New": "new",
    }
    tr_parts: List[str] = []
    for row in rows:
        bid = row["batch_id"]
        lbl = _batch_history_label(
            row["status"],
            row.get("merchant_pushed_at"),
            row.get("closed_at"),
        )
        sc = status_class.get(lbl, "new")
        short = bid[:8] + "…" if len(bid) > 8 else bid
        created = row.get("created_at") or ""
        if len(created) > 16:
            created = created[:16].replace("T", " ")
        cur_cls = " batch-history-row--current" if bid == current_batch_id else ""
        esc_bid = html_module.escape(bid)
        esc_short = html_module.escape(short)
        esc_lbl = html_module.escape(lbl)
        esc_created = html_module.escape(created)
        n = int(row.get("product_count") or 0)
        close_btn = ""
        if not row.get("closed_at"):
            close_btn = (
                f'<button type="button" class="btn btn-outline btn-sm batch-history-close" '
                f'data-batch-id="{esc_bid}">Close</button>'
            )
        tr_parts.append(
            f'<tr class="batch-history-row{cur_cls}">'
            f'<td><a class="batch-history-link" href="/batches/{esc_bid}/review">{esc_short}</a></td>'
            f'<td class="batch-history-meta">{esc_created}</td>'
            f'<td class="batch-history-meta">{n}</td>'
            f'<td><span class="batch-history-pill batch-history-pill--{sc}">{esc_lbl}</span></td>'
            f'<td class="batch-history-actions">'
            f'<a class="btn btn-outline btn-sm" href="/batches/{esc_bid}/review">Open</a> {close_btn}'
            f"</td></tr>"
        )
    return (
        '<section class="batch-history" aria-label="Your batches">'
        "<h2 class=\"batch-history-title\">Your batches</h2>"
        '<div class="batch-history-scroll">'
        "<table class=\"batch-history-table\">"
        "<thead><tr>"
        "<th>Batch</th><th>Created</th><th>Products</th><th>Status</th><th></th>"
        "</tr></thead><tbody>"
        + "".join(tr_parts)
        + "</tbody></table></div>"
        "<p class=\"batch-history-hint\">Open any batch to review, edit, or push products to Merchant again.</p>"
        "</section>"
    )


def _wrap_batches_history_shell(*, page_title: str, body_inner: str, user_role: str) -> str:
    """Full HTML document for /batches/history (shared nav + batch-history styles)."""
    admin_nav = _admin_nav_links(active="", user_role=user_role)
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{page_title} &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.loaded{{opacity:1}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    .nav {{ display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); position: sticky; top: 0; background: rgba(10,10,10,0.95); backdrop-filter: blur(10px); z-index: 100; }}
    [data-theme="light"] .nav {{ border-bottom-color: rgba(15,23,42,0.08); background: rgba(248,250,252,0.95); }}
    .nav-logo img {{ height: 32px; }}
    .nav-logo .logo-light {{ display: block; filter: brightness(0) invert(1); }}
    .nav-logo .logo-dark {{ display: none; }}
    [data-theme="light"] .nav-logo .logo-light {{ display: none; }}
    [data-theme="light"] .nav-logo .logo-dark {{ display: block; filter: none; }}
    .nav-links {{ display: flex; align-items: center; gap: 28px; }}
    .nav-link {{ color: rgba(255,255,255,0.65); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }}
    .nav-link:hover {{ color: #fff; }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover {{ color: #0f172a; }}
    .theme-btn {{ display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: rgba(255,255,255,0.6); cursor: pointer; font-size: 1rem; transition: all 0.2s; }}
    .theme-btn:hover {{ color: #fff; background: rgba(255,255,255,0.08); }}
    [data-theme="light"] .theme-btn {{ border-color: rgba(15,23,42,0.15); color: rgba(15,23,42,0.6); }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 32px 48px 48px; }}
    .page-h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 8px; letter-spacing: -0.02em; }}
    .page-sub {{ font-size: 0.85rem; color: rgba(255,255,255,0.45); margin-bottom: 20px; }}
    .page-sub a {{ color: #22D3EE; text-decoration: none; }}
    .page-sub a:hover {{ text-decoration: underline; }}
    [data-theme="light"] .page-sub {{ color: rgba(15,23,42,0.5); }}
    .btn {{ display: inline-block; padding: 8px 14px; font-size: 0.8rem; font-weight: 600; border-radius: 8px; text-decoration: none; cursor: pointer; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: #e5e5e5; }}
    .btn-outline {{ border-color: rgba(255,255,255,0.25); }}
    .btn-outline:hover {{ background: rgba(255,255,255,0.08); }}
    [data-theme="light"] .btn {{ border-color: rgba(15,23,42,0.2); color: #0f172a; }}
    .btn-sm {{ padding: 6px 12px; font-size: 0.75rem; }}
    .batch-history {{ margin-bottom: 0; padding: 20px 22px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.02); }}
    .batch-history--empty {{ min-height: 120px; }}
    .batch-history-title {{ font-size: 1rem; font-weight: 600; margin-bottom: 14px; color: rgba(255,255,255,0.95); }}
    .batch-history-empty {{ font-size: 0.88rem; color: rgba(255,255,255,0.55); line-height: 1.5; }}
    .batch-history-empty-link {{ color: #22D3EE; }}
    .batch-history-scroll {{ overflow-x: auto; }}
    .batch-history-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; min-width: 520px; }}
    .batch-history-table th {{ text-align: left; padding: 10px 12px; color: rgba(255,255,255,0.45); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.68rem; border-bottom: 1px solid rgba(255,255,255,0.08); }}
    .batch-history-table td {{ padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: middle; }}
    .batch-history-row--current {{ background: rgba(34,211,238,0.06); }}
    .batch-history-link {{ color: #22D3EE; font-weight: 600; text-decoration: none; }}
    .batch-history-link:hover {{ text-decoration: underline; }}
    .batch-history-meta {{ color: rgba(255,255,255,0.5); white-space: nowrap; }}
    .batch-history-pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 600; }}
    .batch-history-pill--closed {{ background: rgba(148,163,184,0.2); color: #e2e8f0; }}
    .batch-history-pill--sent {{ background: rgba(34,211,238,0.15); color: #67e8f9; }}
    .batch-history-pill--pending {{ background: rgba(245,158,11,0.2); color: #fde68a; }}
    .batch-history-pill--new {{ background: rgba(99,102,241,0.2); color: #c7d2fe; }}
    .batch-history-actions {{ white-space: nowrap; }}
    .batch-history-actions .btn {{ margin-left: 6px; }}
    .batch-history-hint {{ font-size: 0.78rem; color: rgba(255,255,255,0.4); margin-top: 12px; margin-bottom: 0; line-height: 1.45; }}
    [data-theme="light"] .batch-history {{ background: rgba(255,255,255,0.9); border-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] .batch-history-title {{ color: #0f172a; }}
    [data-theme="light"] .batch-history-table th {{ color: rgba(15,23,42,0.45); border-bottom-color: rgba(15,23,42,0.08); }}
    [data-theme="light"] .batch-history-table td {{ border-bottom-color: rgba(15,23,42,0.06); }}
    [data-theme="light"] .batch-history-row--current {{ background: rgba(34,211,238,0.1); }}
    [data-theme="light"] .batch-history-meta {{ color: rgba(15,23,42,0.55); }}
    [data-theme="light"] .batch-history-hint {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .batch-history-empty {{ color: rgba(15,23,42,0.55); }}
    </style>
</head>
<body class="loaded">
{GTM_BODY}
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="nav-links">
            <a href="/batches/history" class="nav-link" style="color:#22D3EE;font-weight:600">Batch history</a>
            {admin_nav}
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
        </div>
    </nav>
    <div class="container">
        <h1 class="page-h1">{page_title}</h1>
        <p class="page-sub"><a href="/upload">Upload</a> &middot; <a href="/">Home</a></p>
        {body_inner}
    </div>
    <script>
    (function(){{
        const themeToggle=document.getElementById("themeToggle");
        if(themeToggle){{const THEME_KEY="hp-theme";function getT(){{return localStorage.getItem(THEME_KEY)||"dark";}}function setT(t){{document.documentElement.setAttribute("data-theme",t);localStorage.setItem(THEME_KEY,t);themeToggle.textContent=t==="dark"?"\\u2600":"\\u263E";}}themeToggle.onclick=()=>setT(getT()==="dark"?"light":"dark");setT(getT());}}
    }})();
    document.querySelectorAll(".batch-history-close").forEach(function(btn){{
        btn.addEventListener("click", async function(){{
            var bid = btn.getAttribute("data-batch-id");
            if (!bid || !confirm("Close this batch? It will be marked Closed in your history.")) return;
            try {{
                var r = await fetch("/batches/" + encodeURIComponent(bid) + "/close", {{ method: "POST", credentials: "same-origin", headers: {{ "Accept": "application/json" }} }});
                if (!r.ok) {{ alert("Could not close batch."); return; }}
                window.location.reload();
            }} catch (e) {{ alert("Could not close batch."); }}
        }});
    }});
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


def _track_user(user: dict):
    """Record user in DB on login."""
    from .db import get_db
    from .services.db_repository import upsert_user
    with get_db() as db:
        upsert_user(db, user)


# Onboarding funnel (7 steps) — cookie-bound, server-side; see /admin/onboarding-analytics
_OB_COOKIE = "cartozo_ob_sid"
_OB_MAX_AGE = 90 * 24 * 60 * 60


def _onboarding_track(
    request: Request,
    response: Optional[HTMLResponse],
    step: int,
    source: Optional[str] = None,
) -> None:
    """
    Record funnel step (1–7). Creates session + cookie on first HTML response if missing.
    For JSON-only endpoints pass response=None (requires existing cookie from /upload flow).
    """
    user = get_current_user(request)
    if not user:
        return
    sid = request.cookies.get(_OB_COOKIE)
    if not sid:
        if response is None:
            return
        utm = (request.query_params.get("utm_source") or request.query_params.get("source") or "").strip()[:128]
        from .db import get_db
        from .services.db_repository import create_onboarding_session
        with get_db() as db:
            sid = create_onboarding_session(
                db,
                email=user.get("email"),
                name=user.get("name"),
                source=utm or None,
            )
        response.set_cookie(
            _OB_COOKIE,
            sid,
            max_age=_OB_MAX_AGE,
            httponly=True,
            samesite="lax",
            path="/",
        )
    from .db import get_db
    from .services.db_repository import update_onboarding_progress
    with get_db() as db:
        update_onboarding_progress(db, sid, step, source=source)


def _onboarding_export_done(request: Request) -> None:
    """Step 6 + mark completed when user exports CSV."""
    sid = request.cookies.get(_OB_COOKIE)
    if not sid:
        return
    from .db import get_db
    from .services.db_repository import update_onboarding_progress, complete_onboarding
    with get_db() as db:
        update_onboarding_progress(db, sid, 6)
        complete_onboarding(db, sid)


def _build_error_page(status_code: int = 404, message: str = "Page not found") -> str:
    """Build 404/error page HTML for any bad result."""
    title = "Page not found" if status_code == 404 else "Something went wrong"
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title} &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; -webkit-font-smoothing: antialiased; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    .err-nav {{ position: fixed; top: 0; left: 0; right: 0; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.9); backdrop-filter: blur(12px); }}
    [data-theme="light"] .err-nav {{ background: rgba(248,250,252,0.95); border-color: rgba(15,23,42,0.08); }}
    .err-nav-logo img {{ height: 32px; filter: brightness(0) invert(1); }}
    [data-theme="light"] .err-nav-logo img {{ filter: none; }}
    .err-nav-cta {{ background: #fff; color: #0B0F19; padding: 10px 20px; border-radius: 6px; font-size: 0.85rem; font-weight: 500; text-decoration: none; }}
    [data-theme="light"] .err-nav-cta {{ background: #0f172a; color: #fff; }}
    .err-box {{ text-align: center; padding: 48px 24px; max-width: 480px; }}
    .err-code {{ font-size: 4rem; font-weight: 800; color: #22D3EE; letter-spacing: -0.04em; margin-bottom: 16px; }}
    .err-title {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 12px; }}
    .err-msg {{ color: #9ca3af; font-size: 1rem; line-height: 1.6; margin-bottom: 32px; }}
    [data-theme="light"] .err-msg {{ color: rgba(15,23,42,0.6); }}
    .err-btn {{ display: inline-block; padding: 14px 28px; background: #4F46E5; color: #fff; border-radius: 6px; font-size: 0.9rem; font-weight: 500; text-decoration: none; transition: opacity 0.2s; }}
    .err-btn:hover {{ opacity: 0.9; }}
    </style>
</head>
<body>
{GTM_BODY}
    <nav class="err-nav">
        <a href="/" class="err-nav-logo"><img src="/assets/logo-light.png" alt="Cartozo.ai" /></a>
        <a href="/" class="err-nav-cta">Go to homepage</a>
    </nav>
    <div class="err-box">
        <div class="err-code">{status_code}</div>
        <h1 class="err-title">{title}</h1>
        <p class="err-msg">{message}</p>
        <a href="/" class="err-btn">Back to homepage</a>
    </div>
</body>
</html>"""


app.mount("/static", StaticFiles(directory=_os.path.join(_PROJECT_ROOT, "static")), name="static")
app.mount("/assets", StaticFiles(directory=_os.path.join(_PROJECT_ROOT, "assets")), name="assets")


def _wants_html(request: Request) -> bool:
    """True if client prefers HTML over JSON (for error pages)."""
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept:
        return False
    # fetch() often sends Accept: */* — must not return HTML for JSON APIs
    if (request.url.path or "").startswith("/api/"):
        return False
    return "text/html" in accept or ("*/*" in accept and "application/json" not in accept)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Show custom 404/error page for browser requests."""
    if _wants_html(request):
        msg = str(exc.detail) if isinstance(exc.detail, str) else "Something went wrong"
        return HTMLResponse(content=_build_error_page(exc.status_code, msg), status_code=exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})




@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Show error page for unhandled exceptions (500)."""
    if _wants_html(request):
        return HTMLResponse(content=_build_error_page(500, "An unexpected error occurred. Please try again."), status_code=500)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon_redirect():
    """Redirect to favicon for browsers that request /favicon.ico."""
    return RedirectResponse(url="/assets/favicon.png", status_code=302)


@app.get("/docs", include_in_schema=False)
def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Product Content Optimizer – API",
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
        swagger_css_url="/static/swagger-overrides.css",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth routes (Google + Apple OAuth)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login page. Redirect to upload if already logged in."""
    if request.session.get("user"):
        next_url = request.query_params.get("next", "/upload")
        return RedirectResponse(url=next_url, status_code=302)
    from .google_cloud import get_normalized_google_oauth_credentials

    _gid, _gsec = get_normalized_google_oauth_credentials()
    has_google = bool(_gid and _gsec)
    has_apple = bool(_os.getenv("APPLE_CLIENT_ID") and _os.getenv("APPLE_KEY_ID") and _os.getenv("APPLE_TEAM_ID") and _os.getenv("APPLE_PRIVATE_KEY"))
    next_url = request.query_params.get("next", "/upload")
    oauth_err = request.query_params.get("oauth_err", "").strip()
    return HTMLResponse(
        content=_build_login_page(
            next_url=next_url,
            has_google=has_google,
            has_apple=has_apple,
            request_host=request.headers.get("host", ""),
            oauth_err=oauth_err,
        )
    )


@app.get("/auth/google")
async def auth_google(request: Request):
    """Redirect to Google OAuth."""
    next_url = request.query_params.get("next", "/upload")
    request.session["next_url"] = next_url
    oauth = get_oauth()
    try:
        client = oauth.create_client("google")
    except Exception:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    # Use DEPLOY_URL when behind reverse proxy so redirect_uri matches Google Console
    deploy_url = (_os.getenv("DEPLOY_URL") or "").rstrip("/")
    if deploy_url:
        redirect_uri = f"{deploy_url}/auth/google/callback"
    else:
        redirect_uri = str(request.url_for("auth_google_callback"))
    return await client.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback", name="auth_google_callback")
async def auth_google_callback(request: Request):
    """Handle Google OAuth callback."""
    err = request.query_params.get("error")
    if err:
        from urllib.parse import quote as _quote

        if err == "deleted_client" or "deleted" in err.lower():
            return RedirectResponse(url="/login?oauth_err=deleted_client", status_code=302)
        return RedirectResponse(url=f"/login?oauth_err={_quote(err)}", status_code=302)
    oauth = get_oauth()
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth failed: {e}")
    userinfo = token.get("userinfo") or {}
    email = userinfo.get("email", "")
    user = {
        "id": userinfo.get("sub", ""),
        "email": email,
        "name": userinfo.get("name", userinfo.get("email", "User")),
        "provider": "google",
        "role": get_user_role(email),
    }
    request.session["user"] = user
    _track_user(user)
    next_url = request.session.pop("next_url", "/upload")
    return RedirectResponse(url=next_url, status_code=302)


@app.get("/auth/apple")
async def auth_apple(request: Request):
    """Redirect to Apple Sign-In."""
    oauth = get_oauth()
    try:
        client = oauth.create_client("apple")
    except Exception:
        raise HTTPException(status_code=500, detail="Apple Sign-In not configured")
    next_url = request.query_params.get("next", "/upload")
    request.session["next_url"] = next_url
    redirect_uri = str(request.url_for("auth_apple_callback"))
    return await client.authorize_redirect(request, redirect_uri)


@app.get("/auth/apple/callback", name="auth_apple_callback")
async def auth_apple_callback(request: Request):
    """Handle Apple OAuth callback."""
    oauth = get_oauth()
    try:
        token = await oauth.apple.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth failed: {e}")
    userinfo = token.get("userinfo") or {}
    # Apple may return email in userinfo or only on first sign-in
    email = userinfo.get("email", "")
    user = {
        "id": userinfo.get("sub", ""),
        "email": email,
        "name": userinfo.get("name", {}).get("firstName", userinfo.get("email", "User")) if isinstance(userinfo.get("name"), dict) else (userinfo.get("name") or userinfo.get("email") or "User"),
        "provider": "apple",
        "role": get_user_role(email),
    }
    request.session["user"] = user
    _track_user(user)
    next_url = request.session.pop("next_url", "/upload")
    return RedirectResponse(url=next_url, status_code=302)


@app.get("/auth/dev")
async def auth_dev(request: Request):
    """Dev bypass: create fake session when OAuth not configured (for local testing)."""
    if not (_os.getenv("GOOGLE_CLIENT_ID") or _os.getenv("APPLE_CLIENT_ID")):
        next_url = request.query_params.get("next", "/upload")
        email = "oleh.halahan@zanzarra.com"
        user = {
            "id": "dev-user",
            "email": email,
            "name": "Dev Admin",
            "provider": "dev",
            "role": get_user_role(email),
        }
        request.session["user"] = user
        _track_user(user)
        return RedirectResponse(url=next_url, status_code=302)
    raise HTTPException(status_code=404, detail="Dev auth not available when OAuth is configured")


@app.get("/logout")
async def logout(request: Request):
    """Clear session and redirect home."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


MERCHANT_PUSH_RESOLVE_HINT = ""

# Exposed in X-Cartozo-Upload-UI header and /health — bump when /upload HTML changes.
UPLOAD_UI_REVISION = "3"


def _gmc_merchant_id_env_configured() -> bool:
    from .services import google_merchant as gmc

    return bool(gmc.effective_gmc_merchant_id_override())


def _oauth_debug_json(request: Request) -> JSONResponse:
    """Which GOOGLE_CLIENT_ID this process reads (no secrets). Aliases: /api/auth/oauth-debug, /oauth-debug."""
    from .google_cloud import get_normalized_google_oauth_credentials

    cid, _sec = get_normalized_google_oauth_credentials()
    has_sec = bool(_sec)
    deploy = (_os.getenv("DEPLOY_URL") or "").strip().rstrip("/")
    if deploy:
        login_redirect_uri = f"{deploy}/auth/google/callback"
        merchant_redirect_uri = f"{deploy}/auth/google/merchant/callback"
    else:
        login_redirect_uri = str(request.url_for("auth_google_callback"))
        merchant_redirect_uri = str(request.url_for("auth_google_merchant_callback"))
    return JSONResponse(
        content={
            "google_client_id": cid,
            "client_configured": bool(cid and has_sec),
            "deploy_url": deploy or None,
            "effective_redirect_uri_for_login": login_redirect_uri,
            "effective_redirect_uri_for_merchant": merchant_redirect_uri,
            "redirect_uri_mismatch_hint": "Error 400 redirect_uri_mismatch: add this exact URI (scheme + host + port + path) to Authorized redirect URIs. If you open the app as http://127.0.0.1:8000 but only registered localhost (or vice versa), add both.",
            "deleted_client_meaning": "Google says this client_id does not exist. Create a NEW OAuth 2.0 Client ID (Web) in Google Cloud → Credentials and put the new GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env (and hosting env for production), then restart.",
            "hint": "Compare google_client_id with Credentials list. If testing cartozo.ai, call this URL on that host — local .env does not change production.",
            "merchant_push_resolve_hint": MERCHANT_PUSH_RESOLVE_HINT,
            "gmc_merchant_id_env_set": _gmc_merchant_id_env_configured(),
            "routes": ["/api/auth/oauth-debug", "/oauth-debug"],
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/auth/oauth-debug")
def oauth_debug(request: Request):
    """Debug: env client id + effective redirect URI (see also GET /oauth-debug)."""
    return _oauth_debug_json(request)


@app.get("/oauth-debug")
def oauth_debug_short(request: Request):
    """Same JSON as /api/auth/oauth-debug (shorter URL for quick checks)."""
    return _oauth_debug_json(request)


# ─────────────────────────────────────────────────────────────────────────────
# Google Merchant Center (Merchant API) — OAuth + stored refresh token
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/merchant/google/connect")
async def merchant_google_connect(request: Request):
    """Start OAuth for https://www.googleapis.com/auth/content (all logged-in users)."""
    redir = require_login_redirect(request, "/merchant/google/connect")
    if redir:
        return redir
    oauth = get_oauth()
    try:
        client = oauth.create_client("google_merchant")
    except Exception:
        raise HTTPException(status_code=500, detail="Google Merchant OAuth not configured")
    deploy_url = (_os.getenv("DEPLOY_URL") or "").rstrip("/")
    if deploy_url:
        redirect_uri = f"{deploy_url}/auth/google/merchant/callback"
    else:
        redirect_uri = str(request.url_for("auth_google_merchant_callback"))
    request.session["merchant_oauth_next"] = request.query_params.get("next", "/upload")
    return await client.authorize_redirect(
        request,
        redirect_uri,
        scope="https://www.googleapis.com/auth/content",
        access_type="offline",
        prompt="consent",
    )


@app.get("/auth/google/merchant/callback", name="auth_google_merchant_callback")
async def auth_google_merchant_callback(request: Request):
    """Store refresh token + merchant id for Merchant API."""
    user = get_current_user(request)
    if not user or not user.get("email"):
        return RedirectResponse(url="/login?next=/upload", status_code=302)
    email = user.get("email", "").strip()
    oauth_err = request.query_params.get("error")
    if oauth_err:
        desc = request.query_params.get("error_description") or oauth_err
        raise HTTPException(status_code=400, detail=f"Merchant OAuth failed: {desc}")
    oauth = get_oauth()
    try:
        client = oauth.create_client("google_merchant")
    except Exception:
        raise HTTPException(status_code=500, detail="Google Merchant OAuth not configured")
    # Do not pass redirect_uri= here: authorize_redirect already stored it in session;
    # Authlib merges it into params and fetch_access_token(redirect_uri=...) would duplicate.
    try:
        token = await client.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Merchant OAuth failed: {e}")
    refresh_token = token.get("refresh_token")
    access_token = token.get("access_token")
    merchant_id = None
    if access_token:
        from .services.google_merchant import fetch_primary_merchant_id

        merchant_id = await fetch_primary_merchant_id(access_token)

    from .db import get_db
    from .services.db_repository import get_user_by_email, save_google_merchant_oauth

    with get_db() as db:
        row = get_user_by_email(db, email)
        effective_rt = refresh_token or (row.merchant_refresh_token if row else None)
        save_google_merchant_oauth(db, email, effective_rt, merchant_id)

    next_url = request.session.pop("merchant_oauth_next", "/upload")
    sep = "&" if "?" in next_url else "?"
    return RedirectResponse(url=f"{next_url}{sep}merchant=connected", status_code=302)


@app.get("/api/merchant/status")
async def api_merchant_status(request: Request):
    require_login_http(request)
    user = get_current_user(request)
    from .db import get_db
    from .services.db_repository import get_merchant_connection_status

    with get_db() as db:
        data = get_merchant_connection_status(db, user.get("email", ""))
    data["merchant_push_resolve_hint"] = MERCHANT_PUSH_RESOLVE_HINT
    data["gmc_merchant_id_env_set"] = _gmc_merchant_id_env_configured()
    return data


@app.post("/api/merchant/disconnect")
async def api_merchant_disconnect(request: Request):
    require_login_http(request)
    user = get_current_user(request)
    from .db import get_db
    from .services.db_repository import clear_google_merchant_oauth

    with get_db() as db:
        clear_google_merchant_oauth(db, user.get("email", ""))
    return JSONResponse({"ok": True})


@app.get("/api/merchant/accounts")
async def api_merchant_accounts(request: Request):
    """Numeric Merchant Center account ids this Google login can use (for multi-account setups)."""
    require_login_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from .db import get_db
    from .services.db_repository import get_user_by_email
    from .services import google_merchant as gmc

    with get_db() as db:
        row = get_user_by_email(db, email)
        if not row or not row.merchant_refresh_token:
            raise HTTPException(
                status_code=400,
                detail="Merchant Center not connected. Open Upload and connect Google Merchant Center first.",
            )
        refresh_token = row.merchant_refresh_token

    access_token = await gmc.get_access_token_from_refresh(refresh_token)
    if not access_token:
        raise HTTPException(status_code=502, detail="Could not refresh Google access token. Reconnect Merchant Center.")

    ids, err = await gmc.all_accessible_numeric_merchant_ids(access_token)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"merchant_ids": sorted(ids, key=int)}


@app.post("/api/merchant/select-account")
async def api_merchant_select_account(request: Request):
    """Save which Merchant Center account to use when multiple are linked (no server .env needed)."""
    require_login_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        body = await request.json()
    except Exception:
        body = {}
    raw = (body.get("merchant_id") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail='Missing "merchant_id" in JSON body.')

    from .db import get_db
    from .services.db_repository import get_user_by_email, save_google_merchant_oauth
    from .services import google_merchant as gmc

    with get_db() as db:
        row = get_user_by_email(db, email)
        if not row or not row.merchant_refresh_token:
            raise HTTPException(
                status_code=400,
                detail="Merchant Center not connected. Open Upload and connect Google Merchant Center first.",
            )
        refresh_token = row.merchant_refresh_token

    access_token = await gmc.get_access_token_from_refresh(refresh_token)
    if not access_token:
        raise HTTPException(status_code=502, detail="Could not refresh Google access token. Reconnect Merchant Center.")

    ok, err = await gmc.merchant_id_is_accessible(access_token, raw)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "Invalid merchant id.")
    mid = gmc.normalize_merchant_id(raw)
    if not mid:
        raise HTTPException(status_code=400, detail="merchant_id must be a numeric Merchant Center account id.")

    with get_db() as db:
        save_google_merchant_oauth(db, email, None, mid)
    return JSONResponse({"ok": True, "merchant_id": mid})


@app.post("/api/batches/{batch_id}/merchant-push")
async def api_batch_merchant_push(request: Request, batch_id: str):
    """Push optimized batch rows to the user's linked Google Merchant Center (Merchant API productInputs.insert)."""
    require_login_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    product_ids = payload.get("product_ids")
    if product_ids is not None:
        if not isinstance(product_ids, list):
            raise HTTPException(status_code=400, detail="product_ids must be a JSON array of strings.")
        if len(product_ids) == 0:
            raise HTTPException(
                status_code=400,
                detail="product_ids is empty. Select rows or omit product_ids to push the full batch.",
            )

    batch = storage.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")
    _ensure_batch_owner_from_batch(request, batch)

    from .db import get_db
    from .services.db_repository import get_user_by_email, save_google_merchant_oauth
    from .services import google_merchant as gmc

    with get_db() as db:
        row = get_user_by_email(db, email)
        if not row or not row.merchant_refresh_token:
            raise HTTPException(
                status_code=400,
                detail="Merchant Center not connected. Open Upload and connect Google Merchant Center first.",
            )
        refresh_token = row.merchant_refresh_token
        merchant_id = row.merchant_id

    access_token = await gmc.get_access_token_from_refresh(refresh_token)
    if not access_token:
        raise HTTPException(status_code=502, detail="Could not refresh Google access token. Reconnect Merchant Center.")

    # Built-in default or GMC_MERCHANT_ID in .env always wins over DB (fixes wrong id saved earlier).
    env_mid = gmc.effective_gmc_merchant_id_override()
    if env_mid.isdigit():
        merchant_id = env_mid

    if not merchant_id:
        merchant_id, resolve_hint = await gmc.resolve_merchant_account_id(
            access_token, preferred_merchant_id=row.merchant_id
        )
        if merchant_id:
            with get_db() as db:
                save_google_merchant_oauth(db, email, None, merchant_id)
        else:
            raise HTTPException(
                status_code=400,
                detail=resolve_hint
                or "Could not resolve Merchant Center account ID. Set GMC_MERCHANT_ID in .env to your numeric Merchant Center ID, or reconnect after creating a subaccount.",
            )
    elif env_mid.isdigit():
        with get_db() as db:
            save_google_merchant_oauth(db, email, None, merchant_id)

    if product_ids is not None:
        wanted = {str(x).strip() for x in product_ids if str(x).strip()}
        products = [r for r in batch.products if str(r.product.id).strip() in wanted]
    else:
        products = list(batch.products)

    if not products:
        raise HTTPException(
            status_code=400,
            detail="No matching products to push. Selected IDs do not match this batch, or the batch is empty.",
        )

    summary = await gmc.push_batch_products(access_token, merchant_id, products)
    summary["ok"] = summary["failed"] == 0
    if int(summary.get("inserted") or 0) > 0:
        storage.mark_batch_merchant_pushed(batch_id)
    return JSONResponse(summary)


def _admin_nav_links(active: str = "", user_role: str = "customer") -> str:
    """Generate admin-only nav links if user is admin."""
    if user_role != "admin":
        return ""
    links = [
        f'<a href="/admin/onboarding-analytics" class="nav-link{" active" if active == "onboarding-analytics" else ""}">Dashboard</a>',
        f'<a href="/admin/writter" class="nav-link{" active" if active == "writter" else ""}">Writter</a>',
        f'<a href="/settings" class="nav-link{" active" if active == "settings" else ""}">Settings</a>',
    ]
    return "".join(links)


HOMEPAGE_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{SEO_META_TITLE}</title>
    <meta name="description" content="{SEO_META_DESCRIPTION}" />
    <meta property="og:title" content="{SEO_OG_TITLE}" />
    <meta property="og:description" content="{SEO_OG_DESCRIPTION}" />
    <meta property="og:image" content="{SEO_OG_IMAGE}" />
    <meta property="og:site_name" content="{SEO_OG_SITE_NAME}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{SEO_OG_TITLE}" />
    <meta name="twitter:description" content="{SEO_OG_DESCRIPTION}" />
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{opacity:0;transition:opacity .28s ease}body.page-transition-out{opacity:0;pointer-events:none}</style>
    <link rel="stylesheet" href="/static/styles.css" />
    <style>
    html { scroll-behavior: smooth; }
    :root, [data-theme="dark"] { --hp-bg: #0B0F19; --hp-text: #E5E7EB; --hp-muted: #9ca3af; --hp-accent: #4F46E5; --hp-border: rgba(255,255,255,0.1); --hp-font: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
    [data-theme="light"] { --hp-bg: #f8fafc; --hp-text: #0f172a; --hp-muted: rgba(15,23,42,0.6); --hp-accent: #4F46E5; --hp-border: rgba(15,23,42,0.12); }

    .hp-body { font-family: var(--hp-font); background: var(--hp-bg); color: var(--hp-text); min-height: 100vh; overflow-x: hidden; position: relative; -webkit-font-smoothing: antialiased; }
    .hp-container { max-width: 1200px; width: 100%; margin: 0 auto; padding: 0 40px; box-sizing: border-box; }
    
    /* Grid overlay (hero-style blueprint feel) */
    .hp-grid-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 0; background-image: linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px); background-size: 48px 48px; mask-image: radial-gradient(ellipse 100% 80% at 50% 20%, black 30%, transparent 70%); }
    [data-theme="light"] .hp-grid-overlay { background-image: linear-gradient(rgba(15,23,42,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(15,23,42,0.04) 1px, transparent 1px); }
    /* Global stars background */
    .hp-stars { position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 0; overflow: hidden; }
    .hp-star { position: absolute; width: 2px; height: 2px; background: rgba(255,255,255,0.5); border-radius: 50%; animation: starDrift 30s ease-in-out infinite; }
    [data-theme="light"] .hp-star { background: rgba(15,23,42,0.25); }
    .hp-star::after { content: ''; position: absolute; top: -1px; left: -1px; width: 4px; height: 4px; background: radial-gradient(circle, rgba(255,255,255,0.4) 0%, transparent 70%); border-radius: 50%; }
    @keyframes starDrift { 0% { transform: translate(0, 0); } 25% { transform: translate(15px, -10px); } 50% { transform: translate(5px, -20px); } 75% { transform: translate(-10px, -8px); } 100% { transform: translate(0, 0); } }
    
    .hp-star:nth-child(1) { top: 8%; left: 15%; animation-delay: 0s; animation-duration: 30s; }
    .hp-star:nth-child(2) { top: 12%; left: 85%; animation-delay: 5s; animation-duration: 35s; }
    .hp-star:nth-child(3) { top: 25%; left: 92%; animation-delay: 3s; animation-duration: 28s; }
    .hp-star:nth-child(4) { top: 35%; left: 5%; animation-delay: 8s; animation-duration: 32s; }
    .hp-star:nth-child(5) { top: 45%; left: 78%; animation-delay: 2s; animation-duration: 38s; }
    .hp-star:nth-child(6) { top: 55%; left: 25%; animation-delay: 10s; animation-duration: 25s; }
    .hp-star:nth-child(7) { top: 65%; left: 95%; animation-delay: 6s; animation-duration: 33s; }
    .hp-star:nth-child(8) { top: 72%; left: 12%; animation-delay: 4s; animation-duration: 29s; }
    .hp-star:nth-child(9) { top: 82%; left: 68%; animation-delay: 12s; animation-duration: 36s; }
    .hp-star:nth-child(10) { top: 88%; left: 42%; animation-delay: 7s; animation-duration: 31s; }
    .hp-star:nth-child(11) { top: 18%; left: 55%; animation-delay: 9s; animation-duration: 27s; }
    .hp-star:nth-child(12) { top: 38%; left: 35%; animation-delay: 1s; animation-duration: 34s; }
    .hp-star:nth-child(13) { top: 58%; left: 8%; animation-delay: 11s; animation-duration: 26s; }
    .hp-star:nth-child(14) { top: 78%; left: 88%; animation-delay: 13s; animation-duration: 37s; }
    .hp-star:nth-child(15) { top: 92%; left: 22%; animation-delay: 0s; animation-duration: 30s; }
    
    /* Decorative background elements */
    .hp-bg-decor { position: absolute; pointer-events: none; z-index: 0; }
    .hp-bg-circle { border: 1px solid rgba(255,255,255,0.04); border-radius: 50%; }
    .hp-bg-circle-1 { width: 600px; height: 600px; top: -200px; right: -200px; }
    .hp-bg-circle-2 { width: 400px; height: 400px; top: 50%; left: -150px; }
    .hp-bg-circle-3 { width: 800px; height: 800px; bottom: -400px; right: -300px; border-style: dashed; border-color: rgba(255,255,255,0.03); }
    .hp-bg-line { background: linear-gradient(180deg, transparent, rgba(255,255,255,0.04), transparent); }
    .hp-bg-line-v { width: 1px; height: 300px; }
    .hp-bg-line-h { width: 300px; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.04), transparent); }
    .hp-bg-glow { border-radius: 50%; background: radial-gradient(circle, rgba(79,70,229,0.12) 0%, transparent 70%); }

    /* Navigation — full-width bar, content capped at 1200px (not ultra-wide stretch) */
    .hp-nav { position: fixed; top: 0; left: 0; right: 0; z-index: 1000; padding: 16px 0; background: rgba(0,0,0,0.85); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255,255,255,0.06); }
    [data-theme="light"] .hp-nav { background: rgba(248,250,252,0.95); border-bottom-color: rgba(15,23,42,0.08); }
    .hp-nav-inner { max-width: 1200px; width: 100%; margin: 0 auto; padding: 0 40px; box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
    .hp-nav-logo { flex-shrink: 0; position: relative; }
    .hp-nav-logo img { height: 32px; }
    .hp-nav-logo .logo-dark { display: none; filter: brightness(0) invert(1); }
    .hp-nav-logo .logo-light { display: block; filter: brightness(0) invert(1); }
    [data-theme="light"] .hp-nav-logo .logo-light { display: none; }
    [data-theme="light"] .hp-nav-logo .logo-dark { display: block; filter: none; }
    .hp-nav-links { display: flex; align-items: center; justify-content: center; gap: 28px; flex: 1; }
    .hp-nav-right { display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
    .hp-nav-link { color: var(--hp-muted); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }
    .hp-nav-link:hover { color: var(--hp-text); }
    .hp-theme-btn { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--hp-border); background: transparent; color: var(--hp-muted); cursor: pointer; font-size: 1rem; transition: all 0.2s; }
    .hp-theme-btn:hover { color: var(--hp-text); background: rgba(255,255,255,0.08); }
    [data-theme="light"] .hp-theme-btn:hover { background: rgba(15,23,42,0.06); }
    .hp-nav-cta { background: var(--hp-text); color: var(--hp-bg); padding: 10px 20px; border-radius: 6px; font-size: 0.85rem; font-weight: 500; text-decoration: none; transition: opacity 0.2s; }
    .hp-nav-cta:hover { opacity: 0.9; }

    @media (max-width: 1024px) {
        .hp-nav-links { display: none; }
        .hp-nav-right { gap: 12px; }
    }

    /* Hero — same max width as page content */
    .hp-hero { text-align: center; padding: 160px 40px 120px; position: relative; min-height: 600px; max-width: 1200px; margin-left: auto; margin-right: auto; box-sizing: border-box; overflow: hidden; background: var(--hp-bg); }
    .hp-badge { display: inline-block; color: var(--hp-accent); font-size: 0.75rem; font-weight: 600; margin-bottom: 28px; letter-spacing: 0.18em; text-transform: uppercase; transition: font-size 0.4s cubic-bezier(0.4, 0, 0.2, 1), margin 0.4s cubic-bezier(0.4, 0, 0.2, 1); }
    .hp-title { font-size: clamp(2.5rem, 6vw, 4rem); font-weight: 800; line-height: 1.05; margin-bottom: 24px; letter-spacing: -0.04em; position: relative; z-index: 2; transition: font-size 0.4s cubic-bezier(0.4, 0, 0.2, 1), margin 0.4s cubic-bezier(0.4, 0, 0.2, 1); }
    .hp-sub { font-size: 1.05rem; color: var(--hp-muted); max-width: 52ch; margin: 0 auto 40px; line-height: 1.6; font-weight: 400; position: relative; z-index: 2; transition: font-size 0.4s cubic-bezier(0.4, 0, 0.2, 1), margin 0.4s cubic-bezier(0.4, 0, 0.2, 1), line-height 0.4s cubic-bezier(0.4, 0, 0.2, 1); }
    /* Hero compresses when chat is open (has conversation) */
    .hp-hero:has(.hp-chat-wrap.has-conversation) .hp-badge { font-size: 0.91rem; margin-bottom: 20px; }
    .hp-hero:has(.hp-chat-wrap.has-conversation) .hp-title { font-size: clamp(1.75rem, 4.2vw, 2.8rem); margin-bottom: 17px; }
    .hp-hero:has(.hp-chat-wrap.has-conversation) .hp-sub { font-size: 0.91rem; margin-bottom: 28px; line-height: 1.5; }
    .hp-buttons { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; position: relative; z-index: 2; }
    .hp-btn { padding: 14px 28px; border-radius: 6px; font-size: 0.9rem; font-weight: 500; text-decoration: none; transition: all 0.3s ease; }
    .hp-btn-primary { background: var(--hp-text); color: var(--hp-bg); }
    .hp-btn-primary:hover { opacity: 0.9; transform: translateY(-2px); box-shadow: 0 10px 30px rgba(255,255,255,0.1); }
    .hp-btn-secondary { background: transparent; color: var(--hp-text); border: 1px solid var(--hp-border); }
    .hp-btn-secondary:hover { border-color: rgba(255,255,255,0.3); background: rgba(255,255,255,0.05); }

    /* Hero chat: anchor + spacer reserve layout when .hp-chat-wrap is fixed (avoids scroll flicker) */
    .hp-chat-anchor { position: relative; z-index: 10; max-width: min(680px, 100%); margin: 0 auto; width: 100%; }
    .hp-chat-spacer { display: none; width: 100%; margin: 0; padding: 0; border: 0; box-sizing: border-box; }
    .hp-chat-wrap { position: relative; z-index: 10; margin: 0; width: 100%; }
    .hp-chat-panel {
      background: rgba(30,30,35,0.95); border-radius: 999px; border: 1px solid rgba(255,255,255,0.08);
      display: flex; align-items: center; padding: 10px 16px 10px 20px; gap: 12px;
      transition: background 0.25s ease;
      position: relative; z-index: 11; width: 100%; min-width: 0; box-sizing: border-box;
    }
    .hp-chat-wrap.sticky .hp-chat-panel { box-shadow: 0 8px 32px rgba(0,0,0,0.4); }
    [data-theme="light"] .hp-chat-wrap.sticky .hp-chat-panel { box-shadow: 0 8px 32px rgba(15,23,42,0.15); }
    [data-theme="light"] .hp-chat-panel { background: rgba(241,245,249,0.98); border-color: rgba(15,23,42,0.12); }
    .hp-chat-panel.transparent { opacity: 0.78; }
    .hp-chat-panel.transparent:focus-within, .hp-chat-panel.transparent:hover { opacity: 1; }
    .hp-chat-wrap.sticky { position: fixed; top: var(--hp-sticky-top, 76px); left: 50%; transform: translateX(-50%); width: calc(100% - 48px); max-width: min(680px, calc(100% - 48px)); z-index: 999; }
    .hp-chat-plus { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; color: rgba(255,255,255,0.5); cursor: pointer; flex-shrink: 0; user-select: none; }
    [data-theme="light"] .hp-chat-plus { color: rgba(15,23,42,0.5); }
    .hp-chat-input-wrap { flex: 1; position: relative; min-width: 0; display: flex; align-items: center; }
    .hp-chat-input { flex: 1; background: none; border: none; font-size: 0.95rem; color: var(--hp-text); outline: none; min-width: 0; }
    .hp-chat-placeholder { position: absolute; left: 0; top: 0; bottom: 0; display: flex; align-items: center; font-size: 0.95rem; color: rgba(255,255,255,0.4); pointer-events: none; transition: opacity 0.35s ease; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
    [data-theme="light"] .hp-chat-placeholder { color: rgba(15,23,42,0.4); }
    .hp-chat-placeholder.hidden { opacity: 0; }
    .hp-chat-input::placeholder { color: transparent; }
    [data-theme="light"] .hp-chat-input { color: #0f172a; }
    .hp-chat-mic { display: none; }
    .hp-chat-send { width: 40px; height: 40px; border-radius: 50%; background: var(--hp-text); color: var(--hp-bg); border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: opacity 0.2s; }
    .hp-chat-send:hover { opacity: 0.9; }
    .hp-chat-send svg { width: 18px; height: 18px; }
    /* Transcript block: only visible once there is conversation */
    .hp-chat-log { display: none; margin-bottom: 16px; border-radius: 16px; padding: 16px 16px 12px; text-align: left;
      background: rgba(15, 15, 18, 0.72); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
      border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 8px 32px rgba(0,0,0,0.35); }
    [data-theme="light"] .hp-chat-log {
      background: rgba(255, 255, 255, 0.82); border-color: rgba(15,23,42,0.12); box-shadow: 0 8px 28px rgba(15,23,42,0.12); }
    .hp-chat-wrap.has-conversation .hp-chat-log { display: block; }
    /* Hero in viewport: full chat. Hero out: smooth hide chat block, keep only sticky input bar. */
    .hp-chat-wrap { display: flex; flex-direction: column; }
    .hp-chat-wrap.has-conversation .hp-chat-log {
      max-height: 380px; margin-bottom: 16px;
      transition: opacity 0.28s ease, max-height 0.3s ease, margin 0.28s ease, visibility 0.28s;
    }
    .hp-chat-wrap.has-conversation.collapsed-log .hp-chat-log {
      opacity: 0; visibility: hidden; max-height: 0; margin: 0; overflow: hidden; pointer-events: none;
    }
    .hp-chat-wrap.has-conversation.collapsed-log { margin-bottom: 0; }
    .hp-chat-wrap.sticky .hp-chat-log { box-shadow: 0 12px 40px rgba(0,0,0,0.45); }
    [data-theme="light"] .hp-chat-wrap.sticky .hp-chat-log { box-shadow: 0 12px 36px rgba(15,23,42,0.14); }
    .hp-chat-messages {
      max-height: 280px; overflow-y: auto; padding: 0 4px 4px; text-align: left;
      scrollbar-gutter: stable;
      scrollbar-width: thin;
      scrollbar-color: rgba(249, 115, 22, 0.55) rgba(255, 255, 255, 0.05);
    }
    .hp-chat-messages::-webkit-scrollbar { width: 7px; }
    .hp-chat-messages::-webkit-scrollbar-track {
      background: rgba(255, 255, 255, 0.04);
      border-radius: 100px;
      margin: 6px 0;
    }
    .hp-chat-messages::-webkit-scrollbar-thumb {
      border-radius: 100px;
      background: linear-gradient(180deg, rgba(251, 146, 60, 0.75) 0%, rgba(234, 88, 12, 0.5) 50%, rgba(180, 60, 10, 0.45) 100%);
      box-shadow: 0 0 10px rgba(249, 115, 22, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.2);
      border: 1px solid rgba(249, 115, 22, 0.25);
    }
    .hp-chat-messages::-webkit-scrollbar-thumb:hover {
      background: linear-gradient(180deg, rgba(253, 186, 116, 0.9) 0%, rgba(249, 115, 22, 0.75) 45%, rgba(220, 80, 15, 0.65) 100%);
      box-shadow: 0 0 18px rgba(249, 115, 22, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.28);
    }
    .hp-chat-messages::-webkit-scrollbar-button { display: none; height: 0; width: 0; }
    .hp-chat-messages::-webkit-scrollbar-corner { background: transparent; }
    [data-theme="light"] .hp-chat-messages {
      scrollbar-color: rgba(234, 88, 12, 0.65) rgba(15, 23, 42, 0.07);
    }
    [data-theme="light"] .hp-chat-messages::-webkit-scrollbar-track {
      background: rgba(15, 23, 42, 0.06);
    }
    [data-theme="light"] .hp-chat-messages::-webkit-scrollbar-thumb {
      background: linear-gradient(180deg, rgba(249, 115, 22, 0.85) 0%, rgba(234, 88, 12, 0.65) 100%);
      box-shadow: 0 0 8px rgba(249, 115, 22, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.35);
      border-color: rgba(234, 88, 12, 0.35);
    }
    [data-theme="light"] .hp-chat-messages::-webkit-scrollbar-thumb:hover {
      background: linear-gradient(180deg, rgba(251, 146, 60, 0.95) 0%, rgba(249, 115, 22, 0.8) 100%);
      box-shadow: 0 0 14px rgba(249, 115, 22, 0.35);
    }
    .hp-chat-log-footer { display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-top: 10px; padding-top: 12px;
      border-top: 1px solid rgba(255,255,255,0.08); }
    [data-theme="light"] .hp-chat-log-footer { border-top-color: rgba(15,23,42,0.08); }
    .hp-chat-hide { font-size: 0.8rem; font-weight: 500; padding: 8px 16px; border-radius: 999px; cursor: pointer;
      border: 1px solid rgba(255,255,255,0.22); background: rgba(255,255,255,0.08); color: var(--hp-text);
      transition: background 0.2s, border-color 0.2s, opacity 0.2s; }
    .hp-chat-hide:hover { background: rgba(255,255,255,0.14); border-color: rgba(255,255,255,0.35); }
    [data-theme="light"] .hp-chat-hide { border-color: rgba(15,23,42,0.2); background: rgba(15,23,42,0.06); }
    [data-theme="light"] .hp-chat-hide:hover { background: rgba(15,23,42,0.1); border-color: rgba(15,23,42,0.28); }
    .hp-chat-finish { font-size: 0.8rem; font-weight: 500; padding: 8px 16px; border-radius: 999px; cursor: pointer;
      border: 1px solid rgba(255,255,255,0.22); background: rgba(255,255,255,0.08); color: var(--hp-text);
      transition: background 0.2s, border-color 0.2s, opacity 0.2s; }
    .hp-chat-finish:hover { background: rgba(255,255,255,0.14); border-color: rgba(255,255,255,0.35); }
    [data-theme="light"] .hp-chat-finish { border-color: rgba(15,23,42,0.2); background: rgba(15,23,42,0.06); }
    [data-theme="light"] .hp-chat-finish:hover { background: rgba(15,23,42,0.1); border-color: rgba(15,23,42,0.28); }
    .hp-chat-msg { padding: 12px 16px; border-radius: 12px; margin-bottom: 10px; font-size: 0.9rem; line-height: 1.5; max-width: 90%; }
    .hp-chat-msg.user { background: rgba(255,255,255,0.1); margin-left: auto; }
    .hp-chat-msg.assistant { background: rgba(79,70,229,0.12); border: 1px solid rgba(79,70,229,0.2); }
    .hp-chat-status { padding: 12px 16px; border-radius: 12px; margin-bottom: 10px; font-size: 0.9rem; max-width: 90%; background: rgba(79,70,229,0.08); border: 1px solid rgba(79,70,229,0.15); color: var(--hp-muted); display: flex; align-items: center; gap: 8px; }
    .hp-chat-status-dots { display: inline-flex; gap: 4px; }
    .hp-chat-status-dots span { width: 6px; height: 6px; border-radius: 50%; background: rgba(79,70,229,0.6); animation: hp-status-dot 1.4s ease-in-out infinite both; }
    .hp-chat-status-dots span:nth-child(1) { animation-delay: 0s; }
    .hp-chat-status-dots span:nth-child(2) { animation-delay: 0.2s; }
    .hp-chat-status-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes hp-status-dot { 0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); } 40% { opacity: 1; transform: scale(1); } }
    [data-theme="light"] .hp-chat-status { background: rgba(79,70,229,0.06); border-color: rgba(79,70,229,0.12); color: rgba(15,23,42,0.6); }
    .hp-chat-upload-btn { display: inline-block; margin-top: 10px; padding: 8px 16px; border-radius: 999px; background: #4F46E5; color: #fff; font-size: 0.85rem; font-weight: 500; text-decoration: none; border: none; cursor: pointer; transition: opacity 0.2s; }
    .hp-chat-upload-btn:hover { opacity: 0.9; }
    [data-theme="light"] .hp-chat-msg.user { background: rgba(15,23,42,0.08); }
    [data-theme="light"] .hp-chat-msg.assistant { background: rgba(79,70,229,0.1); border-color: rgba(79,70,229,0.2); }

    /* Hero: abstract AI — neural lines, data nodes, animated grid (no space/planets) */
    .hp-hero-ai { position: absolute; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
    .hp-hero-ai-grid {
      position: absolute; inset: -20%; width: 140%; height: 140%;
      background-image:
        linear-gradient(rgba(79,70,229,0.07) 1px, transparent 1px),
        linear-gradient(90deg, rgba(79,70,229,0.07) 1px, transparent 1px),
        linear-gradient(rgba(167,139,250,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(167,139,250,0.04) 1px, transparent 1px);
      background-size: 56px 56px, 56px 56px, 14px 14px, 14px 14px;
      animation: hpHeroAiGridDrift 28s linear infinite;
      opacity: 0.85;
    }
    [data-theme="light"] .hp-hero-ai-grid {
      background-image:
        linear-gradient(rgba(15,23,42,0.06) 1px, transparent 1px),
        linear-gradient(90deg, rgba(15,23,42,0.06) 1px, transparent 1px),
        linear-gradient(rgba(79,70,229,0.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(79,70,229,0.05) 1px, transparent 1px);
      opacity: 0.9;
    }
    @keyframes hpHeroAiGridDrift { 0% { transform: translate(0, 0); } 100% { transform: translate(-56px, -56px); } }
    .hp-hero-ai-fade {
      position: absolute; inset: 0;
      background: radial-gradient(ellipse 85% 70% at 50% 35%, transparent 0%, var(--hp-bg) 72%);
      z-index: 1;
    }
    [data-theme="light"] .hp-hero-ai-fade { background: radial-gradient(ellipse 85% 70% at 50% 35%, transparent 0%, var(--hp-bg) 75%); }
    .hp-hero-ai-svg { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 0; opacity: 0.55; }
    [data-theme="light"] .hp-hero-ai-svg { opacity: 0.4; }
    .hp-ai-line { fill: none; stroke-linecap: round; stroke-linejoin: round; stroke-width: 0.32; vector-effect: non-scaling-stroke; }
    .hp-ai-line-a { stroke: rgba(79,70,229,0.45); stroke-dasharray: 8 14; animation: hpAiDash 4s linear infinite; }
    .hp-ai-line-b { stroke: rgba(167,139,250,0.35); stroke-dasharray: 6 12; animation: hpAiDash 5.5s linear infinite reverse; }
    .hp-ai-line-c { stroke: rgba(255,255,255,0.12); stroke-width: 0.25; stroke-dasharray: 4 10; animation: hpAiDash 7s linear infinite; }
    [data-theme="light"] .hp-ai-line-c { stroke: rgba(15,23,42,0.12); }
    @keyframes hpAiDash { to { stroke-dashoffset: -120; } }
    .hp-ai-node { animation: hpAiNodePulse 2.8s ease-in-out infinite; }
    .hp-ai-node:nth-child(odd) { animation-delay: 0.4s; }
    .hp-ai-node:nth-child(3n) { animation-delay: 0.9s; }
    @keyframes hpAiNodePulse { 0%, 100% { opacity: 0.35; } 50% { opacity: 1; } }
    [data-theme="light"] .hp-ai-node-muted { fill: rgba(15,23,42,0.4) !important; }
    @media (prefers-reduced-motion: reduce) {
      .hp-hero-ai-grid { animation: none; }
      .hp-ai-line-a, .hp-ai-line-b, .hp-ai-line-c { animation: none; }
      .hp-ai-node { animation: none; opacity: 0.7; }
    }

    /* Features — premium glassmorphism design */
    .hp-features { padding: 120px 0 140px; position: relative; overflow: hidden; background: linear-gradient(180deg, transparent 0%, rgba(79,70,229,0.02) 30%, rgba(167,139,250,0.02) 70%, transparent 100%); }
    .hp-features .hp-container { position: relative; z-index: 1; }
    .hp-features-bg { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
    .hp-features-bg .circle-1 { position: absolute; width: 600px; height: 600px; top: -200px; right: -200px; background: radial-gradient(circle, rgba(79,70,229,0.08) 0%, rgba(167,139,250,0.04) 40%, transparent 70%); border-radius: 50%; filter: blur(60px); }
    .hp-features-bg .circle-2 { position: absolute; width: 500px; height: 500px; bottom: -150px; left: -150px; background: radial-gradient(circle, rgba(59,130,246,0.06) 0%, transparent 60%); border-radius: 50%; filter: blur(80px); }
    .hp-features-bg .glow-1 { position: absolute; width: 400px; height: 400px; top: 30%; left: 50%; transform: translateX(-50%); background: radial-gradient(circle, rgba(79,70,229,0.04) 0%, transparent 70%); border-radius: 50%; filter: blur(100px); }
    .hp-features-header { text-align: center; margin-bottom: 56px; opacity: 0; transform: translateY(40px); transition: all 0.9s cubic-bezier(0.16, 1, 0.3, 1); }
    .hp-features-header.visible { opacity: 1; transform: translateY(0); }
    .hp-features-title { font-size: clamp(2rem, 4vw, 3rem); font-weight: 700; margin-bottom: 20px; letter-spacing: -0.04em; line-height: 1.15; background: linear-gradient(135deg, #fff 0%, rgba(255,255,255,0.85) 50%, rgba(255,255,255,0.7) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    [data-theme="light"] .hp-features-title { background: linear-gradient(135deg, #0f172a 0%, #334155 50%, #475569 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .hp-features-sub { color: var(--hp-muted); font-size: 1.08rem; font-weight: 400; letter-spacing: 0.01em; max-width: 42ch; margin: 0 auto; line-height: 1.65; }
    .hp-features-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; width: 100%; margin: 0 auto; }
    @media (max-width: 1024px) { .hp-features-grid { grid-template-columns: repeat(2, 1fr); gap: 24px; } }
    @media (max-width: 640px) { .hp-features-grid { grid-template-columns: 1fr; gap: 20px; } .hp-features { padding: 72px 0 88px; } }
    
    .hp-feature { position: relative; padding: 28px 22px; border-radius: 18px; overflow: hidden; opacity: 0; transform: translateY(36px); transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1); 
      background: linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%); 
      border: 1px solid rgba(255,255,255,0.08); 
      backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
      box-shadow: 0 4px 24px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.06); }
    .hp-feature.visible { opacity: 1; transform: translateY(0); }
    .hp-feature:hover { transform: translateY(-6px) scale(1.01); 
      border-color: rgba(79,70,229,0.25); 
      box-shadow: 0 24px 48px rgba(0,0,0,0.3), 0 0 0 1px rgba(79,70,229,0.15), inset 0 1px 0 rgba(255,255,255,0.08); 
      background: linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(79,70,229,0.04) 100%); }
    .hp-feature::before { content: ''; position: absolute; inset: 0; border-radius: inherit; padding: 1px; background: linear-gradient(135deg, rgba(255,255,255,0.12), transparent 50%, rgba(79,70,229,0.08)); -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); -webkit-mask-composite: xor; mask-composite: exclude; pointer-events: none; opacity: 0; transition: opacity 0.4s; }
    .hp-feature:hover::before { opacity: 1; }
    [data-theme="light"] .hp-feature { background: linear-gradient(135deg, rgba(255,255,255,0.95) 0%, rgba(248,250,252,0.9) 100%); border-color: rgba(15,23,42,0.08); box-shadow: 0 4px 24px rgba(15,23,42,0.06); }
    [data-theme="light"] .hp-feature:hover { border-color: rgba(79,70,229,0.3); box-shadow: 0 24px 48px rgba(15,23,42,0.1); }
    
    .hp-feature-visual { position: relative; height: 92px; margin-bottom: 20px; display: flex; align-items: center; justify-content: center; }
    .hp-feature-icon-wrap { position: relative; width: 64px; height: 64px; display: flex; align-items: center; justify-content: center; border-radius: 16px; z-index: 2; transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
      background: linear-gradient(145deg, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0.04) 100%);
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: 0 4px 12px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.1);
      color: rgba(255,255,255,0.95); }
    .hp-feature-icon-wrap svg { flex-shrink: 0; }
    .hp-feature:hover .hp-feature-icon-wrap { transform: scale(1.08); 
      box-shadow: 0 8px 24px rgba(79,70,229,0.2), inset 0 1px 0 rgba(255,255,255,0.15);
      background: linear-gradient(145deg, rgba(79,70,229,0.2) 0%, rgba(79,70,229,0.05) 100%);
      border-color: rgba(79,70,229,0.3);
      color: #fff; }
    [data-theme="light"] .hp-feature-icon-wrap { background: linear-gradient(145deg, #fff 0%, rgba(248,250,252,0.9) 100%); border-color: rgba(15,23,42,0.1); color: #0f172a; }
    [data-theme="light"] .hp-feature:hover .hp-feature-icon-wrap { color: #0f172a; }
    
    .hp-feature-dots { position: absolute; inset: 0; overflow: hidden; opacity: 0.5; }
    .hp-feature-dot { position: absolute; width: 4px; height: 4px; background: rgba(255,255,255,0.35); border-radius: 50%; }
    .hp-feature:nth-child(1) .hp-feature-dot:nth-child(1) { top: 15%; left: 20%; animation: float-dot 4s ease-in-out infinite; }
    .hp-feature:nth-child(1) .hp-feature-dot:nth-child(2) { top: 55%; left: 15%; animation: float-dot 5s ease-in-out infinite 0.5s; }
    .hp-feature:nth-child(1) .hp-feature-dot:nth-child(3) { top: 35%; right: 25%; animation: float-dot 4.5s ease-in-out infinite 1s; }
    .hp-feature:nth-child(1) .hp-feature-dot:nth-child(4) { top: 70%; right: 20%; animation: float-dot 5.5s ease-in-out infinite 0.3s; }
    .hp-feature:nth-child(2) .hp-feature-dot:nth-child(1) { top: 20%; left: 18%; animation: float-dot 4.2s ease-in-out infinite 0.2s; }
    .hp-feature:nth-child(2) .hp-feature-dot:nth-child(2) { top: 60%; left: 12%; animation: float-dot 3.8s ease-in-out infinite 0.8s; }
    .hp-feature:nth-child(2) .hp-feature-dot:nth-child(3) { top: 38%; right: 22%; animation: float-dot 4.6s ease-in-out infinite 0.4s; }
    .hp-feature:nth-child(2) .hp-feature-dot:nth-child(4) { top: 72%; right: 18%; animation: float-dot 5s ease-in-out infinite 1.2s; }
    .hp-feature:nth-child(odd) .hp-feature-dot { background: rgba(79,70,229,0.4); }
    @keyframes float-dot { 0%, 100% { transform: translateY(0) scale(1); opacity: 0.35; } 50% { transform: translateY(-10px) scale(1.3); opacity: 0.85; } }
    
    .hp-feature-ring { position: absolute; border: 1px solid rgba(255,255,255,0.06); border-radius: 50%; }
    .hp-feature-ring-1 { width: 100px; height: 100px; animation: pulse-ring 5s ease-in-out infinite; }
    .hp-feature-ring-2 { width: 150px; height: 150px; animation: pulse-ring 5s ease-in-out infinite 1.2s; }
    @keyframes pulse-ring { 0%, 100% { transform: scale(1); opacity: 0.2; } 50% { transform: scale(1.08); opacity: 0.5; } }
    
    .hp-feature-title { font-size: 1.1rem; font-weight: 700; margin-bottom: 12px; letter-spacing: -0.02em; color: var(--hp-text); line-height: 1.3; }
    .hp-feature-desc { font-size: 0.9rem; color: var(--hp-muted); line-height: 1.65; letter-spacing: 0.01em; }

    /* Feed structure showcase - Google Merchant (premium design) */
    .hp-feed-section { padding: 100px 0; border-top: 1px solid var(--hp-border); position: relative; overflow: hidden; }
    .hp-feed-section::before { content: ''; position: absolute; inset: 0; background: radial-gradient(ellipse 80% 50% at 50% 0%, rgba(79,70,229,0.06) 0%, transparent 60%); pointer-events: none; }
    .hp-feed-section .hp-container { position: relative; z-index: 1; }
    .hp-feed-header { text-align: center; margin-bottom: 44px; }
    .hp-feed-label { display: block; font-size: 0.8rem; font-weight: 500; letter-spacing: 0.12em; text-transform: uppercase; color: #22D3EE; margin-bottom: 16px; text-align: center; }
    .hp-feed-title { font-size: clamp(2rem, 4vw, 2.75rem); font-weight: 700; margin-bottom: 16px; letter-spacing: -0.04em; line-height: 1.2; padding: 0.08em 0; display: inline-block; background: linear-gradient(135deg, var(--hp-text) 0%, var(--hp-muted) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    [data-theme="light"] .hp-feed-title { background: linear-gradient(135deg, #0f172a 0%, #475569 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .hp-feed-sub { color: var(--hp-muted); font-size: 1.02rem; max-width: 46ch; margin: 0 auto; line-height: 1.6; }
    .hp-feed-block { position: relative; border-radius: 20px; overflow: hidden; opacity: 0; transform: translateY(32px) perspective(1000px) rotateX(2deg); transition: opacity 0.9s cubic-bezier(0.16, 1, 0.3, 1), transform 0.9s cubic-bezier(0.16, 1, 0.3, 1); }
    .hp-feed-section.visible .hp-feed-block { opacity: 1; transform: translateY(0) perspective(1000px) rotateX(0); }
    .hp-feed-block::before { content: ''; position: absolute; inset: -2px; border-radius: 22px; padding: 2px; background: linear-gradient(135deg, rgba(79,70,229,0.6), rgba(167,139,250,0.4), rgba(79,70,229,0.5)); -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); -webkit-mask-composite: xor; mask-composite: exclude; pointer-events: none; z-index: 2; animation: feedBorderGlow 4s ease-in-out infinite; }
    @keyframes feedBorderGlow { 0%, 100% { opacity: 0.85; } 50% { opacity: 1; } }
    .hp-feed-block-inner { position: relative; background: linear-gradient(165deg, rgba(15,15,18,0.95) 0%, rgba(8,8,10,0.98) 100%); backdrop-filter: blur(24px); border-radius: 18px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.4), 0 25px 50px -12px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.04); }
    [data-theme="light"] .hp-feed-block-inner { background: linear-gradient(165deg, rgba(255,255,255,0.9) 0%, rgba(248,250,252,0.95) 100%); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 25px 50px -12px rgba(0,0,0,0.1), inset 0 1px 0 rgba(255,255,255,0.8); }
    .hp-feed-window-bar { display: flex; align-items: center; gap: 12px; padding: 14px 20px; background: rgba(0,0,0,0.4); border-bottom: 1px solid rgba(255,255,255,0.06); }
    [data-theme="light"] .hp-feed-window-bar { background: rgba(15,23,42,0.04); border-bottom-color: rgba(15,23,42,0.08); }
    .hp-feed-dots { display: flex; gap: 8px; }
    .hp-feed-dot { width: 12px; height: 12px; border-radius: 50%; }
    .hp-feed-dot:nth-child(1) { background: #ff5f57; }
    .hp-feed-dot:nth-child(2) { background: #febc2e; }
    .hp-feed-dot:nth-child(3) { background: #28c840; }
    .hp-feed-filename { flex: 1; text-align: center; font-size: 0.8rem; font-weight: 500; color: var(--hp-muted); font-family: 'SF Mono', monospace; }
    .hp-feed-window-badge { padding: 4px 12px; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.05em; border-radius: 6px; background: linear-gradient(135deg, rgba(79,70,229,0.2), rgba(79,70,229,0.1)); color: #4F46E5; border: 1px solid rgba(79,70,229,0.3); }
    .hp-feed-scan { position: absolute; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, transparent, rgba(79,70,229,0.6), rgba(167,139,250,0.4), transparent); animation: feedScan 5s ease-in-out infinite; pointer-events: none; z-index: 1; filter: blur(1px); }
    @keyframes feedScan { 0% { top: 52px; opacity: 0; } 5% { opacity: 1; } 95% { opacity: 1; } 100% { top: calc(100% - 80px); opacity: 0; } }
    .hp-feed-table-wrap { overflow-x: auto; padding: 0; margin: 0; }
    .hp-feed-table-wrap::-webkit-scrollbar { height: 8px; }
    .hp-feed-table-wrap::-webkit-scrollbar-track { background: rgba(255,255,255,0.03); border-radius: 4px; }
    .hp-feed-table-wrap::-webkit-scrollbar-thumb { background: rgba(79,70,229,0.3); border-radius: 4px; }
    .hp-feed-table-wrap::-webkit-scrollbar-thumb:hover { background: rgba(79,70,229,0.5); }
    .hp-feed-table { width: 100%; min-width: 950px; border-collapse: separate; border-spacing: 0; font-size: 0.76rem; font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace; }
    .hp-feed-table th, .hp-feed-table td { padding: 12px 16px; text-align: left; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); position: relative; }
    .hp-feed-table th { background: linear-gradient(180deg, rgba(79,70,229,0.12) 0%, rgba(79,70,229,0.06) 100%); color: #22D3EE; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.68rem; border-bottom: 1px solid rgba(79,70,229,0.2); }
    [data-theme="light"] .hp-feed-table th { background: linear-gradient(180deg, rgba(79,70,229,0.15) 0%, rgba(79,70,229,0.08) 100%); color: #4338ca; border-bottom-color: rgba(79,70,229,0.25); }
    .hp-feed-table td { color: rgba(255,255,255,0.7); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-bottom: 1px solid rgba(255,255,255,0.04); }
    [data-theme="light"] .hp-feed-table td { color: rgba(15,23,42,0.8); border-bottom-color: rgba(15,23,42,0.06); }
    .hp-feed-table tbody tr:hover td { background: rgba(79,70,229,0.06); color: var(--hp-text); }
    [data-theme="light"] .hp-feed-table tbody tr:hover td { background: rgba(79,70,229,0.08); color: #0f172a; }
    .hp-feed-table th:hover { background: rgba(79,70,229,0.18); color: #67e8f9; }
    .hp-feed-table td:hover { background: rgba(79,70,229,0.1) !important; }
    .hp-feed-table .hp-feed-cell-id { color: #a78bfa; }
    .hp-feed-table .hp-feed-cell-title { color: #A78BFA; font-weight: 500; }
    .hp-feed-table .hp-feed-cell-price { color: #34d399; font-weight: 600; }
    .hp-feed-table .hp-feed-cell-brand { color: #60a5fa; }
    [data-theme="light"] .hp-feed-table .hp-feed-cell-id { color: #7c3aed; }
    [data-theme="light"] .hp-feed-table .hp-feed-cell-title { color: #6d28d9; }
    [data-theme="light"] .hp-feed-table .hp-feed-cell-price { color: #059669; }
    [data-theme="light"] .hp-feed-table .hp-feed-cell-brand { color: #2563eb; }
    .hp-feed-table tr { animation: feedRowReveal 0.6s cubic-bezier(0.16, 1, 0.3, 1) backwards; }
    .hp-feed-table thead tr { animation-delay: 0.15s; }
    .hp-feed-table tbody tr { animation-delay: 0.35s; }
    @keyframes feedRowReveal { from { opacity: 0; transform: translateX(-12px); } to { opacity: 1; transform: translateX(0); } }
    .hp-feed-footer { display: flex; align-items: center; justify-content: center; gap: 24px; flex-wrap: wrap; padding: 20px 24px; background: rgba(0,0,0,0.2); border-top: 1px solid rgba(255,255,255,0.06); }
    [data-theme="light"] .hp-feed-footer { background: rgba(15,23,42,0.03); border-top-color: rgba(15,23,42,0.08); }
    .hp-feed-badge { display: inline-flex; align-items: center; gap: 8px; padding: 8px 18px; font-size: 0.85rem; font-weight: 600; border-radius: 10px; background: linear-gradient(135deg, rgba(79,70,229,0.2), rgba(79,70,229,0.1)); color: #4F46E5; border: 1px solid rgba(79,70,229,0.3); }
    .hp-feed-badge::before { content: '✓'; font-weight: 700; color: #34d399; }
    [data-theme="light"] .hp-feed-badge { background: linear-gradient(135deg, rgba(79,70,229,0.15), rgba(79,70,229,0.08)); color: #4338ca; border-color: rgba(79,70,229,0.25); }
    .hp-feed-meta { font-size: 0.78rem; color: var(--hp-muted); }
    @media (max-width: 768px) { .hp-feed-section { padding: 72px 0; } .hp-feed-table { font-size: 0.7rem; min-width: 750px; } .hp-feed-block::before { animation: none; } }

    /* How it works */
    .hp-steps { padding: 88px 0; text-align: center; position: relative; overflow: hidden; }
    .hp-steps-bg { position: absolute; inset: 0; pointer-events: none; }
    .hp-steps-bg .line-1 { position: absolute; width: 1px; height: 200px; left: 20%; top: 0; background: linear-gradient(180deg, transparent, rgba(255,255,255,0.05), transparent); }
    .hp-steps-bg .line-2 { position: absolute; width: 1px; height: 250px; right: 15%; bottom: 0; background: linear-gradient(180deg, transparent, rgba(255,255,255,0.04), transparent); }
    .hp-steps-bg .circle-1 { position: absolute; width: 200px; height: 200px; border: 1px solid rgba(255,255,255,0.03); border-radius: 50%; left: 5%; top: 30%; }
    .hp-steps .hp-container { position: relative; z-index: 1; }
    .hp-steps-title { font-size: 2.2rem; font-weight: 600; margin-bottom: 12px; letter-spacing: -0.02em; }
    .hp-steps-sub { color: var(--hp-muted); font-size: 0.98rem; margin-bottom: 48px; }
    .hp-steps-grid { display: flex; justify-content: center; gap: 40px; flex-wrap: wrap; width: 100%; margin: 0 auto; }
    .hp-step { text-align: center; max-width: 240px; }
    .hp-step-num { width: 48px; height: 48px; border: 2px solid var(--hp-border); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.1rem; font-weight: 600; margin: 0 auto 20px; transition: border-color 0.3s, background 0.3s; }
    .hp-step:hover .hp-step-num { border-color: rgba(79,70,229,0.5); background: rgba(79,70,229,0.12); }
    [data-theme="light"] .hp-step:hover .hp-step-num { border-color: rgba(15,23,42,0.4); background: rgba(15,23,42,0.06); }
    .hp-step-title { font-size: 1rem; font-weight: 600; margin-bottom: 8px; }
    .hp-step-desc { font-size: 0.85rem; color: var(--hp-muted); line-height: 1.5; }

    /* CTA */
    .hp-cta { padding: 88px 0; text-align: center; border-top: 1px solid var(--hp-border); position: relative; overflow: hidden; }
    .hp-cta-bg { position: absolute; inset: 0; pointer-events: none; }
    .hp-cta-bg .circle-1 { position: absolute; width: 600px; height: 600px; border: 1px dashed rgba(255,255,255,0.03); border-radius: 50%; left: 50%; top: 50%; transform: translate(-50%, -50%); }
    .hp-cta-bg .circle-2 { position: absolute; width: 400px; height: 400px; border: 1px solid rgba(255,255,255,0.04); border-radius: 50%; left: 50%; top: 50%; transform: translate(-50%, -50%); }
    .hp-cta-bg .glow { position: absolute; width: 300px; height: 300px; background: radial-gradient(circle, rgba(34,211,238,0.1) 0%, transparent 70%); border-radius: 50%; left: 50%; top: 50%; transform: translate(-50%, -50%); }
    .hp-cta .hp-container { position: relative; z-index: 1; }
    .hp-cta-title { font-size: 2rem; font-weight: 600; margin-bottom: 16px; letter-spacing: -0.02em; }
    .hp-cta-sub { color: var(--hp-muted); font-size: 1rem; margin-bottom: 32px; }

    /* Footer */
    .hp-footer { max-width: 1200px; margin: 0 auto; padding: 28px 40px; text-align: center; font-size: 0.82rem; color: var(--hp-muted); border-top: 1px solid var(--hp-border); box-sizing: border-box; }
    .hp-footer a { color: var(--hp-muted); text-decoration: none; }
    .hp-footer a:hover { color: var(--hp-fg); text-decoration: underline; }

    /* Back to top button */
    .back-to-top { position: fixed; bottom: 32px; right: 32px; width: 48px; height: 48px; border-radius: 50%; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15); color: var(--hp-text); font-size: 1.2rem; cursor: pointer; opacity: 0; visibility: hidden; transform: translateY(20px); transition: all 0.3s ease; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(10px); z-index: 999; }
    .back-to-top:hover { background: rgba(255,255,255,0.2); border-color: rgba(255,255,255,0.3); transform: translateY(-2px); }
    [data-theme="light"] .back-to-top { background: rgba(15,23,42,0.08); border-color: rgba(15,23,42,0.15); }
    [data-theme="light"] .back-to-top:hover { background: rgba(15,23,42,0.15); border-color: rgba(15,23,42,0.25); }
    .back-to-top.visible { opacity: 1; visibility: visible; transform: translateY(0); }

    @media (max-width: 1024px) {
        .hp-hero { display: flex; flex-direction: column; }
        .hp-badge { order: 1; margin-bottom: 22px; }
        .hp-title { order: 2; line-height: 1.15; margin-bottom: 22px; }
        .hp-sub { order: 3; line-height: 1.65; }
        .hp-chat-anchor { order: 5; margin-top: 20px; }
    }
    @media (max-width: 768px) {
        .hp-nav { padding: 16px 0; }
        .hp-nav-inner { padding: 0 24px; }
        .hp-hero { padding: 120px 20px 60px; min-height: auto; display: flex; flex-direction: column; }
        .hp-badge { order: 1; margin-bottom: 20px; }
        .hp-title { order: 2; margin-bottom: 20px; font-size: clamp(1.75rem, 5vw, 2.25rem); line-height: 1.2; }
        .hp-sub { order: 3; margin-bottom: 28px; font-size: 0.95rem; margin-top: 0; line-height: 1.65; }
        .hp-hero:has(.hp-chat-wrap.has-conversation) .hp-badge { font-size: 0.84rem; margin-bottom: 14px; }
        .hp-hero:has(.hp-chat-wrap.has-conversation) .hp-title { font-size: clamp(1.26rem, 3.5vw, 1.68rem); margin-bottom: 14px; line-height: 1.2; }
        .hp-hero:has(.hp-chat-wrap.has-conversation) .hp-sub { font-size: 0.77rem; margin-bottom: 20px; margin-top: 0; line-height: 1.55; }
        .hp-hero-ai-svg { opacity: 0.42; }
        .hp-chat-anchor { order: 5; margin-top: 12px; padding: 0 4px; }
        .hp-chat-wrap.sticky { width: calc(100% - 24px); }
        .hp-chat-panel { padding: 8px 12px 8px 16px; }
        .hp-chat-messages { max-height: 200px; }
        .hp-container { padding: 0 24px; }
        .hp-features, .hp-steps, .hp-cta { padding: 56px 0; }
        .hp-footer { padding: 24px 24px; }
    }
    </style>
</head>
<body class="hp-body">
""" + GTM_BODY + """
    <div class="hp-grid-overlay" aria-hidden="true"></div>
    <div class="hp-stars">
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
    </div>
    <nav class="hp-nav">
        <div class="hp-nav-inner">
        <a href="/" class="hp-nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="hp-nav-links">
            <a href="/presentation" class="hp-nav-link">Features</a>
            <a href="#feed-structure" class="hp-nav-link">Feed Structure</a>
            <a href="#how-it-works" class="hp-nav-link">How it works</a>
            <a href="/contact" class="hp-nav-link">Contact us</a>
        </div>
        <div class="hp-nav-right">
            <button type="button" class="hp-theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/login" class="hp-nav-cta">Get Started</a>
        </div>
        </div>
    </nav>

    <section class="hp-hero">
        <div class="hp-hero-ai" aria-hidden="true">
            <div class="hp-hero-ai-grid"></div>
            <svg class="hp-hero-ai-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">
                <path class="hp-ai-line hp-ai-line-a" d="M0 38 L14 34 L22 46 L36 30 L44 52 L58 36 L68 50 L82 44 L100 40" />
                <path class="hp-ai-line hp-ai-line-a" d="M4 58 L20 62 L32 54 L46 68 L60 56 L74 64 L96 60" />
                <path class="hp-ai-line hp-ai-line-b" d="M8 22 L26 18 L34 28 L50 14 L64 26 L78 16 L92 24" />
                <path class="hp-ai-line hp-ai-line-b" d="M12 72 L28 78 L40 66 L54 80 L70 72 L88 76" />
                <path class="hp-ai-line hp-ai-line-c" d="M18 8 L38 12 L52 4 L70 10 L88 6" />
                <path class="hp-ai-line hp-ai-line-c" d="M6 88 L24 92 L42 84 L58 94 L78 88" />
                <path class="hp-ai-line hp-ai-line-c" d="M90 70 L96 82 L100 96" />
                <circle class="hp-ai-node" cx="14" cy="34" r="0.85" fill="#4F46E5" />
                <circle class="hp-ai-node" cx="36" cy="30" r="0.75" fill="#4F46E5" />
                <circle class="hp-ai-node" cx="58" cy="36" r="0.8" fill="#4F46E5" />
                <circle class="hp-ai-node" cx="26" cy="18" r="0.7" fill="#A78BFA" />
                <circle class="hp-ai-node" cx="50" cy="14" r="0.65" fill="#A78BFA" />
                <circle class="hp-ai-node" cx="32" cy="54" r="0.72" fill="#A78BFA" />
                <circle class="hp-ai-node" cx="60" cy="56" r="0.68" fill="#4F46E5" />
                <circle class="hp-ai-node" cx="40" cy="66" r="0.7" fill="#4F46E5" />
                <circle class="hp-ai-node" cx="74" cy="64" r="0.75" fill="#A78BFA" />
                <circle class="hp-ai-node hp-ai-node-muted" cx="18" cy="8" r="0.55" fill="rgba(255,255,255,0.5)" />
                <circle class="hp-ai-node hp-ai-node-muted" cx="52" cy="4" r="0.5" fill="rgba(255,255,255,0.45)" />
                <circle class="hp-ai-node hp-ai-node-muted" cx="88" cy="6" r="0.55" fill="rgba(255,255,255,0.4)" />
                <circle class="hp-ai-node hp-ai-node-muted" cx="42" cy="84" r="0.6" fill="rgba(255,255,255,0.35)" />
            </svg>
            <div class="hp-hero-ai-fade"></div>
        </div>

        <div class="hp-badge">AI-Powered E-commerce</div>
        <h1 class="hp-title">Optimize Every Product<br/>for Maximum Visibility</h1>
        <p class="hp-sub">
            AI-powered optimization for your product titles and descriptions. Boost search rankings, increase clicks, and drive more sales.
        </p>
        <div class="hp-chat-anchor" id="hpChatAnchor">
        <div class="hp-chat-spacer" id="hpChatSpacer" aria-hidden="true"></div>
        <div class="hp-chat-wrap" id="hpChatWrap">
            <div class="hp-chat-log" id="hpChatLog" aria-live="polite">
                <div class="hp-chat-messages" id="hpChatMessages"></div>
                <div class="hp-chat-log-footer">
                    <button type="button" class="hp-chat-hide" id="hpChatHide" title="Hide chat">Hide</button>
                    <button type="button" class="hp-chat-finish" id="hpChatFinish" title="Clear conversation">Finish chat</button>
                </div>
            </div>
            <div class="hp-chat-panel" id="hpChatPanel">
                <input type="file" id="hpChatFileInput" accept=".csv,text/csv,application/vnd.ms-excel" style="display:none" />
                <span class="hp-chat-plus" title="Upload file" id="hpChatPlus" role="button" tabindex="0">+</span>
                <div class="hp-chat-input-wrap">
                    <input type="text" class="hp-chat-input" id="hpChatInput" placeholder="Ask about your product feed" autocomplete="off" />
                    <span class="hp-chat-placeholder" id="hpChatPlaceholder">Ask about your product feed</span>
                </div>
                <span class="hp-chat-mic" title="Voice (coming soon)" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg></span>
                <button type="button" class="hp-chat-send" id="hpChatSend" title="Send" aria-label="Send message"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="14" width="3" height="6" rx="1"/><rect x="10" y="10" width="3" height="10" rx="1"/><rect x="16" y="6" width="3" height="14" rx="1"/></svg></button>
            </div>
        </div>
        </div>
    </section>

    <section class="hp-features" id="features">
        <div class="hp-features-bg">
            <div class="hp-bg-circle circle-1"></div>
            <div class="hp-bg-circle circle-2"></div>
            <div class="glow-1"></div>
        </div>
        <div class="hp-container">
            <div class="hp-features-header">
                <h2 class="hp-features-title">Complete feed optimization platform</h2>
                <p class="hp-features-sub">Everything you need to transform your product content</p>
            </div>
            <div class="hp-features-grid">
            <div class="hp-feature">
                <div class="hp-feature-visual">
                    <div class="hp-feature-dots"><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span></div>
                    <div class="hp-feature-ring hp-feature-ring-1"></div>
                    <div class="hp-feature-ring hp-feature-ring-2"></div>
                    <div class="hp-feature-icon-wrap"><svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg></div>
                </div>
                <div class="hp-feature-title">SEO-Optimized Titles</div>
                <div class="hp-feature-desc">AI expands short titles with relevant keywords and search phrases using proven e-commerce patterns.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-visual">
                    <div class="hp-feature-dots"><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span></div>
                    <div class="hp-feature-ring hp-feature-ring-1"></div>
                    <div class="hp-feature-ring hp-feature-ring-2"></div>
                    <div class="hp-feature-icon-wrap"><svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" x2="8" y1="13" y2="13"/><line x1="16" x2="8" y1="17" y2="17"/><line x1="10" x2="8" y1="9" y2="9"/></svg></div>
                </div>
                <div class="hp-feature-title">Compelling Descriptions</div>
                <div class="hp-feature-desc">Generate conversion-focused descriptions emphasizing benefits and features.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-visual">
                    <div class="hp-feature-dots"><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span></div>
                    <div class="hp-feature-ring hp-feature-ring-1"></div>
                    <div class="hp-feature-ring hp-feature-ring-2"></div>
                    <div class="hp-feature-icon-wrap"><svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/><path d="M2 12h20"/></svg></div>
                </div>
                <div class="hp-feature-title">Multi-Language Translation</div>
                <div class="hp-feature-desc">Translate optimized content to German, Swedish, French, Spanish, Polish, and more.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-visual">
                    <div class="hp-feature-dots"><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span></div>
                    <div class="hp-feature-ring hp-feature-ring-1"></div>
                    <div class="hp-feature-ring hp-feature-ring-2"></div>
                    <div class="hp-feature-icon-wrap"><svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg></div>
                </div>
                <div class="hp-feature-title">Quality Scoring</div>
                <div class="hp-feature-desc">Each optimization gets a quality score (1–100) so you see the improvement level.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-visual">
                    <div class="hp-feature-dots"><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span></div>
                    <div class="hp-feature-ring hp-feature-ring-1"></div>
                    <div class="hp-feature-ring hp-feature-ring-2"></div>
                    <div class="hp-feature-icon-wrap"><svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/><line x1="1" x2="7" y1="14" y2="14"/><line x1="9" x2="15" y1="8" y2="8"/><line x1="17" x2="23" y1="16" y2="16"/></svg></div>
                </div>
                <div class="hp-feature-title">Custom Prompts</div>
                <div class="hp-feature-desc">Customize AI prompts to match your brand voice and SEO strategy.</div>
            </div>
            <div class="hp-feature">
                <div class="hp-feature-visual">
                    <div class="hp-feature-dots"><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span><span class="hp-feature-dot"></span></div>
                    <div class="hp-feature-ring hp-feature-ring-1"></div>
                    <div class="hp-feature-ring hp-feature-ring-2"></div>
                    <div class="hp-feature-icon-wrap"><svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg></div>
                </div>
                <div class="hp-feature-title">CSV Import/Export</div>
                <div class="hp-feature-desc">Upload your feed as CSV, review results, and export optimized data.</div>
            </div>
            </div>
        </div>
    </section>

    <section class="hp-feed-section" id="feed-structure">
        <div class="hp-container">
            <div class="hp-feed-header">
                <span class="hp-feed-label">Feed Structure</span>
                <h2 class="hp-feed-title">Perfectly structured for Google Merchant</h2>
                <p class="hp-feed-sub">We map and optimize your feed according to Google product data specification</p>
            </div>
            <div class="hp-feed-block">
                <div class="hp-feed-block-inner">
                    <div class="hp-feed-window-bar">
                        <div class="hp-feed-dots"><span class="hp-feed-dot"></span><span class="hp-feed-dot"></span><span class="hp-feed-dot"></span></div>
                        <span class="hp-feed-filename">product_feed.csv</span>
                        <span class="hp-feed-window-badge">CSV</span>
                    </div>
                    <div class="hp-feed-scan"></div>
                    <div class="hp-feed-table-wrap">
                        <table class="hp-feed-table">
                            <thead>
                                <tr>
                                    <th>id</th>
                                    <th>title</th>
                                    <th>description</th>
                                    <th>link</th>
                                    <th>image_link</th>
                                    <th>availability</th>
                                    <th>price</th>
                                    <th>brand</th>
                                    <th>gtin</th>
                                    <th>condition</th>
                                    <th>google_product_category</th>
                                    <th>product_type</th>
                                    <th>color</th>
                                    <th>material</th>
                                    <th>size</th>
                                    <th>age_group</th>
                                    <th>gender</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td class="hp-feed-cell-id" title="12345">12345</td>
                                    <td class="hp-feed-cell-title" title="IKEA Wooden Dining Chair Black Modern Kitchen">IKEA Wooden Dining Chair Black Modern Kitchen</td>
                                    <td title="Modern wooden dining chair in black color. Made from solid wood. Ideal for kitchen, dining room or office use. Durable, ergonomic and stylish design.">Modern wooden dining chair in black color. Made from solid wood&hellip;</td>
                                    <td title="https://example.com/product/12345">example.com/product/12345</td>
                                    <td title="https://example.com/images/12345.jpg">example.com/images/12345.jpg</td>
                                    <td>in_stock</td>
                                    <td class="hp-feed-cell-price">79.99 USD</td>
                                    <td class="hp-feed-cell-brand">IKEA</td>
                                    <td>1234567890123</td>
                                    <td>new</td>
                                    <td title="Furniture > Chairs">Furniture &gt; Chairs</td>
                                    <td>Dining Chairs</td>
                                    <td>black</td>
                                    <td>wood</td>
                                    <td>standard</td>
                                    <td>adult</td>
                                    <td>unisex</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <div class="hp-feed-footer">
                        <span class="hp-feed-badge">Ready for Google Merchant Center</span>
                        <span class="hp-feed-meta">17 columns &middot; 1 sample row</span>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="hp-steps" id="how-it-works">
        <div class="hp-steps-bg">
            <div class="line-1"></div>
            <div class="line-2"></div>
            <div class="circle-1"></div>
        </div>
        <div class="hp-container">
            <h2 class="hp-steps-title">How it works</h2>
            <p class="hp-steps-sub">Three simple steps to better product content</p>
            <div class="hp-steps-grid">
                <div class="hp-step">
                    <div class="hp-step-num">1</div>
                    <div class="hp-step-title">Upload CSV</div>
                    <div class="hp-step-desc">Drag your feed file and map columns to standard fields.</div>
                </div>
                <div class="hp-step">
                    <div class="hp-step-num">2</div>
                    <div class="hp-step-title">AI optimizes content</div>
                    <div class="hp-step-desc">Our AI analyzes each product and generates improved titles and descriptions.</div>
                </div>
                <div class="hp-step">
                    <div class="hp-step-num">3</div>
                    <div class="hp-step-title">Review & export</div>
                    <div class="hp-step-desc">Review results, regenerate if needed, then download your optimized feed.</div>
                </div>
            </div>
        </div>
    </section>

    <section class="hp-cta">
        <div class="hp-cta-bg">
            <div class="circle-1"></div>
            <div class="circle-2"></div>
            <div class="glow"></div>
        </div>
        <div class="hp-container">
            <h2 class="hp-cta-title">Ready to optimize your product feed?</h2>
            <p class="hp-cta-sub">Start with a free trial — no API key needed for demo mode.</p>
            <a href="/login" class="hp-btn hp-btn-primary">Get Started Free</a>
        </div>
    </section>

    <footer class="hp-footer">
        &copy; 2026 Cartozo.ai - AI-powered product feed optimization &middot; Powered by <a href="https://zanzarra.com/" target="_blank" rel="noopener noreferrer">Zanzarra</a>
    </footer>

    <button class="back-to-top" id="backToTop" onclick="window.scrollTo({top:0,behavior:'smooth'})" title="Back to top">
        &#8593;
    </button>

    <script>
    const btn = document.getElementById('backToTop');
    
    // Theme toggle
    const themeToggle = document.getElementById('themeToggle');
    const THEME_KEY = 'hp-theme';
    function getTheme() { return localStorage.getItem(THEME_KEY) || 'dark'; }
    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem(THEME_KEY, theme);
        themeToggle.textContent = theme === 'dark' ? '\u2600' : '\u263E';
        themeToggle.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    }
    if (themeToggle) {
        setTheme(getTheme());
        themeToggle.addEventListener('click', () => setTheme(getTheme() === 'dark' ? 'light' : 'dark'));
    }
    
    // Scroll reveal for features
    const featuresHeader = document.querySelector('.hp-features-header');
    const featureCards = document.querySelectorAll('.hp-feature');
    
    const observerOptions = {
        threshold: 0.15,
        rootMargin: '0px 0px -50px 0px'
    };
    
    const revealObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                
                // Stagger animation for feature cards
                if (entry.target.classList.contains('hp-features-header')) {
                    featureCards.forEach((card, i) => {
                        setTimeout(() => card.classList.add('visible'), 150 + i * 100);
                    });
                }
            }
        });
    }, observerOptions);
    
    if (featuresHeader) revealObserver.observe(featuresHeader);
    featureCards.forEach(card => revealObserver.observe(card));
    
    const feedSection = document.querySelector('.hp-feed-section');
    if (feedSection) revealObserver.observe(feedSection);
    
    // Back to top button
    window.addEventListener('scroll', () => {
        if (window.scrollY > 400) {
            btn.classList.add('visible');
        } else {
            btn.classList.remove('visible');
        }
    });

    // Hero chat (original): messages above bar; sticky under nav + semi-transparent until click/focus
    (function() {
        const chatWrap = document.getElementById('hpChatWrap');
        const chatPanel = document.getElementById('hpChatPanel');
        const chatInput = document.getElementById('hpChatInput');
        const chatSend = document.getElementById('hpChatSend');
        const chatMessages = document.getElementById('hpChatMessages');
        const chatPlus = document.getElementById('hpChatPlus');
        const chatFinish = document.getElementById('hpChatFinish');
        const chatSpacer = document.getElementById('hpChatSpacer');
        const chatAnchor = document.getElementById('hpChatAnchor');
        const navEl = document.querySelector('.hp-nav');
        if (!chatWrap || !chatPanel || !chatInput || !chatSend || !chatMessages || !chatSpacer || !chatAnchor) return;

        var placeholders = [
            'Ask about your product feed',
            'Upload or describe your feed',
            'Product feed optimization',
            'Get help with your feed',
            'Upload CSV or ask a question'
        ];
        var phIdx = 0;
        var phEl = document.getElementById('hpChatPlaceholder');
        function updatePlaceholder() {
            if (!phEl) return;
            var isVisible = !phEl.classList.contains('hidden');
            if (!isVisible) {
                phIdx = (phIdx + 1) % placeholders.length;
                phEl.textContent = placeholders[phIdx];
                return;
            }
            phEl.classList.add('hidden');
            phEl.addEventListener('transitionend', function onEnd() {
                phEl.removeEventListener('transitionend', onEnd);
                phIdx = (phIdx + 1) % placeholders.length;
                phEl.textContent = placeholders[phIdx];
                phEl.classList.remove('hidden');
            }, { once: true });
        }
        setInterval(updatePlaceholder, 3000);
        function syncPlaceholderVisibility() {
            if (phEl) phEl.classList.toggle('hidden', !!(chatInput.value || document.activeElement === chatInput));
        }
        chatInput.addEventListener('input', syncPlaceholderVisibility);
        chatInput.addEventListener('focus', syncPlaceholderVisibility);
        chatInput.addEventListener('blur', syncPlaceholderVisibility);

        let chatSessionId = localStorage.getItem('hp-chat-session') || '';
        var STICK_HYST = 100;
        var scrollStickyRaf = null;
        var heroInViewport = true;
        var HIDE_SCROLL_Y = 280;
        var SHOW_SCROLL_Y = 200;

        function measureNavHeight() {
            return navEl ? Math.ceil(navEl.getBoundingClientRect().height) : 72;
        }

        function updateStickyTopVar() {
            var nh = measureNavHeight();
            document.documentElement.style.setProperty('--hp-sticky-top', (nh + 4) + 'px');
            return nh;
        }

        function updatePanelTransparency() {
            var sticky = chatWrap.classList.contains('sticky');
            if (!sticky) {
                chatPanel.classList.remove('transparent');
                return;
            }
            if (chatPanel.matches(':focus-within')) {
                chatPanel.classList.remove('transparent');
            } else {
                chatPanel.classList.add('transparent');
            }
        }

        var forceShowForTyping = false;
        function updateLogVisibility() {
            var has = chatMessages.children.length > 0;
            if (!has) {
                chatWrap.classList.remove('collapsed-log');
                return;
            }
            var sy = window.scrollY;
            if (forceShowForTyping) {
                chatWrap.classList.remove('collapsed-log');
                return;
            }
            if (sy >= HIDE_SCROLL_Y) {
                chatWrap.classList.add('collapsed-log');
                return;
            }
            if (sy < SHOW_SCROLL_Y) {
                chatWrap.classList.remove('collapsed-log');
                return;
            }
            if (heroInViewport) {
                chatWrap.classList.remove('collapsed-log');
            } else {
                chatWrap.classList.add('collapsed-log');
            }
        }

        function syncSpacerHeight() {
            if (chatWrap.classList.contains('sticky')) {
                chatSpacer.style.height = Math.ceil(chatWrap.getBoundingClientRect().height) + 'px';
            }
        }

        function syncChrome() {
            updateLogVisibility();
            updatePanelTransparency();
            syncSpacerHeight();
        }

        function scheduleSyncChrome() {
            requestAnimationFrame(syncChrome);
        }

        function syncConversationUI() {
            var has = chatMessages.children.length > 0;
            chatWrap.classList.toggle('has-conversation', has);
            scheduleSyncChrome();
        }

        function clearConversation() {
            chatSessionId = '';
            localStorage.removeItem('hp-chat-session');
            chatMessages.innerHTML = '';
            syncConversationUI();
        }

        function addMsg(role, content) {
            const div = document.createElement('div');
            div.className = 'hp-chat-msg ' + role;
            div.textContent = content;
            chatMessages.appendChild(div);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            syncConversationUI();
        }

        function addMsgWithButton(role, content, buttonText, buttonHref) {
            const div = document.createElement('div');
            div.className = 'hp-chat-msg ' + role;
            div.innerHTML = content + ' <a href="' + buttonHref + '" class="hp-chat-upload-btn">' + buttonText + '</a>';
            chatMessages.appendChild(div);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            syncConversationUI();
        }

        function addStatusIndicator() {
            const div = document.createElement('div');
            div.className = 'hp-chat-status';
            div.id = 'hpChatStatus';
            div.innerHTML = '<span class="hp-chat-status-text">Thinking</span><span class="hp-chat-status-dots"><span></span><span></span><span></span></span>';
            chatMessages.appendChild(div);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            syncConversationUI();
            return div;
        }

        function removeStatusIndicator() {
            const el = document.getElementById('hpChatStatus');
            if (el) el.remove();
            syncConversationUI();
        }

        async function sendMessage() {
            const text = (chatInput.value || '').trim();
            if (!text) return;
            chatInput.value = '';
            addMsg('user', text);
            chatSend.disabled = true;
            addStatusIndicator();
            var statusInterval = setInterval(function() {
                var t = document.querySelector('#hpChatStatus .hp-chat-status-text');
                if (!t) return;
                if (t.textContent === 'Thinking') t.textContent = 'Answering';
                else if (t.textContent === 'Answering') t.textContent = 'Almost there';
            }, 2200);
            try {
                const body = { message: text };
                if (chatSessionId) body.session_id = chatSessionId;
                const r = await fetch('/api/chat', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
                const data = await r.json();
                clearInterval(statusInterval);
                removeStatusIndicator();
                if (data.session_id) {
                    chatSessionId = data.session_id;
                    localStorage.setItem('hp-chat-session', chatSessionId);
                }
                addMsg('assistant', data.reply || 'Sorry, something went wrong.');
            } catch (e) {
                clearInterval(statusInterval);
                removeStatusIndicator();
                addMsg('assistant', 'Sorry, I could not connect. Please try again.');
            }
            chatSend.disabled = false;
            try { chatInput.focus({ preventScroll: true }); } catch (err) { chatInput.focus(); }
            scheduleSyncChrome();
        }

        chatSend.addEventListener('click', sendMessage);
        chatInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        });
        const chatFileInput = document.getElementById('hpChatFileInput');
        if (chatPlus && chatFileInput) {
            chatPlus.addEventListener('click', function(e) {
                e.stopPropagation();
                chatFileInput.click();
            });
            chatPlus.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chatPlus.click(); }
            });
            chatFileInput.addEventListener('change', async function() {
                const file = this.files && this.files[0];
                this.value = '';
                if (!file) return;
                addMsg('user', 'Uploaded: ' + file.name);
                chatSend.disabled = true;
                try {
                    const fd = new FormData();
                    fd.append('file', file);
                    const r = await fetch('/api/chat/upload-csv', { method: 'POST', body: fd });
                    const data = await r.json();
                    if (r.ok && data.upload_id) {
                        addMsgWithButton('assistant', 'Thank you for your product feed, let me move you into our service.', 'Move to service', '/upload/continue?upload_id=' + encodeURIComponent(data.upload_id));
                    } else {
                        addMsg('assistant', data.detail || 'Sorry, the upload failed. Please try again.');
                    }
                } catch (e) {
                    addMsg('assistant', 'Sorry, I could not upload your file. Please try again.');
                }
                chatSend.disabled = false;
                scheduleSyncChrome();
            });
        }
        if (chatFinish) {
            chatFinish.addEventListener('click', function(e) {
                e.stopPropagation();
                clearConversation();
            });
        }
        var chatHide = document.getElementById('hpChatHide');
        if (chatHide) {
            chatHide.addEventListener('click', function(e) {
                e.stopPropagation();
                chatWrap.classList.add('collapsed-log');
                forceShowForTyping = false;
                scheduleSyncChrome();
            });
        }

        chatPanel.addEventListener('focusin', function() {
            forceShowForTyping = true;
            chatWrap.classList.remove('collapsed-log');
            scheduleSyncChrome();
        });
        chatPanel.addEventListener('focusout', function() {
            var el = this;
            setTimeout(function() {
                if (!el.contains(document.activeElement)) {
                    forceShowForTyping = false;
                    scheduleSyncChrome();
                }
            }, 50);
        });
        chatPanel.addEventListener('click', function() {
            if (document.activeElement !== chatInput) {
                try { chatInput.focus({ preventScroll: true }); } catch (err) { chatInput.focus(); }
            }
        });

        function applyStickyBar() {
            chatSpacer.style.height = Math.ceil(chatWrap.getBoundingClientRect().height) + 'px';
            chatSpacer.style.display = 'block';
            chatWrap.classList.add('sticky');
        }

        function removeStickyBar() {
            chatWrap.classList.remove('sticky');
            chatSpacer.style.height = '0px';
            chatSpacer.style.display = 'none';
        }

        function tickStickyFromScroll() {
            var nh = updateStickyTopVar();
            var anchorTop = chatAnchor.getBoundingClientRect().top;
            var sticky = chatWrap.classList.contains('sticky');
            if (!sticky) {
                if (window.scrollY > 12 && anchorTop <= nh + 16) {
                    applyStickyBar();
                }
            } else {
                if (window.scrollY < 8 || anchorTop >= nh + STICK_HYST) {
                    removeStickyBar();
                }
            }
            scheduleSyncChrome();
        }

        function onScrollOrResizeSticky() {
            if (scrollStickyRaf) return;
            scrollStickyRaf = requestAnimationFrame(function() {
                scrollStickyRaf = null;
                tickStickyFromScroll();
            });
        }

        window.addEventListener('scroll', onScrollOrResizeSticky, { passive: true });
        window.addEventListener('resize', function() {
            updateStickyTopVar();
            onScrollOrResizeSticky();
            syncSpacerHeight();
            scheduleSyncChrome();
        }, { passive: true });

        var heroEl = document.querySelector('.hp-hero');
        if (heroEl) {
            var heroIO = new IntersectionObserver(function(entries) {
                heroInViewport = entries[0].isIntersecting;
                scheduleSyncChrome();
            }, { root: null, rootMargin: '-100px 0px 0px 0px', threshold: 0.1 });
            heroIO.observe(heroEl);
        }

        updateStickyTopVar();
        tickStickyFromScroll();
        syncConversationUI();
    })();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


def _build_login_page(
    next_url: str = "/upload",
    has_google: bool = True,
    has_apple: bool = False,
    request_host: str = "",
    oauth_err: str = "",
) -> str:
    """Build login page HTML. Only show providers that are configured."""
    import html as _html
    from urllib.parse import quote
    import os
    next_param = f"?next={quote(next_url)}" if next_url else ""
    providers = []
    if has_google:
        providers.append((f'<a href="/auth/google{next_param}" class="auth-btn auth-google">Continue with Google</a>', True))
    if has_apple:
        providers.append((f'<a href="/auth/apple{next_param}" class="auth-btn auth-apple">Continue with Apple</a>', True))
    # Dev bypass when OAuth not configured (for local testing only)
    if not providers:
        # In production (DEPLOY_URL set or cartozo.ai host), never show dev mode
        deploy_url = _os.getenv("DEPLOY_URL", "")
        is_production = bool(deploy_url) or (request_host and "cartozo.ai" in request_host.lower())
        dev_bypass = not is_production and _os.getenv("AUTH_DEV_BYPASS", "1").lower() in ("1", "true", "yes")
        if dev_bypass:
            providers.append((f'<a href="/auth/dev{next_param}" class="auth-btn auth-google">Continue (dev mode)</a>', True))
        else:
            providers.append(('<p class="auth-no-providers">OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, or AUTH_DEV_BYPASS=1 for local testing.</p>', False))
    providers_html = "\n".join(p[0] for p in providers if p[1]) or providers[0][0]
    oauth_alert_html = ""
    if oauth_err == "deleted_client":
        oauth_alert_html = (
            '<div class="oauth-alert" role="alert"><strong>OAuth client deleted.</strong> '
            "In Google Cloud Console → APIs &amp; Services → Credentials, create a <strong>new</strong> OAuth 2.0 Client ID (Web application), "
            "add redirect URIs, then set <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> in your server environment and restart. "
            "Check <code>/api/auth/oauth-debug</code> for the id this process uses.</div>"
        )
    elif oauth_err:
        oauth_alert_html = f'<div class="oauth-alert" role="alert">{_html.escape(oauth_err)}</div>'
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Sign in &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; -webkit-font-smoothing: antialiased; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    .login-box {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 48px 40px; max-width: 400px; width: 100%; text-align: center; }}
    [data-theme="light"] .login-box {{ background: #fff; border-color: rgba(15,23,42,0.1); box-shadow: 0 4px 24px rgba(0,0,0,0.06); }}
    .login-box h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 8px; }}
    .login-box p {{ color: rgba(255,255,255,0.5); font-size: 0.9rem; margin-bottom: 32px; line-height: 1.5; }}
    [data-theme="light"] .login-box p {{ color: rgba(15,23,42,0.6); }}
    .auth-btn {{ display: flex; align-items: center; justify-content: center; gap: 12px; width: 100%; padding: 14px 24px; font-size: 1rem; font-weight: 500; border-radius: 8px; text-decoration: none; transition: all 0.2s; margin-bottom: 12px; border: 1px solid transparent; }}
    .auth-google {{ background: #fff; color: #1f1f1f; }}
    .auth-google:hover {{ background: #f5f5f5; }}
    .auth-apple {{ background: #0B0F19; color: #E5E7EB; border-color: rgba(255,255,255,0.2); }}
    [data-theme="light"] .auth-apple {{ background: #1f1f1f; }}
    .auth-apple:hover {{ opacity: 0.9; }}
    .auth-no-providers {{ color: rgba(255,255,255,0.5); font-size: 0.85rem; }}
    .nav {{ position: fixed; top: 0; left: 0; right: 0; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); display: flex; align-items: center; justify-content: space-between; }}
    [data-theme="light"] .nav {{ border-color: rgba(15,23,42,0.08); }}
    .nav-logo img {{ height: 32px; filter: brightness(0) invert(1); }}
    [data-theme="light"] .nav-logo img {{ filter: none; }}
    .theme-btn {{ width: 36px; height: 36px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: rgba(255,255,255,0.6); cursor: pointer; font-size: 1rem; transition: all 0.2s; }}
    [data-theme="light"] .theme-btn {{ border-color: rgba(15,23,42,0.15); color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .auth-no-providers {{ color: rgba(15,23,42,0.5); }}
    .oauth-alert {{ text-align: left; font-size: 0.82rem; line-height: 1.45; color: #fecaca; background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.35); border-radius: 10px; padding: 14px 16px; margin-bottom: 20px; }}
    .oauth-alert code {{ font-size: 0.78rem; background: rgba(0,0,0,0.2); padding: 2px 6px; border-radius: 4px; }}
    [data-theme="light"] .oauth-alert {{ color: #991b1b; background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.3); }}
    </style>
</head>
<body>
{GTM_BODY}
    <nav class="nav">
        <a href="/" class="nav-logo"><img src="/assets/logo-light.png" alt="Cartozo.ai" /></a>
        <button type="button" class="theme-btn" id="themeToggle" aria-label="Toggle theme">&#9728;</button>
    </nav>
    <div class="login-box">
        <h1>Sign in to continue</h1>
        <p>Use your Google or Apple account to access the uploader. No registration required.</p>
        {oauth_alert_html}
        {providers_html}
    </div>
    <script>
    (function(){{
        const t=document.getElementById("themeToggle");
        if(t){{const k="hp-theme";function g(){{return localStorage.getItem(k)||"dark";}}function s(v){{document.documentElement.setAttribute("data-theme",v);localStorage.setItem(k,v);t.textContent=v==="dark"?"\u2600":"\u263E";}}t.onclick=()=>s(g()==="dark"?"light":"dark");s(g());}}
    }})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


_UPLOAD_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Upload feed &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{opacity:0;transition:opacity .28s ease}body.page-transition-out{opacity:0;pointer-events:none}</style>
    <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; -webkit-font-smoothing: antialiased; }
    [data-theme="light"] body { background: #f8fafc; color: #0f172a; }
    [data-theme="light"] .subtitle, [data-theme="light"] .label, [data-theme="light"] .hint { color: rgba(15,23,42,0.7) !important; }
    [data-theme="light"] .hint code { background: rgba(15,23,42,0.1); }
    [data-theme="light"] .dropzone { border-color: rgba(15,23,42,0.2); }
    [data-theme="light"] .dropzone:hover, [data-theme="light"] .dropzone.dragover { border-color: rgba(15,23,42,0.4); background: rgba(15,23,42,0.02); }
    [data-theme="light"] .dropzone.has-file { border-color: #4F46E5; background: rgba(79,70,229,0.06); }
    [data-theme="light"] .dropzone-text { color: rgba(15,23,42,0.6); }
    [data-theme="light"] .dropzone-text strong { color: #0f172a; }
    [data-theme="light"] .dropzone.has-file .dropzone-text { color: #4F46E5; }
    [data-theme="light"] .dropzone-icon { color: rgba(15,23,42,0.4); }
    [data-theme="light"] .dropzone.has-file .dropzone-icon { color: #4F46E5; }
    [data-theme="light"] .dropzone-hint { color: rgba(15,23,42,0.5); }
    [data-theme="light"] .dropzone-filename, [data-theme="light"] .dropzone-thanks { color: rgba(15,23,42,0.8); }
    [data-theme="light"] select { border-color: rgba(15,23,42,0.15); background-color: rgba(255,255,255,0.9); color: #0f172a; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%230f172a' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 16px center; }
    [data-theme="light"] select option { background: #fff; color: #0f172a; }
    [data-theme="light"] .btn-primary { background: #0f172a; color: #fff; }
    [data-theme="light"] .btn-primary:hover { background: #1e293b; }
    [data-theme="light"] .nav-cta { background: #0f172a; color: #fff; }
    [data-theme="light"] .nav-cta:hover { background: #1e293b; }
    [data-theme="light"] .nav-link { color: rgba(15,23,42,0.6); }
    [data-theme="light"] .nav-link:hover, [data-theme="light"] .nav-link.active { color: #0f172a; }

    .nav { display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); }
    [data-theme="light"] .nav { border-bottom-color: rgba(15,23,42,0.08); }
    .nav-logo img { height: 32px; }
    .nav-logo .logo-light { display: block; filter: brightness(0) invert(1); }
    .nav-logo .logo-dark { display: none; }
    [data-theme="light"] .nav-logo .logo-light { display: none; }
    [data-theme="light"] .nav-logo .logo-dark { display: block; filter: none; }
    .theme-btn { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: rgba(255,255,255,0.6); cursor: pointer; font-size: 1rem; transition: all 0.2s; }
    .theme-btn:hover { color: #fff; background: rgba(255,255,255,0.08); }
    [data-theme="light"] .theme-btn { border-color: rgba(15,23,42,0.15); color: rgba(15,23,42,0.6); }
    [data-theme="light"] .theme-btn:hover { color: #0f172a; background: rgba(15,23,42,0.06); }
    .nav-links { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; justify-content: flex-end; }
    .nav-link { color: rgba(255,255,255,0.6); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }
    .nav-link:hover, .nav-link.active { color: #fff; }
    .nav-cta { background: #fff; color: #000; padding: 10px 20px; border-radius: 6px; font-size: 0.85rem; font-weight: 500; text-decoration: none; }
    .nav-merchant { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .nav-merchant-connect { display: inline-flex; align-items: center; justify-content: center; padding: 10px 18px; font-size: 0.85rem; font-weight: 600; border-radius: 8px; text-decoration: none; border: none; cursor: pointer; background: linear-gradient(135deg, #22D3EE 0%, #06b6d4 100%); color: #0a0a0a; box-shadow: 0 2px 12px rgba(34, 211, 238, 0.35); transition: transform 0.15s, filter 0.15s, box-shadow 0.15s; white-space: nowrap; }
    .nav-merchant-connect:hover { filter: brightness(1.06); transform: translateY(-1px); box-shadow: 0 4px 16px rgba(34, 211, 238, 0.45); }
    .nav-merchant-connected { display: none; align-items: center; gap: 10px; flex-wrap: wrap; }
    .nav-merchant-connected.visible { display: flex; }
    button.nav-merchant-pill { font: inherit; font-family: inherit; font-size: 0.8rem; font-weight: 600; padding: 8px 14px; border-radius: 999px; background: rgba(34, 211, 238, 0.15); color: #22D3EE; border: 1px solid rgba(34, 211, 238, 0.35); cursor: pointer; }
    button.nav-merchant-pill:hover { filter: brightness(1.08); }
    [data-theme="light"] button.nav-merchant-pill { color: #0e7490; border-color: rgba(14, 116, 144, 0.35); background: rgba(34, 211, 238, 0.12); }
    .mc-confirm-row { display: flex; gap: 12px; margin-top: 8px; justify-content: stretch; }
    .mc-confirm-no { flex: 1; padding: 12px 14px; font-size: 0.9rem; font-weight: 600; border-radius: 10px; border: 1px solid rgba(255,255,255,0.25); background: transparent; color: rgba(255,255,255,0.9); cursor: pointer; }
    .mc-confirm-no:hover { background: rgba(255,255,255,0.06); }
    .mc-confirm-yes { flex: 1; padding: 12px 14px; font-size: 0.9rem; font-weight: 600; border-radius: 10px; border: none; cursor: pointer; background: linear-gradient(135deg, #22D3EE 0%, #06b6d4 100%); color: #0a0a0a; }
    .mc-confirm-yes:hover { filter: brightness(1.05); }
    [data-theme="light"] .mc-confirm-no { border-color: rgba(15,23,42,0.2); color: #0f172a; }
    [data-theme="light"] .mc-confirm-no:hover { background: rgba(15,23,42,0.06); }
    [data-theme="light"] .nav-merchant-connect { box-shadow: 0 2px 12px rgba(6, 182, 212, 0.3); }

    .mc-success-overlay { position: fixed; inset: 0; background: rgba(5, 8, 15, 0.72); backdrop-filter: blur(6px); z-index: 10000; display: none; align-items: center; justify-content: center; padding: 24px; opacity: 0; transition: opacity 0.28s ease; }
    .mc-success-overlay.visible { display: flex; opacity: 1; }
    .mc-success-modal { background: rgba(18, 22, 32, 0.96); border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 36px 32px; max-width: 400px; width: 100%; text-align: center; box-shadow: 0 24px 64px rgba(0,0,0,0.45); }
    [data-theme="light"] .mc-success-modal { background: #fff; border-color: rgba(15,23,42,0.1); }
    .mc-success-icon { width: 56px; height: 56px; margin: 0 auto 16px; border-radius: 50%; background: linear-gradient(135deg, #22D3EE, #06b6d4); color: #0a0a0a; font-size: 28px; line-height: 56px; font-weight: 700; }
    .mc-success-modal h3 { font-size: 1.15rem; font-weight: 600; color: #fff; margin-bottom: 8px; }
    [data-theme="light"] .mc-success-modal h3 { color: #0f172a; }
    .mc-success-modal p { font-size: 0.9rem; color: rgba(255,255,255,0.6); line-height: 1.5; margin-bottom: 20px; }
    [data-theme="light"] .mc-success-modal p { color: rgba(15,23,42,0.6); }
    .mc-success-gotit { width: 100%; padding: 12px 18px; font-size: 0.95rem; font-weight: 600; border-radius: 10px; border: none; cursor: pointer; background: linear-gradient(135deg, #22D3EE 0%, #06b6d4 100%); color: #0a0a0a; }
    .mc-success-gotit:hover { filter: brightness(1.05); }

    .container { max-width: 600px; margin: 80px auto; padding: 0 24px; }
    .title { font-size: 2rem; font-weight: 600; margin-bottom: 8px; letter-spacing: -0.02em; }
    .subtitle { color: rgba(255,255,255,0.6); font-size: 1rem; margin-bottom: 40px; line-height: 1.6; }

    .form-group { margin-bottom: 24px; }
    .form-actions-top { margin-bottom: 32px; }
    .label { display: block; font-size: 0.85rem; font-weight: 500; margin-bottom: 8px; color: rgba(255,255,255,0.8); }

    .dropzone { border: 2px dashed rgba(255,255,255,0.2); border-radius: 12px; padding: 48px 24px; text-align: center; cursor: pointer; transition: all 0.3s; }
    .dropzone:hover, .dropzone.dragover { border-color: rgba(255,255,255,0.4); background: rgba(255,255,255,0.02); }
    .dropzone.has-file { border-color: #4F46E5; border-style: solid; background: rgba(79,70,229,0.04); }
    .dropzone-icon { font-size: 2.5rem; margin-bottom: 12px; opacity: 0.5; transition: all 0.3s; }
    .dropzone.has-file .dropzone-icon { font-size: 2rem; color: #4F46E5; opacity: 1; animation: pop 0.3s ease-out; }
    .dropzone-text { font-size: 0.95rem; margin-bottom: 4px; color: rgba(255,255,255,0.6); }
    .dropzone-text strong { color: #fff; }
    .dropzone.has-file .dropzone-text { color: #4F46E5; }
    .dropzone-hint { font-size: 0.8rem; color: rgba(255,255,255,0.4); }
    .dropzone.has-file .dropzone-hint { display: none; }
    .dropzone-filename { margin-top: 10px; font-size: 0.88rem; color: rgba(255,255,255,0.9); font-weight: 500; }
    .dropzone-thanks { margin-top: 6px; font-size: 0.82rem; color: rgba(255,255,255,0.5); font-style: italic; opacity: 0; transform: translateY(8px); transition: all 0.4s ease; }
    .dropzone.has-file .dropzone-thanks { opacity: 1; transform: translateY(0); }
    .dropzone input { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); border: 0; }
    
    @keyframes pop { 0% { transform: scale(0.5); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }

    .file-error { margin-top: 12px; padding: 12px 16px; background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); border-radius: 8px; color: #ef4444; font-size: 0.85rem; display: none; }
    .file-error:not(:empty) { display: block; }

    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    @media (max-width: 600px) { .row { grid-template-columns: 1fr; } }

    select { width: 100%; padding: 12px 16px; font-size: 0.9rem; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; background: rgba(255,255,255,0.05); color: #fff; cursor: pointer; -webkit-appearance: none; -moz-appearance: none; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='white' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 16px center; }
    select:focus { outline: none; border-color: rgba(255,255,255,0.3); }
    select option { background: #111; color: #fff; }

    .btn { display: block; width: 100%; padding: 16px 24px; font-size: 1rem; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; transition: all 0.2s; text-align: center; text-decoration: none; }
    .btn-primary { background: #fff; color: #000; }
    .btn-primary:hover { opacity: 0.9; transform: translateY(-1px); }

    .hint { margin-top: 24px; text-align: center; font-size: 0.82rem; color: rgba(255,255,255,0.4); }
    .hint code { background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.78rem; }

    .label-hint { font-weight: 400; color: rgba(255,255,255,0.4); font-size: 0.78rem; }
    [data-theme="light"] .label-hint { color: rgba(15,23,42,0.4); }

    .combo-wrap { position: relative; }
    .combo-input { width: 100%; padding: 12px 40px 12px 16px; font-size: 0.9rem; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; background: rgba(255,255,255,0.05); color: #fff; box-sizing: border-box; }
    .combo-input:focus { outline: none; border-color: rgba(255,255,255,0.3); }
    .combo-input::placeholder { color: rgba(255,255,255,0.35); }
    .combo-arrow { position: absolute; right: 14px; top: 50%; transform: translateY(-50%); font-size: 0.55rem; color: rgba(255,255,255,0.4); pointer-events: none; transition: transform 0.2s; }
    .combo-wrap.open .combo-arrow { transform: translateY(-50%) rotate(180deg); }
    .combo-list { display: none; position: absolute; top: calc(100% + 4px); left: 0; right: 0; max-height: 260px; overflow-y: auto; background: #141b2e; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; list-style: none; margin: 0; padding: 4px 0; z-index: 50; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
    .combo-wrap.open .combo-list { display: block; }
    .combo-list li { padding: 10px 16px; font-size: 0.88rem; color: rgba(255,255,255,0.85); cursor: pointer; transition: background 0.15s; }
    .combo-list li:hover { background: rgba(255,255,255,0.08); }
    .combo-list li.selected { background: rgba(255,255,255,0.06); font-weight: 600; }
    .combo-list li.hidden { display: none; }
    .combo-desc { color: rgba(255,255,255,0.35); font-size: 0.78rem; font-weight: 400; }

    [data-theme="light"] .combo-input { background: rgba(255,255,255,0.9); border-color: rgba(15,23,42,0.15); color: #0f172a; }
    [data-theme="light"] .combo-input:focus { border-color: rgba(15,23,42,0.3); }
    [data-theme="light"] .combo-input::placeholder { color: rgba(15,23,42,0.35); }
    [data-theme="light"] .combo-arrow { color: rgba(15,23,42,0.4); }
    [data-theme="light"] .combo-list { background: #fff; border-color: rgba(15,23,42,0.12); box-shadow: 0 8px 24px rgba(0,0,0,0.1); }
    [data-theme="light"] .combo-list li { color: #0f172a; }
    [data-theme="light"] .combo-list li:hover { background: rgba(15,23,42,0.05); }
    [data-theme="light"] .combo-list li.selected { background: rgba(15,23,42,0.04); }
    [data-theme="light"] .combo-desc { color: rgba(15,23,42,0.4); }

    @media (max-width: 768px) { .nav { padding: 16px 24px; } .nav-link { display: none; } .container { margin: 40px auto; } }
    </style>
</head>
<!-- cartozo-upload-ui:3 merchant-in-nav -->
<body data-upload-ui="3">
{GTM_BODY}
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="nav-links">
            <a href="/batches/history" class="nav-link">Batch history</a>
            <!-- ADMIN_NAV -->
            <div class="nav-merchant" id="navMerchantWrap">
                <a href="/merchant/google/connect" class="nav-merchant-connect" id="merchantConnectBtn">Connect Merchant Center</a>
                <div class="nav-merchant-connected" id="navMerchantConnected">
                    <button type="button" class="nav-merchant-pill" id="merchantConnectedLabel" aria-haspopup="dialog" title="Disconnect Merchant Center">Connected</button>
                </div>
            </div>
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/logout" class="nav-link">Log out</a>
        </div>
    </nav>

    <div id="mcConnectSuccessOverlay" class="mc-success-overlay" aria-hidden="true">
        <div class="mc-success-modal" role="dialog" aria-modal="true" aria-labelledby="mcSuccessTitle" onclick="event.stopPropagation()">
            <div class="mc-success-icon" aria-hidden="true">&#10003;</div>
            <h3 id="mcSuccessTitle">Merchant Center connected</h3>
            <p>Cartozo can upload products to your Google Merchant account on your behalf.</p>
            <button type="button" class="mc-success-gotit" id="mcConnectSuccessGotIt">Got it</button>
        </div>
    </div>

    <div id="merchantDisconnectOverlay" class="mc-success-overlay" aria-hidden="true">
        <div class="mc-success-modal" role="dialog" aria-modal="true" aria-labelledby="mcDiscTitle" onclick="event.stopPropagation()">
            <h3 id="mcDiscTitle">Disconnect Merchant Center?</h3>
            <p>Cartozo will stop uploading products to your Google Merchant account until you connect again.</p>
            <div class="mc-confirm-row">
                <button type="button" class="mc-confirm-no" id="merchantDisconnectCancel">No</button>
                <button type="button" class="mc-confirm-yes" id="merchantDisconnectConfirm">Yes, disconnect</button>
            </div>
        </div>
    </div>

    <div class="container">
        <h1 class="title">Optimize your product catalog</h1>
        <p class="subtitle">Upload a CSV with your products. We'll improve titles, descriptions and translations using AI — then you review and export.</p>

        <form action="/batches/preview" method="post" enctype="multipart/form-data">
            <div class="form-actions-top">
                <button type="submit" class="btn btn-primary">Start processing &rarr;</button>
            </div>
            <div class="form-group">
                <label class="label">Product catalog (CSV)</label>
                <div class="dropzone" id="dropzone">
                    <div class="dropzone-icon" id="dropicon">&#128206;</div>
                    <div class="dropzone-text" id="droptext"><strong>Click to upload</strong> or drag & drop</div>
                    <div class="dropzone-hint">CSV files only, UTF-8 encoding</div>
                    <div class="dropzone-filename" id="filename"></div>
                    <div class="dropzone-thanks" id="thanks"></div>
                    <input id="file" name="file" type="file" accept=".csv" required />
                </div>
                <div id="file-error" class="file-error"></div>
            </div>

            <div class="form-group">
                <label class="label" for="product_type">Product type <span class="label-hint">(affects GMC validation rules)</span></label>
                <div class="combo-wrap" id="comboWrap">
                    <input type="text" class="combo-input" id="productTypeInput" placeholder="Search or select product type..." autocomplete="off" />
                    <input type="hidden" name="product_type" id="productTypeValue" value="standard" />
                    <div class="combo-arrow" id="comboArrow">&#9660;</div>
                    <ul class="combo-list" id="comboList">
                        <li data-value="standard" class="selected">Standard products <span class="combo-desc">— GTIN required</span></li>
                        <li data-value="custom">Custom / Personalized products <span class="combo-desc">— no GTIN needed</span></li>
                        <li data-value="handmade">Handmade products <span class="combo-desc">— no GTIN needed</span></li>
                        <li data-value="vintage">Vintage / Antique products <span class="combo-desc">— no GTIN needed</span></li>
                        <li data-value="private_label">Store brand / Private label <span class="combo-desc">— no GTIN needed</span></li>
                        <li data-value="bundle">Product bundles <span class="combo-desc">— no GTIN needed</span></li>
                        <li data-value="digital">Digital products / Software <span class="combo-desc">— no GTIN needed</span></li>
                        <li data-value="services">Services / Subscriptions <span class="combo-desc">— no GTIN needed</span></li>
                        <li data-value="promotional">Promotional items <span class="combo-desc">— no GTIN needed</span></li>
                    </ul>
                </div>
            </div>

            <div class="row">
                <div class="form-group">
                    <label class="label" for="mode">Processing mode</label>
                    <select id="mode" name="mode">
                        <option value="optimize">Optimize titles & descriptions</option>
                        <option value="translate">Translate descriptions</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="label" for="target_language">Target language</label>
                    <select id="target_language" name="target_language">
                        <option value="">Same as input</option>
                        <option value="en">English</option>
                        <option value="sv">Swedish</option>
                        <option value="de">German</option>
                        <option value="fr">French</option>
                        <option value="es">Spanish</option>
                        <option value="pl">Polish</option>
                    </select>
                </div>
            </div>

            <div class="form-group">
                <label class="label" for="row_limit">Process first N rows (for testing)</label>
                <select id="row_limit" name="row_limit">
                    <option value="0">All rows</option>
                    <option value="10" selected>First 10 rows</option>
                    <option value="20">First 20 rows</option>
                    <option value="50">First 50 rows</option>
                    <option value="100">First 100 rows</option>
                </select>
            </div>
        </form>

        <p class="hint">Results appear instantly. You can also use the <code>POST /batches</code> API.</p>
    </div>

    <script>
    (function(){
        window.dataLayer = window.dataLayer || [];
        function dlFoundUs(payload) {
            dataLayer.push(Object.assign({ event: "found_us" }, payload));
        }
        try {
            var sp = new URLSearchParams(location.search);
            var utm = sp.get("utm_source");
            if (utm) {
                dlFoundUs({
                    found_via: "utm:" + utm,
                    attribution_channel: "utm",
                    utm_medium: sp.get("utm_medium") || "",
                    utm_campaign: sp.get("utm_campaign") || ""
                });
            }
        } catch (e) {}
        try {
            if (!sessionStorage.getItem("cartozo_ref_dl")) {
                var ref = document.referrer;
                if (ref && ref.indexOf(location.hostname) === -1) {
                    sessionStorage.setItem("cartozo_ref_dl", "1");
                    dlFoundUs({ found_via: "referrer", attribution_channel: "referrer", referrer_host: new URL(ref).hostname });
                }
            }
        } catch (e) {}
        var mConn = document.getElementById("merchantConnectBtn");
        var navConnected = document.getElementById("navMerchantConnected");
        var merchantConnectedLabel = document.getElementById("merchantConnectedLabel");
        var mcSuccessOv = document.getElementById("mcConnectSuccessOverlay");
        var mcSuccessOk = document.getElementById("mcConnectSuccessGotIt");
        var discOv = document.getElementById("merchantDisconnectOverlay");
        var discCancel = document.getElementById("merchantDisconnectCancel");
        var discConfirm = document.getElementById("merchantDisconnectConfirm");
        function refreshMerchantUi(s) {
            if (!mConn || !navConnected) return;
            if (!s || !s.connected) {
                mConn.style.display = "inline-flex";
                navConnected.classList.remove("visible");
                return;
            }
            mConn.style.display = "none";
            navConnected.classList.add("visible");
            if (merchantConnectedLabel) {
                merchantConnectedLabel.textContent = s.merchant_id ? "Connected · ID " + s.merchant_id : "Connected";
            }
        }
        try {
            var spMc = new URLSearchParams(location.search);
            if (spMc.get("merchant") === "connected" && mcSuccessOv) {
                mcSuccessOv.classList.add("visible");
                mcSuccessOv.setAttribute("aria-hidden", "false");
                spMc.delete("merchant");
                var qMc = spMc.toString();
                history.replaceState({}, "", location.pathname + (qMc ? "?" + qMc : "") + location.hash);
            }
        } catch (e) {}
        if (mcSuccessOk && mcSuccessOv) {
            function closeMcSuccess() {
                mcSuccessOv.classList.remove("visible");
                mcSuccessOv.setAttribute("aria-hidden", "true");
            }
            mcSuccessOk.addEventListener("click", closeMcSuccess);
            mcSuccessOv.addEventListener("click", function(e) { if (e.target === mcSuccessOv) closeMcSuccess(); });
        }
        fetch("/api/merchant/status", { credentials: "same-origin" }).then(function(r) { return r.ok ? r.json() : null; }).then(refreshMerchantUi).catch(function() {});
        function merchantDiscOpen() {
            if (!discOv) return;
            discOv.classList.add("visible");
            discOv.setAttribute("aria-hidden", "false");
        }
        function merchantDiscClose() {
            if (!discOv) return;
            discOv.classList.remove("visible");
            discOv.setAttribute("aria-hidden", "true");
        }
        if (merchantConnectedLabel) {
            merchantConnectedLabel.addEventListener("click", function(e) {
                if (!navConnected || !navConnected.classList.contains("visible")) return;
                e.preventDefault();
                merchantDiscOpen();
            });
        }
        if (discCancel) discCancel.addEventListener("click", merchantDiscClose);
        if (discOv) discOv.addEventListener("click", function(e) { if (e.target === discOv) merchantDiscClose(); });
        if (discConfirm) {
            discConfirm.addEventListener("click", function() {
                merchantDiscClose();
                fetch("/api/merchant/disconnect", { method: "POST", credentials: "same-origin" }).then(function(r) {
                    if (r.ok) { refreshMerchantUi({ connected: false }); location.reload(); }
                });
            });
        }
    })();
    (function(){
        const zone=document.getElementById("dropzone"),inp=document.getElementById("file"),nameEl=document.getElementById("filename"),errEl=document.getElementById("file-error");
        const thanksEl=document.getElementById("thanks"),iconEl=document.getElementById("dropicon"),textEl=document.getElementById("droptext");
        
        const thanksMsgs = [
            "Thanks for the feed!",
            "Got it, looks delicious!",
            "Yum, fresh data!",
            "Nice one, let's go!",
            "Ready to optimize!"
        ];
        
        function showSuccess(fileName){
            zone.classList.add("has-file");
            nameEl.textContent=fileName;
            iconEl.innerHTML="✓";
            textEl.innerHTML="<strong>Ready to process</strong>";
            thanksEl.textContent=thanksMsgs[Math.floor(Math.random()*thanksMsgs.length)];
        }
        
        function resetZone(){
            zone.classList.remove("has-file");
            nameEl.textContent="";
            iconEl.innerHTML="&#128206;";
            textEl.innerHTML="<strong>Click to upload</strong> or drag & drop";
            thanksEl.textContent="";
        }
        
        function validate(f){
            errEl.textContent="";
            if(!f)return false;
            const ext=f.name.split(".").pop().toLowerCase();
            if(f.type!=="text/csv"&&f.type!=="application/vnd.ms-excel"&&ext!=="csv"){
                errEl.textContent="Only CSV files are supported.";
                inp.value="";resetZone();return false;
            }
            return true;
        }
        zone.onclick=()=>inp.click();
        zone.ondragover=e=>{e.preventDefault();zone.classList.add("dragover");};
        zone.ondragleave=()=>zone.classList.remove("dragover");
        zone.ondrop=e=>{e.preventDefault();zone.classList.remove("dragover");if(e.dataTransfer.files.length&&validate(e.dataTransfer.files[0])){inp.files=e.dataTransfer.files;showSuccess(e.dataTransfer.files[0].name);}};
        inp.onchange=()=>{if(inp.files.length&&validate(inp.files[0]))showSuccess(inp.files[0].name);};
        document.querySelector("form").onsubmit=e=>{if(!inp.files.length||!validate(inp.files[0]))e.preventDefault();};
        /* Searchable combo box for product type */
        const cWrap=document.getElementById("comboWrap"),cInput=document.getElementById("productTypeInput");
        const cList=document.getElementById("comboList"),cVal=document.getElementById("productTypeValue");
        const cItems=Array.from(cList.querySelectorAll("li"));
        const selItem=cList.querySelector("li.selected");
        if(selItem)cInput.value=selItem.textContent.split("—")[0].trim();

        cInput.addEventListener("focus",()=>{cWrap.classList.add("open");filterItems("");});
        cInput.addEventListener("input",()=>{cWrap.classList.add("open");filterItems(cInput.value);});
        document.addEventListener("click",(e)=>{if(!cWrap.contains(e.target))cWrap.classList.remove("open");});
        document.getElementById("comboArrow").parentElement.addEventListener("click",(e)=>{
            if(e.target===cInput)return;
            cWrap.classList.toggle("open");
            if(cWrap.classList.contains("open")){cInput.focus();filterItems("");}
        });

        function filterItems(q){
            const lower=q.toLowerCase().trim();
            cItems.forEach(li=>{
                const text=li.textContent.toLowerCase();
                li.classList.toggle("hidden",lower.length>0&&!text.includes(lower));
            });
        }

        cItems.forEach(li=>{
            li.addEventListener("click",()=>{
                cItems.forEach(x=>x.classList.remove("selected"));
                li.classList.add("selected");
                cVal.value=li.dataset.value;
                cInput.value=li.textContent.split("—")[0].trim();
                cWrap.classList.remove("open");
            });
        });

        cInput.addEventListener("keydown",(e)=>{
            const visible=cItems.filter(li=>!li.classList.contains("hidden"));
            if(e.key==="Enter"&&visible.length===1){
                e.preventDefault();
                visible[0].click();
            }
            if(e.key==="Escape")cWrap.classList.remove("open");
        });

        const themeToggle=document.getElementById("themeToggle");
        if(themeToggle){const THEME_KEY="hp-theme";function getT(){return localStorage.getItem(THEME_KEY)||"dark";}function setT(t){document.documentElement.setAttribute("data-theme",t);localStorage.setItem(THEME_KEY,t);themeToggle.textContent=t==="dark"?"\u2600":"\u263E";}themeToggle.onclick=()=>setT(getT()==="dark"?"light":"dark");setT(getT());}
    })();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


def _build_upload_page(user_role: str = "customer") -> str:
    admin_nav = _admin_nav_links(active="", user_role=user_role)
    return _UPLOAD_TEMPLATE.replace("{GTM_HEAD}", GTM_HEAD).replace("{GTM_BODY}", GTM_BODY).replace("<!-- ADMIN_NAV -->", admin_nav)


def _build_contact_page() -> str:
    return """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
""" + GTM_HEAD + """
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Contact us &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{opacity:0;transition:opacity .28s ease}body.page-transition-out{opacity:0;pointer-events:none}</style>
    <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; overflow-x: hidden; position: relative; -webkit-font-smoothing: antialiased; }
    [data-theme="light"] body { background: #f8fafc; color: #0f172a; }
    [data-theme="light"] .subtitle, [data-theme="light"] .label { color: rgba(15,23,42,0.7); }
    [data-theme="light"] input { border-color: rgba(15,23,42,0.15); background: rgba(255,255,255,0.9); color: #0f172a; }
    [data-theme="light"] input:focus { border-color: rgba(15,23,42,0.3); }
    [data-theme="light"] .contact-email { color: #4F46E5; }
    .cp-stars { position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 0; overflow: hidden; }
    .cp-star { position: absolute; width: 2px; height: 2px; background: rgba(255,255,255,0.5); border-radius: 50%; animation: cp-starDrift 30s ease-in-out infinite; }
    [data-theme="light"] .cp-star { background: rgba(15,23,42,0.25); }
    .cp-star::after { content: ''; position: absolute; top: -1px; left: -1px; width: 4px; height: 4px; background: radial-gradient(circle, rgba(255,255,255,0.4) 0%, transparent 70%); border-radius: 50%; }
    @keyframes cp-starDrift { 0% { transform: translate(0, 0); } 25% { transform: translate(15px, -10px); } 50% { transform: translate(5px, -20px); } 75% { transform: translate(-10px, -8px); } 100% { transform: translate(0, 0); } }
    .cp-star:nth-child(1) { top: 8%; left: 15%; animation-delay: 0s; animation-duration: 30s; }
    .cp-star:nth-child(2) { top: 12%; left: 85%; animation-delay: 5s; animation-duration: 35s; }
    .cp-star:nth-child(3) { top: 25%; left: 92%; animation-delay: 3s; animation-duration: 28s; }
    .cp-star:nth-child(4) { top: 35%; left: 5%; animation-delay: 8s; animation-duration: 32s; }
    .cp-star:nth-child(5) { top: 45%; left: 78%; animation-delay: 2s; animation-duration: 38s; }
    .cp-star:nth-child(6) { top: 55%; left: 25%; animation-delay: 10s; animation-duration: 25s; }
    .cp-star:nth-child(7) { top: 65%; left: 95%; animation-delay: 6s; animation-duration: 33s; }
    .cp-star:nth-child(8) { top: 72%; left: 12%; animation-delay: 4s; animation-duration: 29s; }
    .cp-star:nth-child(9) { top: 82%; left: 68%; animation-delay: 12s; animation-duration: 36s; }
    .cp-star:nth-child(10) { top: 88%; left: 42%; animation-delay: 7s; animation-duration: 31s; }
    .cp-star:nth-child(11) { top: 18%; left: 55%; animation-delay: 9s; animation-duration: 27s; }
    .cp-star:nth-child(12) { top: 38%; left: 35%; animation-delay: 1s; animation-duration: 34s; }
    .cp-star:nth-child(13) { top: 58%; left: 8%; animation-delay: 11s; animation-duration: 26s; }
    .cp-star:nth-child(14) { top: 78%; left: 88%; animation-delay: 13s; animation-duration: 37s; }
    .cp-star:nth-child(15) { top: 92%; left: 22%; animation-delay: 0s; animation-duration: 30s; }
    .cp-particles { position: absolute; width: 100%; height: 100%; top: 0; left: 0; pointer-events: none; z-index: 0; }
    .cp-particle { position: absolute; width: 3px; height: 3px; background: rgba(255,255,255,0.4); border-radius: 50%; animation: cp-particleDrift 8s ease-in-out infinite; pointer-events: none; }
    .cp-particle:nth-child(1) { top: 20%; left: 30%; animation-delay: 0s; }
    .cp-particle:nth-child(2) { top: 60%; left: 70%; animation-delay: 2s; animation-duration: 10s; }
    .cp-particle:nth-child(3) { top: 40%; left: 85%; animation-delay: 4s; animation-duration: 12s; }
    .cp-particle:nth-child(4) { top: 80%; left: 20%; animation-delay: 1s; animation-duration: 9s; }
    @keyframes cp-particleDrift { 0%, 100% { transform: translate(0, 0); opacity: 0.4; } 25% { transform: translate(10px, -15px); opacity: 0.8; } 50% { transform: translate(-5px, -25px); opacity: 0.4; } 75% { transform: translate(-15px, -10px); opacity: 0.7; } }
    .cp-moon-container { position: absolute; width: 320px; height: 320px; left: 50%; top: 50%; transform: translate(-50%, -50%); z-index: 1; pointer-events: none; animation: cp-moonTravel 90s ease-in-out infinite; }
    @keyframes cp-moonTravel { 0% { transform: translate(-50%, -50%) translateX(-55vw); } 50% { transform: translate(-50%, -50%) translateX(55vw); } 100% { transform: translate(-50%, -50%) translateX(-55vw); } }
    .cp-moon-planet { position: relative; width: 100%; height: 100%; }
    .cp-moon-glow { position: absolute; top: 50%; left: 50%; width: 220px; height: 220px; margin: -110px 0 0 -110px; border-radius: 50%; background: radial-gradient(circle, rgba(200,210,230,0.15) 0%, rgba(150,160,180,0.08) 40%, transparent 70%); animation: cp-moonGlow 4s ease-in-out infinite; pointer-events: none; }
    [data-theme="light"] .cp-moon-glow { background: radial-gradient(circle, rgba(100,120,150,0.12) 0%, rgba(80,90,110,0.06) 40%, transparent 70%); }
    @keyframes cp-moonGlow { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.1); opacity: 0.8; } }
    .cp-moon-body { position: absolute; top: 50%; left: 50%; width: 140px; height: 140px; margin: -70px 0 0 -70px; border-radius: 50%; background: radial-gradient(circle at 35% 30%, #c8d0dc, #8b95a5 35%, #5a6474 60%, #3d4552 85%, #2a3040 100%); box-shadow: 0 0 50px rgba(180,190,210,0.2), 0 0 100px rgba(120,130,150,0.15), inset -15px -15px 35px rgba(0,0,0,0.4), inset 8px 8px 25px rgba(255,255,255,0.08); animation: cp-moonFloat 8s ease-in-out infinite; overflow: hidden; }
    [data-theme="light"] .cp-moon-body { background: radial-gradient(circle at 35% 30%, #d8e0e8, #a8b0bc 35%, #78808c 60%, #58606c 85%, #404850 100%); box-shadow: 0 0 40px rgba(100,110,130,0.2), inset -12px -12px 30px rgba(0,0,0,0.2), inset 6px 6px 20px rgba(255,255,255,0.15); }
    @keyframes cp-moonFloat { 0%, 100% { transform: translate(-50%, -50%) translateY(0); } 50% { transform: translate(-50%, -50%) translateY(-12px); } }
    .cp-crater { position: absolute; border-radius: 50%; background: rgba(50,55,65,0.5); box-shadow: inset 2px 2px 4px rgba(0,0,0,0.4); }
    [data-theme="light"] .cp-crater { background: rgba(80,85,95,0.4); }
    .cp-crater-1 { width: 18px; height: 18px; top: 32%; left: 38%; }
    .cp-crater-2 { width: 10px; height: 10px; top: 62%; left: 22%; }
    .cp-crater-3 { width: 14px; height: 14px; top: 22%; left: 62%; }
    .cp-crater-4 { width: 8px; height: 8px; top: 55%; left: 55%; }
    .cp-crater-5 { width: 6px; height: 6px; top: 42%; left: 72%; }
    :root, [data-theme="dark"] { --hp-bg: #0B0F19; --hp-text: #E5E7EB; --hp-muted: #9ca3af; --hp-accent: #4F46E5; --hp-border: rgba(255,255,255,0.1); }
    [data-theme="light"] { --hp-bg: #f8fafc; --hp-text: #0f172a; --hp-muted: rgba(15,23,42,0.6); --hp-accent: #4F46E5; --hp-border: rgba(15,23,42,0.12); }
    .cp-nav { display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; position: fixed; top: 0; left: 0; right: 0; z-index: 1000; background: rgba(0,0,0,0.85); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255,255,255,0.06); }
    [data-theme="light"] .cp-nav { background: rgba(248,250,252,0.95); border-bottom-color: rgba(15,23,42,0.08); }
    .cp-nav-logo { flex-shrink: 0; }
    .cp-nav-logo img { height: 32px; }
    .cp-nav-logo .logo-light { display: block; filter: brightness(0) invert(1); }
    .cp-nav-logo .logo-dark { display: none; }
    [data-theme="light"] .cp-nav-logo .logo-light { display: none; }
    [data-theme="light"] .cp-nav-logo .logo-dark { display: block; filter: none; }
    .cp-nav-links { display: flex; align-items: center; justify-content: center; gap: 28px; flex: 1; }
    .cp-nav-right { display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
    .cp-nav-link { color: var(--hp-muted); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }
    .cp-nav-link:hover { color: var(--hp-text); }
    .cp-theme-btn { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--hp-border); background: transparent; color: var(--hp-muted); cursor: pointer; font-size: 1rem; transition: all 0.2s; }
    .cp-theme-btn:hover { color: var(--hp-text); background: rgba(255,255,255,0.08); }
    [data-theme="light"] .cp-theme-btn:hover { background: rgba(15,23,42,0.06); }
    .cp-nav-cta { background: var(--hp-text); color: var(--hp-bg); padding: 10px 20px; border-radius: 6px; font-size: 0.85rem; font-weight: 500; text-decoration: none; transition: opacity 0.2s; }
    .cp-nav-cta:hover { opacity: 0.9; }
    @media (max-width: 1024px) { .cp-nav-links { display: none; } .cp-nav-right { gap: 12px; } }
    .cp-container { max-width: 480px; margin: 80px auto; padding: 0 24px; position: relative; z-index: 2; padding-top: 100px; }
    .title { font-size: 1.75rem; font-weight: 600; margin-bottom: 8px; }
    .subtitle { color: rgba(255,255,255,0.6); font-size: 0.95rem; margin-bottom: 32px; line-height: 1.5; }
    .contact-email { font-size: 0.9rem; margin-bottom: 32px; }
    .contact-email a { color: #4F46E5; text-decoration: none; }
    .contact-email a:hover { text-decoration: underline; }
    .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .form-group { margin-bottom: 20px; }
    .label { display: block; font-size: 0.85rem; font-weight: 500; margin-bottom: 8px; color: rgba(255,255,255,0.8); }
    input { width: 100%; padding: 12px 16px; font-size: 0.95rem; border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; background: rgba(255,255,255,0.05); color: #fff; }
    input:focus { outline: none; border-color: rgba(255,255,255,0.4); }
    .btn { padding: 14px 28px; font-size: 0.95rem; font-weight: 600; background: #4F46E5; color: #fff; border: none; border-radius: 8px; cursor: pointer; transition: opacity 0.2s; }
    .btn:hover { opacity: 0.9; }
    .btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .success-msg { margin-top: 20px; padding: 16px; background: rgba(34,197,94,0.15); border: 1px solid rgba(34,197,94,0.3); border-radius: 8px; color: #22c55e; font-size: 0.9rem; display: none; }
    .success-msg.show { display: block; }
    .error-msg { margin-top: 20px; padding: 16px; background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3); border-radius: 8px; color: #ef4444; font-size: 0.9rem; display: none; }
    .error-msg.show { display: block; }
    @media (max-width: 600px) { .form-row { grid-template-columns: 1fr; } .cp-moon-container { width: 220px; height: 220px; } .cp-moon-body { width: 90px; height: 90px; margin: -45px 0 0 -45px; } .cp-moon-glow { width: 150px; height: 150px; margin: -75px 0 0 -75px; } }
    </style>
</head>
<body>
""" + GTM_BODY + """
    <div class="cp-stars">
        <div class="cp-star"></div><div class="cp-star"></div><div class="cp-star"></div>
        <div class="cp-star"></div><div class="cp-star"></div><div class="cp-star"></div>
        <div class="cp-star"></div><div class="cp-star"></div><div class="cp-star"></div>
        <div class="cp-star"></div><div class="cp-star"></div><div class="cp-star"></div>
        <div class="cp-star"></div><div class="cp-star"></div><div class="cp-star"></div>
    </div>
    <div class="cp-particles">
        <div class="cp-particle"></div>
        <div class="cp-particle"></div>
        <div class="cp-particle"></div>
        <div class="cp-particle"></div>
    </div>
    <div class="cp-moon-container">
        <div class="cp-moon-planet">
            <div class="cp-moon-glow"></div>
            <div class="cp-moon-body">
                <div class="cp-crater cp-crater-1"></div>
                <div class="cp-crater cp-crater-2"></div>
                <div class="cp-crater cp-crater-3"></div>
                <div class="cp-crater cp-crater-4"></div>
                <div class="cp-crater cp-crater-5"></div>
            </div>
        </div>
    </div>
    <nav class="cp-nav">
        <a href="/" class="cp-nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="cp-nav-links">
            <a href="/#features" class="cp-nav-link">Features</a>
            <a href="/#feed-structure" class="cp-nav-link">Feed Structure</a>
            <a href="/#how-it-works" class="cp-nav-link">How it works</a>
            <a href="/contact" class="cp-nav-link">Contact us</a>
        </div>
        <div class="cp-nav-right">
            <button type="button" class="cp-theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/login" class="cp-nav-cta">Get Started</a>
        </div>
    </nav>
    <div class="cp-container">
        <h1 class="title">Contact us</h1>
        <p class="subtitle">Have a question? Fill out the form below and we'll get back to you.</p>
        <p class="contact-email">Or email us directly: <a href="mailto:oleh.halahan@zanzarra.com">oleh.halahan@zanzarra.com</a></p>
        <form id="contactForm">
            <div class="form-row">
                <div class="form-group">
                    <label class="label" for="name">Name</label>
                    <input type="text" id="name" name="name" required placeholder="John" maxlength="255" />
                </div>
                <div class="form-group">
                    <label class="label" for="surname">Surname</label>
                    <input type="text" id="surname" name="surname" required placeholder="Doe" maxlength="255" />
                </div>
            </div>
            <div class="form-group">
                <label class="label" for="email">Your email</label>
                <input type="email" id="email" name="email" required placeholder="john@example.com" maxlength="255" />
            </div>
            <div class="form-group">
                <label class="label" for="phone">Phone number</label>
                <input type="tel" id="phone" name="phone" placeholder="+1 234 567 8900" maxlength="64" />
            </div>
            <button type="submit" class="btn" id="submitBtn">Send</button>
        </form>
        <div id="successMsg" class="success-msg">Thank you! We'll be in touch soon.</div>
        <div id="errorMsg" class="error-msg"></div>
    </div>
    <script>
    (function(){
        const form=document.getElementById('contactForm');
        const submitBtn=document.getElementById('submitBtn');
        const successMsg=document.getElementById('successMsg');
        const errorMsg=document.getElementById('errorMsg');
        form.onsubmit=async function(e){
            e.preventDefault();
            submitBtn.disabled=true;
            errorMsg.classList.remove('show');
            successMsg.classList.remove('show');
            try{
                const r=await fetch('/api/contact',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
                    name:document.getElementById('name').value.trim(),
                    surname:document.getElementById('surname').value.trim(),
                    email:document.getElementById('email').value.trim(),
                    phone:document.getElementById('phone').value.trim()
                })});
                const d=await r.json().catch(()=>({}));
                if(r.ok){successMsg.classList.add('show');form.reset();}
                else{errorMsg.textContent=d.detail||'Something went wrong. Please try again.';errorMsg.classList.add('show');}
            }catch(err){errorMsg.textContent='Could not send. Please try again.';errorMsg.classList.add('show');}
            submitBtn.disabled=false;
        };
        const t=document.getElementById('themeToggle');
        if(t){const k='hp-theme';function g(){return localStorage.getItem(k)||'dark';}function s(v){document.documentElement.setAttribute('data-theme',v);localStorage.setItem(k,v);t.textContent=v==='dark'?'\u2600':'\u263E';}t.onclick=()=>s(g()==='dark'?'light':'dark');s(g());}
    })();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


def _build_presentation_page() -> str:
    return """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
""" + GTM_HEAD + """
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Features &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{opacity:0;transition:opacity .28s ease}body.page-transition-out{opacity:0;pointer-events:none}</style>
    <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; overflow: hidden; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
    [data-theme="light"] body { background: linear-gradient(165deg, #0f172a 0%, #1e293b 50%, #0f172a 100%); }
    :root { --pp-accent: #4F46E5; --pp-accent-soft: rgba(79,70,229,0.15); --pp-muted: #9ca3af; --pp-ease: cubic-bezier(0.22, 1, 0.36, 1); --pp-ease-out: cubic-bezier(0.16, 1, 0.3, 1); }
    .pp-bg { position: fixed; inset: 0; z-index: 0; overflow: hidden; }
    .pp-bg-gradient { position: absolute; inset: 0; background: radial-gradient(ellipse 120% 80% at 50% -20%, rgba(79,70,229,0.12) 0%, transparent 50%), radial-gradient(ellipse 80% 60% at 80% 80%, rgba(167,139,250,0.06) 0%, transparent 50%), radial-gradient(ellipse 60% 80% at 10% 50%, rgba(59,130,246,0.04) 0%, transparent 50%); }
    .pp-bg-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px); background-size: 60px 60px; mask-image: radial-gradient(ellipse 80% 80% at 50% 50%, black 20%, transparent 70%); }
    .pp-stars { position: absolute; inset: 0; }
    .pp-star { position: absolute; width: 2px; height: 2px; background: rgba(255,255,255,0.6); border-radius: 50%; animation: pp-twinkle 4s ease-in-out infinite; }
    .pp-star:nth-child(1){top:8%;left:12%;}.pp-star:nth-child(2){top:22%;right:18%;animation-delay:0.5s;}
    .pp-star:nth-child(3){top:45%;left:8%;animation-delay:1s;}.pp-star:nth-child(4){top:65%;right:12%;animation-delay:1.5s;}
    .pp-star:nth-child(5){top:85%;left:25%;animation-delay:2s;}.pp-star:nth-child(6){top:15%;left:55%;animation-delay:0.3s;}
    .pp-star:nth-child(7){top:55%;left:85%;animation-delay:2.2s;}.pp-star:nth-child(8){top:35%;right:8%;animation-delay:0.8s;}
    @keyframes pp-twinkle { 0%,100%{opacity:0.4;transform:scale(1)} 50%{opacity:1;transform:scale(1.3)} }
    .pp-nav { position: fixed; top: 0; left: 0; right: 0; padding: 20px 48px; z-index: 200; display: flex; justify-content: space-between; align-items: center; background: linear-gradient(180deg, rgba(5,5,8,0.9) 0%, transparent 100%); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); transition: background 0.4s var(--pp-ease); }
    .pp-nav.scrolled { background: rgba(5,5,8,0.85); }
    .pp-nav-logo { font-size: 1.25rem; font-weight: 700; letter-spacing: -0.02em; color: #fff; text-decoration: none; transition: opacity 0.2s; }
    .pp-nav-logo:hover { opacity: 0.9; }
    .pp-nav-close { font-size: 0.9rem; font-weight: 500; color: var(--pp-muted); text-decoration: none; padding: 10px 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); transition: all 0.25s var(--pp-ease); }
    .pp-nav-close:hover { color: #fff; background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.12); }
    .pp-slides { position: relative; width: 100vw; height: 100vh; }
    .pp-slide { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 140px 48px 120px; opacity: 0; visibility: hidden; transform: scale(0.98); transition: opacity 0.7s var(--pp-ease), visibility 0.7s, transform 0.7s var(--pp-ease); z-index: 1; }
    .pp-slide.active { opacity: 1; visibility: visible; z-index: 2; transform: scale(1); }
    .pp-slide .pp-badge { font-size: 0.75rem; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--pp-accent); margin-bottom: 28px; opacity: 0; transform: translateY(12px); transition: all 0.6s var(--pp-ease) 0.1s; }
    .pp-slide.active .pp-badge { opacity: 1; transform: translateY(0); }
    .pp-slide h1 { font-size: clamp(2.75rem, 6.5vw, 4.5rem); font-weight: 700; letter-spacing: -0.04em; line-height: 1.05; margin-bottom: 24px; text-align: center; background: linear-gradient(135deg, #fff 0%, rgba(255,255,255,0.85) 50%, rgba(255,255,255,0.7) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; opacity: 0; transform: translateY(20px); transition: all 0.6s var(--pp-ease) 0.15s; }
    .pp-slide.active h1 { opacity: 1; transform: translateY(0); }
    .pp-slide h2 { font-size: clamp(1.75rem, 3.5vw, 2.5rem); font-weight: 600; letter-spacing: -0.03em; margin-bottom: 16px; opacity: 0; transform: translateY(16px); transition: all 0.5s var(--pp-ease) 0.1s; }
    .pp-slide.active h2 { opacity: 1; transform: translateY(0); }
    .pp-slide > p { font-size: clamp(1rem, 1.8vw, 1.2rem); color: var(--pp-muted); max-width: 560px; text-align: center; line-height: 1.7; margin-bottom: 12px; opacity: 0; transform: translateY(12px); transition: all 0.5s var(--pp-ease) 0.2s; }
    .pp-slide.active > p { opacity: 1; transform: translateY(0); }
    .pp-features { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; max-width: 960px; margin-top: 48px; }
    .pp-feature { padding: 32px 28px; border-radius: 20px; background: linear-gradient(145deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%); border: 1px solid rgba(255,255,255,0.06); text-align: center; opacity: 0; transform: translateY(28px); transition: all 0.55s var(--pp-ease); backdrop-filter: blur(12px); }
    .pp-slide.active .pp-feature { opacity: 1; transform: translateY(0); }
    .pp-slide.active .pp-feature:nth-child(1){transition-delay:0.2s}.pp-slide.active .pp-feature:nth-child(2){transition-delay:0.28s}.pp-slide.active .pp-feature:nth-child(3){transition-delay:0.36s}
    .pp-slide.active .pp-feature:nth-child(4){transition-delay:0.44s}.pp-slide.active .pp-feature:nth-child(5){transition-delay:0.52s}.pp-slide.active .pp-feature:nth-child(6){transition-delay:0.6s}
    .pp-feature:hover { background: linear-gradient(145deg, var(--pp-accent-soft) 0%, rgba(79,70,229,0.05) 100%); border-color: rgba(79,70,229,0.25); transform: translateY(-6px); box-shadow: 0 20px 40px -20px rgba(79,70,229,0.2); }
    .pp-feature-icon { width: 52px; height: 52px; margin: 0 auto 20px; border-radius: 14px; background: linear-gradient(145deg, var(--pp-accent-soft) 0%, rgba(79,70,229,0.05) 100%); display: flex; align-items: center; justify-content: center; font-size: 1.4rem; color: var(--pp-accent); transition: all 0.35s var(--pp-ease); }
    .pp-feature:hover .pp-feature-icon { background: rgba(79,70,229,0.2); transform: scale(1.05); }
    .pp-feature-title { font-size: 1.05rem; font-weight: 600; letter-spacing: -0.01em; margin-bottom: 10px; }
    .pp-feature-desc { font-size: 0.88rem; color: var(--pp-muted); line-height: 1.6; }
    .pp-flow { display: flex; align-items: flex-start; justify-content: center; gap: 0; margin-top: 56px; flex-wrap: wrap; max-width: 1000px; }
    .pp-flow-step { flex: 1; min-width: 160px; max-width: 200px; text-align: center; position: relative; opacity: 0; transform: translateY(24px); transition: all 0.5s var(--pp-ease); }
    .pp-slide.active .pp-flow-step { opacity: 1; transform: translateY(0); }
    .pp-slide.active .pp-flow-step:nth-child(1){transition-delay:0.15s}.pp-slide.active .pp-flow-step:nth-child(2){transition-delay:0.25s}
    .pp-slide.active .pp-flow-step:nth-child(3){transition-delay:0.35s}.pp-slide.active .pp-flow-step:nth-child(4){transition-delay:0.45s}
    .pp-slide.active .pp-flow-step:nth-child(5){transition-delay:0.55s}
    .pp-flow-connector { flex: 0 0 24px; height: 2px; margin-top: 36px; background: linear-gradient(90deg, rgba(79,70,229,0.4), rgba(79,70,229,0.15)); align-self: center; opacity: 0; transition: opacity 0.5s var(--pp-ease) 0.3s; }
    .pp-slide.active .pp-flow-connector { opacity: 1; }
    .pp-flow-num { width: 48px; height: 48px; border-radius: 14px; background: linear-gradient(145deg, var(--pp-accent-soft) 0%, rgba(79,70,229,0.08) 100%); border: 1px solid rgba(79,70,229,0.2); display: flex; align-items: center; justify-content: center; font-size: 1.1rem; font-weight: 700; color: var(--pp-accent); margin: 0 auto 16px; transition: all 0.35s var(--pp-ease); }
    .pp-flow-step:hover .pp-flow-num { background: rgba(79,70,229,0.2); border-color: rgba(79,70,229,0.4); transform: scale(1.08); }
    .pp-flow-title { font-size: 0.95rem; font-weight: 600; margin-bottom: 8px; }
    .pp-flow-desc { font-size: 0.8rem; color: var(--pp-muted); line-height: 1.5; }
    .pp-result-mock { margin-top: 40px; padding: 24px 32px; border-radius: 16px; background: linear-gradient(165deg, rgba(15,15,18,0.95) 0%, rgba(8,8,10,0.98) 100%); border: 1px solid rgba(255,255,255,0.08); max-width: 500px; opacity: 0; transform: translateY(20px) scale(0.98); transition: all 0.6s var(--pp-ease) 0.3s; }
    .pp-slide.active .pp-result-mock { opacity: 1; transform: translateY(0) scale(1); }
    .pp-result-mock-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); }
    .pp-result-mock-dot { width: 10px; height: 10px; border-radius: 50%; }
    .pp-result-mock-dot:nth-child(1){background:#ff5f57}.pp-result-mock-dot:nth-child(2){background:#febc2e}.pp-result-mock-dot:nth-child(3){background:#28c840}
    .pp-result-mock-title { font-size: 0.8rem; color: var(--pp-muted); font-family: monospace; }
    .pp-result-mock-row { display: flex; gap: 12px; font-size: 0.8rem; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
    .pp-result-mock-row:last-child { border-bottom: none; }
    .pp-result-mock-label { color: var(--pp-muted); min-width: 70px; }
    .pp-result-mock-value { color: #34d399; }
    .pp-result-badge { display: inline-flex; align-items: center; gap: 8px; margin-top: 20px; padding: 10px 20px; border-radius: 10px; background: linear-gradient(135deg, rgba(52,211,153,0.15), rgba(52,211,153,0.05)); border: 1px solid rgba(52,211,153,0.3); font-size: 0.9rem; font-weight: 600; color: #34d399; }
    .pp-cta { margin-top: 48px; opacity: 0; transform: translateY(16px); transition: all 0.6s var(--pp-ease) 0.4s; }
    .pp-slide.active .pp-cta { opacity: 1; transform: translateY(0); }
    .pp-cta a { display: inline-block; padding: 18px 44px; font-size: 1.05rem; font-weight: 600; background: linear-gradient(135deg, var(--pp-accent) 0%, #6366f1 100%); color: #fff; border-radius: 14px; text-decoration: none; transition: all 0.3s var(--pp-ease); box-shadow: 0 4px 24px -4px rgba(79,70,229,0.4); }
    .pp-cta a:hover { transform: translateY(-3px); box-shadow: 0 12px 32px -8px rgba(79,70,229,0.5); }
    .pp-progress { position: fixed; bottom: 0; left: 0; right: 0; height: 3px; background: rgba(255,255,255,0.06); z-index: 200; }
    .pp-progress-bar { height: 100%; background: linear-gradient(90deg, var(--pp-accent), #22D3EE); width: 0%; transition: width 0.5s var(--pp-ease); }
    .pp-dots { position: fixed; bottom: 36px; left: 50%; transform: translateX(-50%); display: flex; gap: 10px; z-index: 200; }
    .pp-dot { width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,0.2); cursor: pointer; transition: all 0.35s var(--pp-ease); }
    .pp-dot:hover { background: rgba(255,255,255,0.4); transform: scale(1.25); }
    .pp-dot.active { background: var(--pp-accent); width: 24px; border-radius: 4px; }
    .pp-arrows { position: fixed; top: 50%; left: 0; right: 0; transform: translateY(-50%); display: flex; justify-content: space-between; padding: 0 20px; z-index: 200; pointer-events: none; }
    .pp-arrow { width: 52px; height: 52px; border-radius: 50%; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 1.2rem; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.3s var(--pp-ease); pointer-events: auto; }
    .pp-arrow:hover { background: var(--pp-accent-soft); border-color: rgba(79,70,229,0.3); color: var(--pp-accent); transform: scale(1.05); }
    @media (max-width: 900px) { .pp-flow { flex-direction: column; align-items: center; gap: 32px; } .pp-flow-connector { width: 2px; height: 24px; margin: 0; background: linear-gradient(180deg, rgba(79,70,229,0.4), rgba(79,70,229,0.15)); } }
    @media (max-width: 768px) { .pp-features { grid-template-columns: 1fr 1fr; gap: 16px; } .pp-arrows { padding: 0 12px; } .pp-arrow { width: 44px; height: 44px; } .pp-nav { padding: 16px 24px; } }
    </style>
</head>
<body>
""" + GTM_BODY + """
    <div class="pp-bg">
        <div class="pp-bg-gradient"></div>
        <div class="pp-bg-grid"></div>
        <div class="pp-stars">
            <div class="pp-star"></div><div class="pp-star"></div><div class="pp-star"></div>
            <div class="pp-star"></div><div class="pp-star"></div><div class="pp-star"></div>
            <div class="pp-star"></div><div class="pp-star"></div>
        </div>
    </div>
    <nav class="pp-nav" id="ppNav">
        <a href="/" class="pp-nav-logo">Cartozo.ai</a>
        <a href="/" class="pp-nav-close">Close</a>
    </nav>
    <div class="pp-slides">
        <div class="pp-slide active" data-slide="0">
            <span class="pp-badge">AI-Powered E-commerce</span>
            <h1>Optimize Every Product<br/>for Maximum Visibility</h1>
            <p>Transform your product feed with AI. Better titles, compelling descriptions, and higher search rankings.</p>
        </div>
        <div class="pp-slide" data-slide="1">
            <h2>Key Features</h2>
            <p>Everything you need to elevate your product content</p>
            <div class="pp-features">
                <div class="pp-feature"><div class="pp-feature-icon">&#128269;</div><div class="pp-feature-title">SEO-Optimized Titles</div><div class="pp-feature-desc">AI expands titles with relevant keywords using proven e-commerce patterns.</div></div>
                <div class="pp-feature"><div class="pp-feature-icon">&#128196;</div><div class="pp-feature-title">Compelling Descriptions</div><div class="pp-feature-desc">Conversion-focused descriptions emphasizing benefits and features.</div></div>
                <div class="pp-feature"><div class="pp-feature-icon">&#127760;</div><div class="pp-feature-title">Multi-Language</div><div class="pp-feature-desc">Translate to German, Swedish, French, Spanish, Polish, and more.</div></div>
                <div class="pp-feature"><div class="pp-feature-icon">&#128200;</div><div class="pp-feature-title">Quality Scoring</div><div class="pp-feature-desc">Each optimization gets a 1–100 score so you see improvement.</div></div>
                <div class="pp-feature"><div class="pp-feature-icon">&#9881;</div><div class="pp-feature-title">Custom Prompts</div><div class="pp-feature-desc">Match your brand voice and SEO strategy.</div></div>
                <div class="pp-feature"><div class="pp-feature-icon">&#128190;</div><div class="pp-feature-title">CSV Import/Export</div><div class="pp-feature-desc">Upload your feed, review results, export optimized data.</div></div>
            </div>
        </div>
        <div class="pp-slide" data-slide="2">
            <h2>How It Works</h2>
            <p>Five steps from upload to optimized feed</p>
            <div class="pp-flow">
                <div class="pp-flow-step"><div class="pp-flow-num">1</div><div class="pp-flow-title">Upload CSV</div><div class="pp-flow-desc">Drag your product feed file into the uploader.</div></div>
                <div class="pp-flow-connector"></div>
                <div class="pp-flow-step"><div class="pp-flow-num">2</div><div class="pp-flow-title">Map Columns</div><div class="pp-flow-desc">Match your columns to standard fields. AI suggests mappings.</div></div>
                <div class="pp-flow-connector"></div>
                <div class="pp-flow-step"><div class="pp-flow-num">3</div><div class="pp-flow-title">AI Optimizes</div><div class="pp-flow-desc">Our AI generates improved titles and descriptions.</div></div>
                <div class="pp-flow-connector"></div>
                <div class="pp-flow-step"><div class="pp-flow-num">4</div><div class="pp-flow-title">Review Results</div><div class="pp-flow-desc">Compare before/after, regenerate if needed.</div></div>
                <div class="pp-flow-connector"></div>
                <div class="pp-flow-step"><div class="pp-flow-num">5</div><div class="pp-flow-title">Export</div><div class="pp-flow-desc">Download your optimized feed, ready for Google Merchant.</div></div>
            </div>
        </div>
        <div class="pp-slide" data-slide="3">
            <h2>Final Result</h2>
            <p>Your optimized feed, ready to upload</p>
            <div class="pp-result-mock">
                <div class="pp-result-mock-header"><span class="pp-result-mock-dot"></span><span class="pp-result-mock-dot"></span><span class="pp-result-mock-dot"></span><span class="pp-result-mock-title">optimized_feed.csv</span></div>
                <div class="pp-result-mock-row"><span class="pp-result-mock-label">title</span><span class="pp-result-mock-value">IKEA Wooden Dining Chair Black | Modern Kitchen Furniture</span></div>
                <div class="pp-result-mock-row"><span class="pp-result-mock-label">desc</span><span class="pp-result-mock-value">Modern wooden dining chair. Solid wood, ergonomic design&hellip;</span></div>
                <div class="pp-result-badge">&#10003; Ready for Google Merchant Center</div>
            </div>
        </div>
        <div class="pp-slide" data-slide="4">
            <h2>Ready to Optimize?</h2>
            <p>Start with a free trial — no API key needed for demo mode.</p>
            <div class="pp-cta"><a href="/login">Get Started Free</a></div>
        </div>
    </div>
    <div class="pp-arrows">
        <button class="pp-arrow" id="ppPrev" aria-label="Previous">&#8592;</button>
        <button class="pp-arrow" id="ppNext" aria-label="Next">&#8594;</button>
    </div>
    <div class="pp-progress"><div class="pp-progress-bar" id="ppProgressBar"></div></div>
    <div class="pp-dots" id="ppDots"></div>
    <script>
    (function(){
        var slides=document.querySelectorAll('.pp-slide');
        var dotsEl=document.getElementById('ppDots');
        var progressBar=document.getElementById('ppProgressBar');
        var cur=0;
        var TOTAL=slides.length;
        var AUTO_MS=7500;
        var t;
        function go(n){cur=(n+TOTAL)%TOTAL;slides.forEach(function(s,i){s.classList.toggle('active',i===cur);});if(dotsEl){dotsEl.querySelectorAll('.pp-dot').forEach(function(d,i){d.classList.toggle('active',i===cur);});}if(progressBar){progressBar.style.width=(100*(cur+1)/TOTAL)+'%';}}
        function next(){go(cur+1);resetAuto();}
        function prev(){go(cur-1);resetAuto();}
        function resetAuto(){clearTimeout(t);t=setTimeout(next,AUTO_MS);}
        for(var i=0;i<TOTAL;i++){var d=document.createElement('span');d.className='pp-dot'+(i===0?' active':'');d.setAttribute('aria-label','Slide '+(i+1));(function(idx){d.onclick=function(){go(idx);resetAuto();};})(i);dotsEl.appendChild(d);}
        document.getElementById('ppPrev').onclick=prev;
        document.getElementById('ppNext').onclick=next;
        document.addEventListener('keydown',function(e){if(e.key==='ArrowLeft')prev();if(e.key==='ArrowRight'||e.key===' ')e.preventDefault(),next();});
        go(0);
        resetAuto();
    })();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


def _build_homepage_html() -> str:
    """Build homepage HTML with SEO meta from settings."""
    import html as html_module
    s = _get_settings()
    meta_title = s.get("seo_meta_title") or "Cartozo.ai — AI-Powered Product Feed Optimization"
    meta_desc = s.get("seo_meta_description") or "AI-powered optimization for your product titles and descriptions."
    og_title = s.get("seo_og_title") or meta_title
    og_desc = s.get("seo_og_description") or meta_desc
    og_image = s.get("seo_og_image") or ""
    og_site = s.get("seo_og_site_name") or "Cartozo.ai"
    return HOMEPAGE_HTML.replace("{GTM_HEAD}", GTM_HEAD).replace(
        "{SEO_META_TITLE}", html_module.escape(meta_title)).replace(
        "{SEO_META_DESCRIPTION}", html_module.escape(meta_desc)).replace(
        "{SEO_OG_TITLE}", html_module.escape(og_title)).replace(
        "{SEO_OG_DESCRIPTION}", html_module.escape(og_desc)).replace(
        "{SEO_OG_IMAGE}", html_module.escape(og_image)).replace(
        "{SEO_OG_SITE_NAME}", html_module.escape(og_site))


@app.get("/", response_class=HTMLResponse)
def homepage():
    return HTMLResponse(content=_build_homepage_html())


@app.get("/contact", response_class=HTMLResponse)
def contact_page():
    return HTMLResponse(content=_build_contact_page())


@app.get("/presentation", response_class=HTMLResponse)
def presentation_page():
    return HTMLResponse(content=_build_presentation_page())


@app.post("/api/contact")
async def api_contact(request: Request):
    """Save contact form submission."""
    import re
    data = await request.json()
    name = (data.get("name") or "").strip()[:255]
    surname = (data.get("surname") or "").strip()[:255]
    email = (data.get("email") or "").strip()[:255]
    phone = (data.get("phone") or "").strip()[:64]
    if not name or not surname or not email:
        raise HTTPException(status_code=400, detail="Name, surname and email are required.")
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        raise HTTPException(status_code=400, detail="Invalid email address.")
    from .db import get_db
    from .services.db_repository import save_contact_submission
    with get_db() as db:
        save_contact_submission(db, name, surname, email, phone)
    return JSONResponse({"status": "ok"})


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    redir = require_login_redirect(request, "/upload")
    if redir:
        return redir
    user = get_current_user(request)
    role = user.get("role", "customer") if user else "customer"
    r = HTMLResponse(content=_build_upload_page(user_role=role))
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    r.headers["Pragma"] = "no-cache"
    r.headers["X-Cartozo-Upload-UI"] = UPLOAD_UI_REVISION
    _onboarding_track(request, r, 1)
    return r


@app.get("/upload/continue", response_class=HTMLResponse)
async def upload_continue(request: Request, upload_id: str = Query(...)):
    """Show mapping page for a pending upload (e.g. from hero chat). Requires login."""
    redir = require_login_redirect(request, f"/upload/continue?upload_id={upload_id}")
    if redir:
        return redir
    from .db import get_db
    from .services.db_repository import get_pending_upload
    with get_db() as db:
        pending = get_pending_upload(db, upload_id)
    if not pending:
        raise HTTPException(status_code=400, detail="Upload session expired. Please re-upload your CSV.")

    records = pending["records"]
    csv_columns = list(records[0].keys())
    guessed = guess_mapping(csv_columns)
    sample_rows = records[:5]
    mode = pending.get("mode", "optimize")
    target_language = pending.get("target_language", "") or ""
    product_type = pending.get("product_type", "standard") or "standard"

    user = get_current_user(request)
    role = user.get("role", "customer") if user else "customer"
    r = HTMLResponse(content=_build_mapping_page(
        upload_id=upload_id,
        csv_columns=csv_columns,
        guessed=guessed,
        sample_rows=sample_rows,
        mode=mode,
        target_language=target_language,
        total_rows=len(records),
        product_type=product_type,
        user_role=role,
    ))
    _onboarding_track(request, r, 2)
    return r


@app.post("/batches/preview", response_class=HTMLResponse)
async def preview_csv(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("optimize"),
    target_language: Optional[str] = Form(None),
    row_limit: int = Form(0),
    product_type: str = Form("standard"),
):
    redir = require_login_redirect(request, "/upload")
    if redir:
        return redir
    if file.content_type not in {"text/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=400, detail="Only CSV upload is supported.")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")

    is_safe, security_error = validate_csv_content(text, len(content))
    if not is_safe:
        raise HTTPException(status_code=400, detail=security_error)

    records = parse_csv_file(io.StringIO(text))
    if not records:
        raise HTTPException(status_code=400, detail="CSV appears empty or has no rows.")

    if row_limit > 0:
        records = records[:row_limit]

    csv_columns = list(records[0].keys())
    guessed = guess_mapping(csv_columns)
    sample_rows = records[:5]

    upload_id = str(uuid.uuid4())
    from .db import get_db
    from .services.db_repository import save_pending_upload
    with get_db() as db:
        save_pending_upload(db, upload_id, records, mode, target_language or "", product_type)

    user = get_current_user(request)
    role = user.get("role", "customer") if user else "customer"
    r = HTMLResponse(content=_build_mapping_page(
        upload_id=upload_id,
        csv_columns=csv_columns,
        guessed=guessed,
        sample_rows=sample_rows,
        mode=mode,
        target_language=target_language or "",
        total_rows=len(records),
        product_type=product_type,
        user_role=role,
    ))
    _onboarding_track(request, r, 2)
    return r


@app.post("/batches/confirm", response_class=HTMLResponse)
async def confirm_mapping(
    request: Request,
    upload_id: str = Form(...),
    mode: str = Form("optimize"),
    target_language: str = Form(""),
    mappings_json: str = Form(...),
    optimize_fields: str = Form("title,description"),
    product_type: str = Form("standard"),
):
    redir = require_login_redirect(request, "/upload")
    if redir:
        return redir
    from .db import get_db
    from .services.db_repository import get_pending_upload
    with get_db() as db:
        pending = get_pending_upload(db, upload_id)
    if not pending:
        raise HTTPException(status_code=400, detail="Upload session expired. Please re-upload your CSV.")

    user = get_current_user(request)
    role = user.get("role", "customer") if user else "customer"
    r = HTMLResponse(content=_build_processing_page(upload_id, mode, target_language, mappings_json, optimize_fields, product_type=product_type, user_role=role))
    _onboarding_track(request, r, 3)
    return r


@app.post("/batches/run")
async def run_processing(
    request: Request,
    upload_id: str = Form(...),
    mode: str = Form("optimize"),
    target_language: str = Form(""),
    optimize_fields: str = Form("title,description"),
    product_type: str = Form("standard"),
    mappings_json: str = Form(...),
):
    require_login_http(request)  # Returns 401 JSON for fetch
    try:
        from .db import get_db
        from .services.db_repository import delete_pending_upload
        with get_db() as db:
            pending = delete_pending_upload(db, upload_id)
        if not pending:
            raise HTTPException(status_code=400, detail="Upload session expired.")

        custom_mapping: dict = json.loads(mappings_json)
        records = pending["records"]
        opt_set = set(optimize_fields.split(","))

        batch_id = str(uuid.uuid4())
        normalized_products: List[NormalizedProduct] = normalize_records(records, custom_mapping=custom_mapping)

        actions = decide_actions_for_products(normalized_products, mode=mode)
        user = get_current_user(request)
        owner_email = (user.get("email") or "").strip() if user else ""
        storage.create_batch(
            batch_id=batch_id,
            products=normalized_products,
            actions=actions,
            product_type=product_type,
            user_email=owner_email or None,
        )

        if target_language:
            storage.default_target_language = target_language
        elif mode == "translate":
            storage.default_target_language = "en"

        # Pass current prompts to AI provider
        s = _get_settings()
        storage._ai.set_prompts(s["prompt_title"], s["prompt_description"])

        storage.process_batch_synchronously(batch_id, optimize_fields=opt_set)

        _onboarding_track(request, None, 4)
        return {"batch_id": batch_id}
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.exception("batches/run failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")


def _build_processing_page(upload_id: str, mode: str, target_language: str, mappings_json: str, optimize_fields: str = "title,description", product_type: str = "standard", user_role: str = "customer") -> str:
    mappings_escaped = mappings_json.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Processing &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; display: flex; flex-direction: column; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    [data-theme="light"] .thinking-sub, [data-theme="light"] .progress-pct {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .spinner {{ border-color: rgba(15,23,42,0.1); border-top-color: #22D3EE; }}
    [data-theme="light"] .progress {{ background: rgba(15,23,42,0.1); }}
    .nav {{ display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
    [data-theme="light"] .nav {{ border-bottom-color: rgba(15,23,42,0.08); }}
    .nav-logo img {{ height: 32px; }}
    .nav-logo .logo-light {{ display: block; filter: brightness(0) invert(1); }}
    .nav-logo .logo-dark {{ display: none; }}
    [data-theme="light"] .nav-logo .logo-light {{ display: none; }}
    [data-theme="light"] .nav-logo .logo-dark {{ display: block; filter: none; }}
    .theme-btn {{ display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: rgba(255,255,255,0.6); cursor: pointer; font-size: 1rem; transition: all 0.2s; }}
    .theme-btn:hover {{ color: #fff; background: rgba(255,255,255,0.08); }}
    [data-theme="light"] .theme-btn {{ border-color: rgba(15,23,42,0.15); color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .theme-btn:hover {{ color: #0f172a; background: rgba(15,23,42,0.06); }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover {{ color: #0f172a; }}
    .nav-links {{ display: flex; align-items: center; gap: 32px; }}
    .nav-link {{ color: rgba(255,255,255,0.6); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }}
    .nav-link:hover {{ color: #fff; }}

    .main {{ flex: 1; display: flex; align-items: center; justify-content: center; padding: 24px; }}
    .loader {{ text-align: center; max-width: 460px; width: 100%; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 48px 40px; }}
    [data-theme="light"] .loader {{ background: #fff; border-color: rgba(15,23,42,0.1); box-shadow: 0 4px 24px rgba(0,0,0,0.06); }}

    .icon-wrap {{ width: 64px; height: 64px; margin: 0 auto 24px; position: relative; }}
    .spinner {{ width: 64px; height: 64px; border: 3px solid rgba(255,255,255,0.1); border-top-color: #22D3EE; border-radius: 50%; animation: spin 1s cubic-bezier(0.4,0,0.2,1) infinite; }}
    .checkmark {{ display: none; width: 64px; height: 64px; border-radius: 50%; background: #4F46E5; color: #fff; font-size: 32px; line-height: 64px; text-align: center; animation: popIn 0.35s cubic-bezier(0.2,0.8,0.2,1.2); }}
    .done .spinner {{ display: none; }}
    .done .checkmark {{ display: block; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @keyframes popIn {{ 0% {{ transform: scale(0); }} 100% {{ transform: scale(1); }} }}

    .thinking {{ font-size: 1.25rem; font-weight: 600; min-height: 1.6em; transition: opacity 0.35s ease; }}
    .thinking-sub {{ font-size: 0.9rem; color: rgba(255,255,255,0.5); margin-top: 8px; }}
    .dots::after {{ content: ''; animation: dots 1.5s steps(4, end) infinite; }}
    @keyframes dots {{ 0%{{content:'';}} 25%{{content:'.';}} 50%{{content:'..';}} 75%{{content:'...';}} }}

    .progress {{ width: 100%; height: 6px; background: rgba(255,255,255,0.1); border-radius: 999px; margin-top: 32px; overflow: hidden; }}
    .progress-fill {{ height: 100%; width: 0%; background: linear-gradient(90deg, #4F46E5, #22D3EE); border-radius: 999px; transition: width 0.12s linear; }}
    .progress-pct {{ font-size: 0.8rem; color: rgba(255,255,255,0.4); margin-top: 10px; font-variant-numeric: tabular-nums; }}

    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} }}
    </style>
</head>
<body>
{GTM_BODY}
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="nav-links">
            <a href="/batches/history" class="nav-link">Batch history</a>
            {_admin_nav_links(user_role=user_role)}
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
        </div>
    </nav>

    <main class="main">
        <div class="loader">
            <div class="icon-wrap">
                <div class="spinner"></div>
                <div class="checkmark">&#10003;</div>
            </div>
            <div class="thinking" id="thinking">Boiling the water</div>
            <div class="thinking-sub">This may take a moment depending on catalog size<span class="dots"></span></div>
            <div class="progress"><div class="progress-fill"></div></div>
            <div class="progress-pct" id="pct">0%</div>
        </div>
    </main>

    <input type="hidden" id="mj" value="{mappings_escaped}" />
    <script>
    const phrases = [
        "Boiling water","Reading each title","Consulting the SEO oracle",
        "Scoring descriptions as a copywriter","Feeding algorithms with data",
        "Counting pixels","Negotiating with search engines","Brewing strong coffee",
        "Polishing text to a shine","Teaching products to sell themselves",
        "Whispering keywords","Waking up AI hamsters","Sprinkling conversion dust",
        "Smoothing out wrinkles","Checking for hallucinations",
        "Asking ChatGPT for help","Optimizing at full throttle",
        "Rewriting titles with passion","Making descriptions readable",
        "Convincing the algorithm of our value","Almost there!"
    ];
    let phraseIdx=0, pct=0, batchId=null, serverReady=false;
    const pageStart=Date.now(), MIN_SHOW=5000;

    function nextPhrase(){{
        const el=document.getElementById("thinking");
        phraseIdx=(phraseIdx+1)%phrases.length;
        el.style.opacity=0;
        setTimeout(()=>{{el.textContent=phrases[phraseIdx];el.style.opacity=1;}},250);
    }}
    function setBar(val){{
        pct=Math.min(val,100);
        document.querySelector(".progress-fill").style.width=pct+"%";
        document.getElementById("pct").textContent=Math.round(pct)+"%";
    }}
    let crawlTimer=null;
    function startCrawl(ceiling){{
        crawlTimer=setInterval(()=>{{
            if(pct>=ceiling){{clearInterval(crawlTimer);return;}}
            setBar(pct+Math.max(0.15,(ceiling-pct)*0.02));
        }},80);
    }}
    function finishBar(cb){{
        clearInterval(crawlTimer);
        const fin=setInterval(()=>{{
            if(pct>=100){{clearInterval(fin);setBar(100);cb();return;}}
            setBar(pct+1.2);
        }},30);
    }}
    function showDone(){{
        document.querySelector(".loader").classList.add("done");
        const el=document.getElementById("thinking");
        el.style.opacity=0;
        setTimeout(()=>{{el.textContent="Done!";el.style.opacity=1;document.querySelector(".thinking-sub").innerHTML="Redirecting to results...";}},300);
        setTimeout(()=>{{window.location.href="/batches/"+batchId+"/review";}},1400);
    }}
    function tryFinish(){{
        if(!serverReady)return;
        setTimeout(()=>{{finishBar(showDone);}},Math.max(0,MIN_SHOW-(Date.now()-pageStart)));
    }}
    async function startProcessing(){{
        setInterval(nextPhrase,1800);
        startCrawl(80);
        const form=new FormData();
        form.append("upload_id","{upload_id}");
        form.append("mode","{mode}");
        form.append("target_language","{target_language}");
        form.append("optimize_fields","{optimize_fields}");
        form.append("product_type","{product_type}");
        form.append("mappings_json",document.getElementById("mj").value);
        try{{
            const resp=await fetch("/batches/run",{{method:"POST",body:form}});
            if(!resp.ok){{clearInterval(crawlTimer);if(resp.status===401){{window.location.href="/login?next="+encodeURIComponent(window.location.pathname||"/upload");return;}}const err=await resp.json().catch(()=>({{}}));alert(err.detail||"Processing failed.");window.location.href="/login";return;}}
            const data=await resp.json();
            batchId=data.batch_id;
            serverReady=true;
            tryFinish();
        }}catch(e){{clearInterval(crawlTimer);alert("Something went wrong.");window.location.href="/upload";}}
    }}
    startProcessing();
    (function(){{
        const t=document.getElementById("themeToggle");
        if(t){{const k="hp-theme";function g(){{return localStorage.getItem(k)||"dark";}}function s(v){{document.documentElement.setAttribute("data-theme",v);localStorage.setItem(k,v);t.textContent=v==="dark"?"\u2600":"\u263E";}}t.onclick=()=>s(g()==="dark"?"light":"dark");s(g());}}
    }})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


def _build_mapping_page(
    upload_id: str,
    csv_columns: List[str],
    guessed: dict,
    sample_rows: List[dict],
    mode: str,
    target_language: str,
    total_rows: int = 0,
    product_type: str = "standard",
    user_role: str = "customer",
) -> str:
    internal_options = ["-- skip --"] + INTERNAL_FIELDS
    field_labels = {"image_url": "image_link"}
    select_rows = ""
    for col in csv_columns:
        current = guessed.get(col, "")
        opts = ""
        for opt in internal_options:
            val = "" if opt == "-- skip --" else opt
            label = field_labels.get(opt, opt)
            selected = 'selected' if val == current else ''
            opts += f'<option value="{val}" {selected}>{label}</option>'
        sample_vals = [str(row.get(col, ""))[:60] for row in sample_rows]
        sample_preview = " | ".join(sample_vals) if sample_vals else ""
        select_rows += f"""
        <tr>
            <td class="col-name">{col}</td>
            <td class="sample">{sample_preview}</td>
            <td><select data-col="{col}">{opts}</select></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Map columns &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    [data-theme="light"] .subtitle, [data-theme="light"] .subtitle strong {{ color: rgba(15,23,42,0.8) !important; }}
    [data-theme="light"] .table-container, [data-theme="light"] .options-box {{ background: rgba(255,255,255,0.8); border-color: rgba(15,23,42,0.15); }}
    [data-theme="light"] th {{ color: rgba(15,23,42,0.5); background: rgba(15,23,42,0.04); border-bottom-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] td, [data-theme="light"] .col-name {{ color: #0f172a; border-bottom-color: rgba(15,23,42,0.06); }}
    [data-theme="light"] .sample {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] select {{ border-color: rgba(15,23,42,0.15); background-color: rgba(255,255,255,0.9); color: #0f172a; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%230f172a' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; }}
    [data-theme="light"] select option {{ background: #fff; color: #0f172a; }}
    [data-theme="light"] .options-title, [data-theme="light"] .checkbox-label {{ color: rgba(15,23,42,0.9); }}
    [data-theme="light"] .btn-back {{ border-color: rgba(15,23,42,0.2); color: #0f172a; }}
    [data-theme="light"] .btn-back:hover {{ border-color: rgba(15,23,42,0.4); }}
    [data-theme="light"] .btn-primary {{ background: #0f172a; color: #fff; }}
    [data-theme="light"] .nav {{ border-bottom-color: rgba(15,23,42,0.08); }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover, [data-theme="light"] .nav-link.active {{ color: #0f172a; }}
    [data-theme="light"] .nav-cta {{ background: #0f172a; color: #fff; }}
    .nav-cta {{ background: #fff; color: #000; padding: 10px 20px; border-radius: 6px; font-size: 0.85rem; font-weight: 500; text-decoration: none; }}

    .container {{ max-width: 900px; margin: 40px auto; padding: 0 24px; }}
    .title {{ font-size: 1.75rem; font-weight: 600; margin-bottom: 8px; letter-spacing: -0.02em; display: flex; align-items: center; gap: 12px; }}
    .subtitle {{ color: rgba(255,255,255,0.6); font-size: 0.95rem; margin-bottom: 32px; line-height: 1.6; }}
    .subtitle strong {{ color: #fff; }}

    .table-container {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; overflow: hidden; margin-bottom: 24px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; padding: 12px 16px; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: rgba(255,255,255,0.5); background: rgba(255,255,255,0.03); border-bottom: 1px solid rgba(255,255,255,0.1); }}
    td {{ padding: 12px 16px; font-size: 0.9rem; border-bottom: 1px solid rgba(255,255,255,0.05); }}
    tr:last-child td {{ border-bottom: none; }}
    .col-name {{ font-weight: 500; color: #fff; }}
    .sample {{ color: rgba(255,255,255,0.4); font-family: monospace; font-size: 0.8rem; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

    select {{ width: 100%; padding: 10px 14px; font-size: 0.85rem; border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; background: rgba(255,255,255,0.05); color: #fff; cursor: pointer; -webkit-appearance: none; -moz-appearance: none; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='white' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; }}
    select:focus {{ outline: none; border-color: rgba(255,255,255,0.3); }}
    select option {{ background: #111; color: #fff; }}

    .options-box {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px 24px; margin-bottom: 24px; }}
    .options-title {{ font-weight: 600; font-size: 0.95rem; margin-bottom: 14px; }}
    .checkboxes {{ display: flex; gap: 32px; flex-wrap: wrap; }}
    .checkbox-label {{ display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 0.9rem; color: rgba(255,255,255,0.8); }}
    .checkbox-label input {{ width: 18px; height: 18px; accent-color: #4F46E5; }}

    .actions {{ display: flex; gap: 12px; margin-bottom: 24px; }}
    .btn {{ padding: 14px 28px; font-size: 0.95rem; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; transition: all 0.2s; text-align: center; text-decoration: none; }}
    .btn-back {{ flex: 1; background: transparent; border: 1px solid rgba(255,255,255,0.2); color: #fff; }}
    .btn-back:hover {{ border-color: rgba(255,255,255,0.4); }}
    .btn-primary {{ flex: 2; background: #fff; color: #000; }}
    .btn-primary:hover {{ opacity: 0.9; transform: translateY(-1px); }}

    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} .container {{ margin: 24px auto; }} .checkboxes {{ gap: 16px; }} }}
    </style>
</head>
<body>
{GTM_BODY}
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="nav-links">
            <a href="/batches/history" class="nav-link">Batch history</a>
            {_admin_nav_links(user_role=user_role)}
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
        </div>
    </nav>

    <div class="container">
        <h1 class="title"><span>&#9881;</span> Map your columns</h1>
        <p class="subtitle">
            We detected <strong>{len(csv_columns)}</strong> columns and <strong>{total_rows}</strong> rows in your CSV.
            Assign each column to the correct product field. Fields marked <em>-- skip --</em> will go into extra attributes.
        </p>

        <div class="actions">
            <a href="/upload" class="btn btn-back">&larr; Back</a>
            <button class="btn btn-primary" onclick="submitMappings()">Confirm & process &rarr;</button>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr><th>CSV Column</th><th>Sample data</th><th>Maps to field</th></tr>
                </thead>
                <tbody>{select_rows}</tbody>
            </table>
        </div>

        <div class="options-box">
            <p class="options-title">Which fields should AI optimize?</p>
            <div class="checkboxes">
                <label class="checkbox-label">
                    <input type="checkbox" id="opt_title" checked /> Optimize titles
                </label>
                <label class="checkbox-label">
                    <input type="checkbox" id="opt_desc" checked /> Optimize descriptions
                </label>
            </div>
        </div>

        <form id="confirm-form" method="post" action="/batches/confirm">
            <input type="hidden" name="upload_id" value="{upload_id}" />
            <input type="hidden" name="mode" value="{mode}" />
            <input type="hidden" name="target_language" value="{target_language}" />
            <input type="hidden" name="product_type" value="{product_type}" />
            <input type="hidden" id="mappings_json" name="mappings_json" value="" />
            <input type="hidden" id="optimize_fields" name="optimize_fields" value="title,description" />
        </form>
    </div>

    <script>
    function submitMappings(){{
        const selects=document.querySelectorAll("select");
        const mapping={{}}, used={{}};
        let hasTitle=false, hasId=false;
        selects.forEach(s=>{{
            const col=s.dataset.col, val=s.value;
            if(val){{
                if(used[val]){{alert('Field "'+val+'" is assigned to multiple columns.');return;}}
                used[val]=true; mapping[col]=val;
                if(val==="title")hasTitle=true;
                if(val==="id")hasId=true;
            }}
        }});
        if(!hasTitle){{alert("Please assign at least the Title field.");return;}}
        if(!hasId){{alert("Please assign at least the ID field.");return;}}
        document.getElementById("mappings_json").value=JSON.stringify(mapping);
        const fields=[];
        if(document.getElementById("opt_title").checked)fields.push("title");
        if(document.getElementById("opt_desc").checked)fields.push("description");
        if(!fields.length){{alert("Select at least one field to optimize.");return;}}
        document.getElementById("optimize_fields").value=fields.join(",");
        document.getElementById("confirm-form").submit();
    }}
    (function(){{
        const t=document.getElementById("themeToggle");
        if(t){{const k="hp-theme";function g(){{return localStorage.getItem(k)||"dark";}}function s(v){{document.documentElement.setAttribute("data-theme",v);localStorage.setItem(k,v);t.textContent=v==="dark"?"\u2600":"\u263E";}}t.onclick=()=>s(g()==="dark"?"light":"dark");s(g());}}
    }})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


@app.post("/batches", response_model=BatchSummary)
async def create_batch(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("optimize"),  # "optimize" or "translate"
    target_language: Optional[str] = Form(None),
    redirect: bool = Query(False),
):
    require_login_http(request)
    if file.content_type not in {"text/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=400, detail="Only CSV upload is supported in v1.")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")

    is_safe, security_error = validate_csv_content(text, len(content))
    if not is_safe:
        raise HTTPException(status_code=400, detail=security_error)

    records = parse_csv_file(io.StringIO(text))

    batch_id = str(uuid.uuid4())
    normalized_products: List[NormalizedProduct] = normalize_records(records)

    actions = decide_actions_for_products(normalized_products, mode=mode)
    u = get_current_user(request)
    owner_email = (u.get("email") or "").strip() if u else ""
    storage.create_batch(
        batch_id=batch_id,
        products=normalized_products,
        actions=actions,
        user_email=owner_email or None,
    )

    if target_language:
        storage.default_target_language = target_language
    storage.process_batch_synchronously(batch_id)

    if redirect:
        return RedirectResponse(url=f"/batches/{batch_id}/review", status_code=303)

    return storage.get_batch_summary(batch_id)


@app.get("/batches/history", response_class=HTMLResponse)
async def batches_history_page(request: Request):
    """All batches for the logged-in user (newest first). Must be registered before /batches/{batch_id} so 'history' is not captured as a batch id."""
    redir = require_login_redirect(request, "/batches/history")
    if redir:
        return redir
    user = get_current_user(request)
    email = (user.get("email") or "").strip() if user else ""
    user_role = user.get("role", "customer") if user else "customer"
    body_inner = _build_batch_history_html("", email)
    html = _wrap_batches_history_shell(
        page_title="Batch history",
        body_inner=body_inner,
        user_role=user_role,
    )
    return HTMLResponse(content=html)


@app.get("/batches/{batch_id}", response_model=BatchSummary)
def get_batch(request: Request, batch_id: str):
    require_login_http(request)
    batch = storage.get_batch(batch_id)
    _ensure_batch_owner_from_batch(request, batch)
    summary = storage.get_batch_summary(batch_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return summary


@app.get("/batches/{batch_id}/export")
async def export_batch(request: Request, batch_id: str):
    require_login_http(request)
    batch = storage.get_batch(batch_id)
    _ensure_batch_owner_from_batch(request, batch)

    _onboarding_export_done(request)

    csv_buffer = io.StringIO()
    generate_result_csv(batch, csv_buffer)
    csv_buffer.seek(0)

    return StreamingResponse(
        iter([csv_buffer.getvalue().encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="batch_{batch_id}.csv"'},
    )


@app.post("/batches/{batch_id}/regenerate", response_model=BatchSummary)
async def regenerate_batch_items(request: Request, batch_id: str, product_ids: List[str]):
    """
    Regenerate selected rows (by product_id) within an existing batch.
    Expects JSON body: ["id1", "id2", ...]
    """
    require_login_http(request)
    batch = storage.get_batch(batch_id)
    _ensure_batch_owner_from_batch(request, batch)

    storage.regenerate_products(batch_id, product_ids)
    return storage.get_batch_summary(batch_id)


@app.post("/batches/{batch_id}/update-product")
async def update_product_field(request: Request, batch_id: str, data: dict):
    """
    Update a single field of a product result.
    Expects JSON body: { "product_id": "...", "field": "...", "value": "..." }
    """
    require_login_http(request)
    batch = storage.get_batch(batch_id)
    _ensure_batch_owner_from_batch(request, batch)

    product_id = data.get("product_id")
    field = data.get("field")
    value = data.get("value", "")

    allowed_fields = {"optimized_title", "optimized_description", "translated_title", "translated_description"}
    if field not in allowed_fields:
        raise HTTPException(status_code=400, detail=f"Field '{field}' is not editable.")

    for result in batch.products:
        if result.product.id == product_id:
            setattr(result, field, value)
            storage._save_batch(batch)
            return {"status": "ok"}

    raise HTTPException(status_code=404, detail="Product not found.")


@app.post("/batches/{batch_id}/export-selected")
async def export_selected_products(request: Request, batch_id: str, product_ids: List[str]):
    """
    Export only selected products as CSV.
    Expects JSON body: ["id1", "id2", ...]
    """
    require_login_http(request)
    batch = storage.get_batch(batch_id)
    _ensure_batch_owner_from_batch(request, batch)

    # Filter to only selected products
    from .models import Batch as BatchModel
    selected_products = [r for r in batch.products if r.product.id in product_ids]
    
    if not selected_products:
        raise HTTPException(status_code=400, detail="No products selected.")

    _onboarding_export_done(request)

    # Create a temporary batch with only selected products
    filtered_batch = BatchModel(
        id=batch.id,
        status=batch.status,
        products=selected_products,
    )

    csv_buffer = io.StringIO()
    generate_result_csv(filtered_batch, csv_buffer)
    csv_buffer.seek(0)

    return StreamingResponse(
        iter([csv_buffer.getvalue().encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="selected_{batch_id[:8]}.csv"'},
    )


@app.post("/batches/{batch_id}/close")
async def close_batch(request: Request, batch_id: str):
    """Mark batch as closed (archived) for history status."""
    require_login_http(request)
    batch = storage.get_batch(batch_id)
    _ensure_batch_owner_from_batch(request, batch)
    from .db import get_db
    from .services.db_repository import mark_batch_closed

    with get_db() as db:
        mark_batch_closed(db, batch_id)
    return JSONResponse({"ok": True})


@app.get("/batches/{batch_id}/review", response_class=HTMLResponse)
async def review_batch(request: Request, batch_id: str):
    redir = require_login_redirect(request, f"/batches/{batch_id}/review")
    if redir:
        return redir
    batch = storage.get_batch(batch_id)
    user = get_current_user(request)
    _ensure_batch_owner_from_batch(request, batch)
    user_role = user.get("role", "customer") if user else "customer"
    batch_history_html = _build_batch_history_html(batch_id, (user.get("email") or "") if user else "")

    total = len(batch.products)
    from .models import ProductStatus as PS
    done = sum(1 for r in batch.products if r.status == PS.DONE)
    failed = sum(1 for r in batch.products if r.status == PS.FAILED)
    skipped = sum(1 for r in batch.products if r.status == PS.SKIPPED)
    review = sum(1 for r in batch.products if r.status == PS.NEEDS_REVIEW)

    scores = [r.score for r in batch.products if r.score > 0]
    avg_score = round(sum(scores) / len(scores)) if scores else 0

    gmc_err_count = sum(len(r.gmc_errors) for r in batch.products)
    gmc_warn_count = sum(len(r.gmc_warnings) for r in batch.products)
    gmc_products_with_errors = sum(1 for r in batch.products if r.gmc_errors)
    gmc_products_with_warnings = sum(1 for r in batch.products if r.gmc_warnings and not r.gmc_errors)
    gmc_products_clean = sum(1 for r in batch.products if not r.gmc_errors and not r.gmc_warnings and r.status.value != "skipped")
    # Error-free = no hard errors (warnings are recommendations, not failures)
    gmc_products_error_free = (total - skipped) - gmc_products_with_errors
    gmc_error_free_pct = round(gmc_products_error_free / (total - skipped) * 100) if (total - skipped) > 0 else 0
    gmc_products_pass = gmc_products_clean

    _ptype_labels = {
        "standard": "Standard", "custom": "Custom / Personalized",
        "handmade": "Handmade", "vintage": "Vintage / Antique",
        "private_label": "Private label", "bundle": "Bundles",
        "digital": "Digital / Software", "services": "Services",
        "promotional": "Promotional",
    }
    ptype_label = _ptype_labels.get(batch.product_type, batch.product_type)

    from collections import Counter
    _issue_counter: Counter = Counter()
    _issue_severity: dict = {}
    for r in batch.products:
        for e in r.gmc_errors:
            _issue_counter[e] += 1
            _issue_severity[e] = "error"
        for w in r.gmc_warnings:
            _issue_counter[w] += 1
            if w not in _issue_severity:
                _issue_severity[w] = "warn"
    top_issues = _issue_counter.most_common(5)

    import html as html_module

    top_issues_html = ""
    if top_issues:
        issue_items = ""
        for issue_text, count in top_issues:
            sev = _issue_severity.get(issue_text, "warn")
            icon = "&#10006;" if sev == "error" else "&#9888;"
            sev_cls = "gmc-ti-err" if sev == "error" else "gmc-ti-warn"
            issue_items += f'<li class="gmc-ti-item {sev_cls}"><span class="gmc-ti-icon">{icon}</span><span class="gmc-ti-text">{html_module.escape(issue_text)}</span><span class="gmc-ti-count">{count}</span></li>'
        top_issues_html = f'<div class="gmc-top-issues"><div class="gmc-ti-label">Most common issues found in your source CSV data</div><ul class="gmc-ti-list">{issue_items}</ul></div>'

    from .services.validator import validate_title, validate_description
    import re

    def _warning_items_for_row(r):
        """Merge error, GMC issues, and notes into deduplicated (severity, text) rows."""
        severity_by_text: dict = {}
        order: List[str] = []

        def bump(sev: str, text: object) -> None:
            t = (str(text) if text is not None else "").strip()
            if not t:
                return
            if t not in severity_by_text:
                order.append(t)
            prev = severity_by_text.get(t, "warn")
            if sev == "error" or prev == "error":
                severity_by_text[t] = "error"
            else:
                severity_by_text[t] = "warn"

        if r.error:
            bump("error", r.error)
        for e in r.gmc_errors:
            bump("error", e)
        for w in r.gmc_warnings:
            bump("warn", w)
        if r.notes:
            for part in re.split(r"[\n;|]+", r.notes):
                bump("warn", part)
        return [(severity_by_text[t], t) for t in order]

    rows_html = ""
    for r in batch.products:
        orig_sc = r.original_score
        sc = r.score
        improvement = sc - orig_sc
        if improvement > 0:
            score_cls = "score-high"
            score_cell = f'<span class="score-improve"><span class="score-old">{orig_sc}</span> → <span class="score {score_cls}">{sc}</span> <span class="score-delta">+{improvement}</span></span>'
        elif sc > 0:
            score_cls = "score-mid" if sc >= 50 else "score-low"
            score_cell = f'<span class="score {score_cls}">{sc}</span>'
        else:
            score_cell = ''
        
        # Action display - show what was done
        action_map = {
            "generate_new": "generated",
            "improve_existing": "improved",
            "translate": "translated",
            "skip": "skipped",
            "manual_review": "review",
        }
        action_display = action_map.get(r.action.value, r.action.value)
        action_cls = "action-done" if r.status.value == "done" else ""
        
        old_title_raw = r.product.title or ''
        old_title = html_module.escape(old_title_raw)[:80]
        new_title_raw = r.optimized_title or ''
        new_title = html_module.escape(new_title_raw)
        old_desc_raw = r.product.description or ''
        old_desc_full = html_module.escape(old_desc_raw)
        new_desc_raw = r.optimized_description or ''
        new_desc_full = html_module.escape(new_desc_raw)
        trans_title = html_module.escape(r.translated_title or '')
        trans_desc = html_module.escape(r.translated_description or '')
        product_url = r.product.url or ''
        link_cell = f'<a href="{product_url}" target="_blank" class="product-link" title="{product_url}">&#8599;</a>' if product_url else '<span class="no-link">—</span>'
        image_url = html_module.escape(r.product.image_url or '')
        image_cell = f'<a href="{image_url}" target="_blank" class="img-thumb-link" title="{image_url}"><img src="{image_url}" class="img-thumb" alt="" onerror="this.parentElement.innerHTML=\'—\'" /></a>' if image_url else '<span class="no-link">—</span>'

        # ── Per-field GMC validation (old vs new) ────────────────────
        old_title_issues = validate_title(old_title_raw)
        new_title_issues = validate_title(new_title_raw) if new_title_raw else []
        old_desc_issues = validate_description(old_desc_raw, old_title_raw)
        new_desc_issues = validate_description(new_desc_raw, new_title_raw) if new_desc_raw else []

        old_title_issue_keys = {m for _, m in old_title_issues}
        new_title_issue_keys = {m for _, m in new_title_issues}
        old_desc_issue_keys = {m for _, m in old_desc_issues}
        new_desc_issue_keys = {m for _, m in new_desc_issues}

        def _build_issue_tags(issues):
            parts = []
            for sev, msg in issues:
                cls = "gmc-tag-err" if sev == "error" else "gmc-tag-warn"
                icon = "&#10006;" if sev == "error" else "&#9888;"
                parts.append(f'<span class="gmc-tag {cls}">{icon} {html_module.escape(msg)}</span>')
            return "".join(parts)

        def _build_fixed_tags(old_issues, new_issue_keys):
            parts = []
            for _, msg in old_issues:
                if msg not in new_issue_keys:
                    parts.append(f'<span class="gmc-tag gmc-tag-fixed">&#10004; Fixed: {html_module.escape(msg)}</span>')
            return "".join(parts)

        old_title_tags = _build_issue_tags(old_title_issues)
        new_title_fixed = _build_fixed_tags(old_title_issues, new_title_issue_keys) if new_title_raw else ""
        new_title_remaining = _build_issue_tags(new_title_issues) if new_title_raw else ""
        old_desc_tags = _build_issue_tags(old_desc_issues)
        new_desc_fixed = _build_fixed_tags(old_desc_issues, new_desc_issue_keys) if new_desc_raw else ""
        new_desc_remaining = _build_issue_tags(new_desc_issues) if new_desc_raw else ""

        gmc_suffix_old_title = f'<div class="gmc-tags">{old_title_tags}</div>' if old_title_tags else ''
        gmc_suffix_new_title = f'<div class="gmc-tags">{new_title_fixed}{new_title_remaining}</div>' if (new_title_fixed or new_title_remaining) else ''
        gmc_suffix_old_desc = f'<div class="gmc-tags">{old_desc_tags}</div>' if old_desc_tags else ''
        gmc_suffix_new_desc = f'<div class="gmc-tags">{new_desc_fixed}{new_desc_remaining}</div>' if (new_desc_fixed or new_desc_remaining) else ''

        # ── Description cells with expand/collapse ───────────────────
        desc_preview_len = 120
        old_desc_short = old_desc_full[:desc_preview_len] + ('...' if len(old_desc_full) > desc_preview_len else '')
        
        if len(old_desc_raw) > desc_preview_len:
            old_desc_cell = f'<td class="desc-cell"><div class="desc-wrapper"><span class="desc-text" data-full="{html_module.escape(old_desc_raw)}">{old_desc_short}</span><button type="button" class="expand-btn" onclick="toggleDesc(this)"><span class="expand-icon">&#9660;</span> show more</button></div>{gmc_suffix_old_desc}</td>'
        else:
            old_desc_cell = f'<td>{old_desc_full or "—"}{gmc_suffix_old_desc}</td>'
        
        if len(new_desc_full) > desc_preview_len:
            new_desc_cell = f'<td class="desc-cell editable-wrap"><div class="desc-wrapper"><span class="desc-text editable-cell desc-collapsed" contenteditable="true" data-field="optimized_description" data-product="{r.product.id}">{new_desc_full}</span><button type="button" class="expand-btn" onclick="toggleDescEditable(this)"><span class="expand-icon">&#9660;</span> show more</button></div>{gmc_suffix_new_desc}</td>'
        else:
            new_desc_cell = f'<td class="editable-cell" contenteditable="true" data-field="optimized_description" data-product="{r.product.id}">{new_desc_full}</td>'
            if gmc_suffix_new_desc:
                new_desc_cell = f'<td><div class="cell-with-gmc"><span class="editable-cell" contenteditable="true" data-field="optimized_description" data-product="{r.product.id}">{new_desc_full}</span>{gmc_suffix_new_desc}</div></td>'
        
        if len(trans_desc) > desc_preview_len:
            trans_desc_cell = f'<td class="desc-cell editable-wrap"><div class="desc-wrapper"><span class="desc-text editable-cell desc-collapsed" contenteditable="true" data-field="translated_description" data-product="{r.product.id}">{trans_desc}</span><button type="button" class="expand-btn" onclick="toggleDescEditable(this)"><span class="expand-icon">&#9660;</span> show more</button></div></td>'
        else:
            trans_desc_cell = f'<td class="editable-cell" contenteditable="true" data-field="translated_description" data-product="{r.product.id}">{trans_desc}</td>'

        # ── GMC data attribute for row filter ────────────────────────
        gmc_errs = r.gmc_errors
        gmc_warns = r.gmc_warnings
        gmc_status = 'error' if gmc_errs else 'warn' if gmc_warns else 'pass'

        # ── Title cells with inline GMC tags ─────────────────────────
        old_title_cell = f'<td>{old_title}{gmc_suffix_old_title}</td>'
        if gmc_suffix_new_title:
            new_title_cell = f'<td><div class="cell-with-gmc"><span class="editable-cell" contenteditable="true" data-field="optimized_title" data-product="{r.product.id}">{new_title}</span>{gmc_suffix_new_title}</div></td>'
        else:
            new_title_cell = f'<td class="editable-cell" contenteditable="true" data-field="optimized_title" data-product="{r.product.id}">{new_title}</td>'

        warn_items = _warning_items_for_row(r)
        if not warn_items:
            warnings_cell = '<td class="warnings-cell"><span class="warnings-empty">—</span></td>'
        else:
            _pills = []
            for _sev, _txt in warn_items:
                _pcls = "warn-pill warn-pill--err" if _sev == "error" else "warn-pill warn-pill--warn"
                _pills.append(f'<span class="{_pcls}">{html_module.escape(_txt)}</span>')
            warnings_cell = f'<td class="warnings-cell"><div class="warnings-stack">{"".join(_pills)}</div></td>'

        rows_html += f"""
        <tr data-id="{r.product.id}" data-status="{r.status.value}" data-gmc="{gmc_status}">
            <td><input type="checkbox" name="product_id" value="{r.product.id}" /></td>
            {warnings_cell}
            <td class="img-cell">{image_cell}</td>
            <td class="link-cell">{link_cell}</td>
            {old_title_cell}
            {new_title_cell}
            {old_desc_cell}
            {new_desc_cell}
            <td class="editable-cell" contenteditable="true" data-field="translated_title" data-product="{r.product.id}">{trans_title}</td>
            {trans_desc_cell}
            <td class="score-cell col-sticky col-score">{score_cell}</td>
            <td class="col-sticky col-action"><span class="badge {action_cls}">{action_display}</span></td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Review &mdash; {batch_id[:8]}</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    [data-theme="light"] .nav {{ border-bottom-color: rgba(15,23,42,0.08); background: rgba(248,250,252,0.95); }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover {{ color: #0f172a; }}
    [data-theme="light"] .header .batch-id {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .btn-outline {{ border-color: rgba(15,23,42,0.2); color: #0f172a; }}
    [data-theme="light"] .btn-outline:hover {{ border-color: rgba(15,23,42,0.4); }}
    [data-theme="light"] .btn-primary {{ background: #0f172a; color: #fff; }}
    [data-theme="light"] .btn-primary:hover {{ background: #1e293b; }}
    [data-theme="light"] .btn-merchant-push {{ background: linear-gradient(135deg, #22D3EE 0%, #06b6d4 100%); color: #0a0a0a; box-shadow: 0 2px 14px rgba(6, 182, 212, 0.35); }}
    [data-theme="light"] .btn-merchant-push:hover {{ filter: brightness(0.97); box-shadow: 0 4px 18px rgba(6, 182, 212, 0.45); }}
    [data-theme="light"] .merchant-push-modal {{ background: #fff; border-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] .merchant-push-title {{ color: #0f172a; }}
    [data-theme="light"] .merchant-push-sub {{ color: rgba(15,23,42,0.55); }}
    [data-theme="light"] .merchant-push-body {{ color: rgba(15,23,42,0.85); }}
    [data-theme="light"] .review-summary-bar {{ background: rgba(255,255,255,0.85); border-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] .review-summary-lead {{ color: #0f172a; }}
    [data-theme="light"] .review-summary-lead strong {{ color: #0f172a; }}
    [data-theme="light"] .review-summary-meta {{ color: rgba(15,23,42,0.55); }}
    [data-theme="light"] .review-summary-meta strong {{ color: #334155; }}
    [data-theme="light"] .review-summary-meta .c-review {{ color: #b45309; }}
    [data-theme="light"] .review-summary-meta .c-fail {{ color: #dc2626; }}
    [data-theme="light"] .search {{ border-color: rgba(15,23,42,0.15); background-color: rgba(255,255,255,0.9); color: #0f172a; }}
    [data-theme="light"] .search::placeholder {{ color: rgba(15,23,42,0.4); }}
    [data-theme="light"] .search:focus {{ border-color: rgba(15,23,42,0.3); }}
    [data-theme="light"] .filter {{ border-color: rgba(15,23,42,0.15); background-color: rgba(255,255,255,0.9); color: #0f172a; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%230f172a' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; }}
    [data-theme="light"] .filter option {{ background: #fff; color: #0f172a; }}
    [data-theme="light"] .table-container {{ background: #fff; border-color: rgba(15,23,42,0.12); }}
    [data-theme="light"] th {{ color: rgba(15,23,42,0.5); background: rgba(15,23,42,0.04); border-bottom-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] th:hover {{ color: #0f172a; }}
    [data-theme="light"] td {{ border-bottom-color: rgba(15,23,42,0.06); color: #0f172a; }}
    [data-theme="light"] tr:nth-child(even) {{ background: rgba(15,23,42,0.02); }}
    [data-theme="light"] tr:hover {{ background: rgba(15,23,42,0.04); }}
    [data-theme="light"] .mono, [data-theme="light"] .note {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .new-content {{ color: #0f172a; }}
    [data-theme="light"] .product-link {{ background: rgba(15,23,42,0.1); color: #0f172a; }}
    [data-theme="light"] .product-link:hover {{ background: rgba(15,23,42,0.2); }}
    [data-theme="light"] .no-link {{ color: rgba(15,23,42,0.3); }}
    [data-theme="light"] .badge {{ background: rgba(15,23,42,0.08); color: rgba(15,23,42,0.8); }}
    [data-theme="light"] .pill-done {{ background: rgba(15,23,42,0.12); color: #0f172a; }}
    [data-theme="light"] .pill-needs_review {{ background: rgba(251,191,36,0.2); color: #b45309; }}
    [data-theme="light"] .pill-failed {{ background: rgba(239,68,68,0.15); color: #dc2626; }}
    [data-theme="light"] .pill-skipped {{ background: rgba(15,23,42,0.08); color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .score-high {{ background: rgba(15,23,42,0.15); color: #0f172a; }}
    [data-theme="light"] .score-mid {{ background: rgba(15,23,42,0.1); color: #0f172a; }}
    [data-theme="light"] .score-low {{ background: rgba(239,68,68,0.15); color: #dc2626; }}
    [data-theme="light"] .score-old {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .editable-cell:hover {{ background: rgba(15,23,42,0.04); border-color: rgba(15,23,42,0.15); }}
    [data-theme="light"] .editable-cell:focus {{ background: rgba(255,255,255,0.9); border-color: rgba(15,23,42,0.3); box-shadow: 0 0 0 2px rgba(15,23,42,0.1); }}
    [data-theme="light"] .expand-btn {{ color: #0f172a; background: rgba(15,23,42,0.08); border-color: rgba(15,23,42,0.2); }}
    [data-theme="light"] .expand-btn:hover {{ background: rgba(15,23,42,0.15); border-color: rgba(15,23,42,0.3); color: #0f172a; }}
    [data-theme="light"] .scroll-hint {{ color: rgba(15,23,42,0.5); background: rgba(15,23,42,0.03); border-top-color: rgba(15,23,42,0.06); }}
    [data-theme="light"] .scroll-arrow {{ background: rgba(255,255,255,0.9); color: #0f172a; border-color: rgba(15,23,42,0.2); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
    [data-theme="light"] .scroll-arrow:hover {{ background: #fff; }}
    [data-theme="light"] .table-wrap::-webkit-scrollbar-track {{ background: rgba(15,23,42,0.08); }}
    [data-theme="light"] .table-wrap::-webkit-scrollbar-thumb {{ background: rgba(15,23,42,0.25); }}
    [data-theme="light"] .table-wrap::-webkit-scrollbar-thumb:hover {{ background: rgba(15,23,42,0.4); }}
    [data-theme="light"] th.sorted-asc::after, [data-theme="light"] th.sorted-desc::after {{ color: #0f172a; }}
    [data-theme="light"] .feedback-overlay {{ background: rgba(255,255,255,0.5); }}
    [data-theme="light"] .feedback-stars span {{ color: rgba(15,23,42,0.2); }}
    [data-theme="light"] input[type="checkbox"] {{ accent-color: #0f172a; }}
    .nav {{ display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); position: sticky; top: 0; background: rgba(10,10,10,0.95); backdrop-filter: blur(10px); z-index: 100; }}
    .nav-logo img {{ height: 32px; }}
    .nav-logo .logo-light {{ display: block; filter: brightness(0) invert(1); }}
    .nav-logo .logo-dark {{ display: none; }}
    [data-theme="light"] .nav-logo .logo-light {{ display: none; }}
    [data-theme="light"] .nav-logo .logo-dark {{ display: block; filter: none; }}
    .theme-btn {{ display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: rgba(255,255,255,0.6); cursor: pointer; font-size: 1rem; transition: all 0.2s; }}
    .theme-btn:hover {{ color: #fff; background: rgba(255,255,255,0.08); }}
    [data-theme="light"] .theme-btn {{ border-color: rgba(15,23,42,0.15); color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .theme-btn:hover {{ color: #0f172a; background: rgba(15,23,42,0.06); }}
    .nav-links {{ display: flex; align-items: center; gap: 32px; }}
    .nav-link {{ color: rgba(255,255,255,0.6); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }}
    .nav-link:hover {{ color: #fff; }}

    .container {{ max-width: 1700px; margin: 0 auto; padding: 32px 48px; }}

    .header {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }}
    .header h1 {{ font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em; }}
    .header .batch-id {{ font-size: 0.85rem; color: rgba(255,255,255,0.4); font-family: monospace; margin-top: 4px; }}
    .header-actions {{ display: flex; gap: 10px; }}
    .btn {{ padding: 10px 18px; font-size: 0.85rem; font-weight: 500; border-radius: 6px; cursor: pointer; transition: all 0.2s; text-decoration: none; border: none; }}
    .btn-outline {{ background: transparent; border: 1px solid rgba(255,255,255,0.2); color: #fff; }}
    .btn-outline:hover {{ border-color: rgba(255,255,255,0.4); }}
    .btn-primary {{ background: #fff; color: #0a0a0a; }}
    .btn-primary:hover {{ background: #e5e5e5; }}
    .btn-merchant-push {{ background: linear-gradient(135deg, #22D3EE 0%, #06b6d4 100%); color: #0a0a0a; border: none; font-weight: 600; padding: 11px 20px; box-shadow: 0 2px 14px rgba(34, 211, 238, 0.35); }}
    .btn-merchant-push:hover {{ filter: brightness(1.06); box-shadow: 0 4px 20px rgba(34, 211, 238, 0.45); transform: translateY(-1px); }}
    .btn-merchant-push:disabled {{ opacity: 0.55; cursor: not-allowed; transform: none; box-shadow: none; }}
    .btn:focus-visible, .expand-btn:focus-visible {{ outline: 2px solid #fff; outline-offset: 2px; }}
    .btn-merchant-push:focus-visible {{ outline: 2px solid #22D3EE; outline-offset: 2px; }}

    .merchant-push-overlay {{ position: fixed; inset: 0; background: rgba(5, 8, 15, 0.72); backdrop-filter: blur(6px); z-index: 10000; display: none; align-items: center; justify-content: center; padding: 24px; opacity: 0; transition: opacity 0.28s ease; }}
    .merchant-push-overlay.visible {{ display: flex; opacity: 1; }}
    .merchant-push-modal {{ position: relative; background: rgba(18, 22, 32, 0.96); border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 36px 32px; max-width: 440px; width: 100%; box-shadow: 0 24px 64px rgba(0,0,0,0.45); }}
    .merchant-push-state {{ text-align: center; }}
    .merchant-push-state.is-hidden {{ display: none !important; }}
    .merchant-push-spinner {{ width: 56px; height: 56px; margin: 0 auto 20px; border: 3px solid rgba(255,255,255,0.12); border-top-color: #22D3EE; border-radius: 50%; animation: merchantSpin 0.9s linear infinite; }}
    @keyframes merchantSpin {{ to {{ transform: rotate(360deg); }} }}
    .merchant-push-title {{ font-size: 1.15rem; font-weight: 600; color: #fff; margin-bottom: 8px; }}
    .merchant-push-sub {{ font-size: 0.88rem; color: rgba(255,255,255,0.55); line-height: 1.45; }}
    .merchant-push-icon-ok {{ width: 56px; height: 56px; margin: 0 auto 16px; border-radius: 50%; background: linear-gradient(135deg, #22D3EE, #06b6d4); color: #0a0a0a; font-size: 28px; line-height: 56px; font-weight: 700; }}
    .merchant-push-icon-err {{ width: 56px; height: 56px; margin: 0 auto 16px; border-radius: 50%; background: rgba(239,68,68,0.2); color: #f87171; font-size: 26px; line-height: 56px; font-weight: 700; }}
    .merchant-push-icon-ok.is-hidden, .merchant-push-icon-err.is-hidden {{ display: none !important; }}
    .merchant-push-body {{ text-align: left; font-size: 0.82rem; line-height: 1.55; color: rgba(255,255,255,0.82); margin-top: 12px; max-height: 280px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; padding: 12px 14px; background: rgba(0,0,0,0.25); border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); }}
    .btn-merchant-gotit {{ width: 100%; margin-top: 20px; padding: 12px 18px; font-size: 0.95rem; font-weight: 600; border-radius: 10px; border: none; cursor: pointer; background: linear-gradient(135deg, #22D3EE 0%, #06b6d4 100%); color: #0a0a0a; transition: filter 0.2s, transform 0.15s; }}
    .btn-merchant-gotit:hover {{ filter: brightness(1.05); }}

    .review-summary-bar {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 14px; padding: 8px 12px; margin-bottom: 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; font-size: 0.78rem; line-height: 1.35; color: rgba(255,255,255,0.65); }}
    .review-summary-lead {{ color: rgba(255,255,255,0.92); font-weight: 600; }}
    .review-summary-lead strong {{ color: #fff; font-weight: 700; }}
    .review-summary-lead .m {{ opacity: 0.45; font-weight: 400; margin: 0 2px; }}
    .review-summary-meta {{ font-size: 0.72rem; color: rgba(255,255,255,0.48); text-transform: uppercase; letter-spacing: 0.04em; }}
    .review-summary-meta strong {{ font-weight: 700; font-size: 0.76rem; text-transform: none; letter-spacing: 0; margin-left: 3px; color: rgba(255,255,255,0.88); }}
    .review-summary-meta .m {{ opacity: 0.45; margin: 0 2px; font-weight: 400; }}
    .review-summary-meta .c-review {{ color: #fbbf24; }}
    .review-summary-meta .c-fail {{ color: #ef4444; }}

    .controls {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }}
    .controls-left {{ display: flex; gap: 12px; flex: 1; }}
    .search {{ flex: 1; max-width: 300px; padding: 10px 14px; font-size: 0.85rem; border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; background: rgba(255,255,255,0.05); color: #fff; }}
    .search::placeholder {{ color: rgba(255,255,255,0.4); }}
    .search:focus {{ outline: none; border-color: rgba(255,255,255,0.5); }}
    .search:focus-visible {{ outline: 2px solid rgba(255,255,255,0.5); outline-offset: 2px; }}
    .filter {{ padding: 10px 14px; font-size: 0.85rem; border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; background: rgba(255,255,255,0.05); color: #fff; cursor: pointer; -webkit-appearance: none; -moz-appearance: none; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='white' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 36px; }}
    .filter option {{ background: #111; color: #fff; }}

    .table-container {{ background: #111; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; overflow: hidden; position: relative; }}
    .table-wrap {{ overflow-x: scroll; scroll-behavior: smooth; cursor: grab; }}
    .table-wrap.dragging {{ cursor: grabbing; scroll-behavior: auto; user-select: none; }}
    .table-wrap::-webkit-scrollbar {{ height: 10px; }}
    .table-wrap::-webkit-scrollbar-track {{ background: rgba(255,255,255,0.08); border-radius: 5px; }}
    .table-wrap::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.25); border-radius: 5px; }}
    .table-wrap::-webkit-scrollbar-thumb:hover {{ background: rgba(255,255,255,0.4); }}
    .scroll-hint {{ text-align: center; padding: 8px; font-size: 0.75rem; color: rgba(255,255,255,0.4); background: rgba(255,255,255,0.02); border-top: 1px solid rgba(255,255,255,0.05); }}
    .scroll-hint.hidden {{ display: none; }}
    
    .feedback-overlay {{ position: fixed; inset: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); z-index: 9999; display: none; align-items: center; justify-content: center; padding: 24px; opacity: 0; transition: opacity 0.3s; }}
    .feedback-overlay.visible {{ display: flex; opacity: 1; }}
    .feedback-box {{ position: relative; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 32px; max-width: 420px; width: 100%; }}
    [data-theme="light"] .feedback-box {{ background: #fff; border-color: rgba(15,23,42,0.1); box-shadow: 0 24px 48px rgba(0,0,0,0.12); }}
    .feedback-box h3 {{ font-size: 1.1rem; font-weight: 600; margin-bottom: 8px; }}
    .feedback-box p {{ font-size: 0.9rem; color: rgba(255,255,255,0.6); margin-bottom: 20px; line-height: 1.5; }}
    [data-theme="light"] .feedback-box p {{ color: rgba(15,23,42,0.6); }}
    .feedback-box textarea {{ width: 100%; min-height: 100px; padding: 12px 14px; font-size: 0.9rem; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; background: rgba(255,255,255,0.05); color: #fff; resize: vertical; margin-bottom: 16px; font-family: inherit; }}
    [data-theme="light"] .feedback-box textarea {{ background: #f8fafc; border-color: rgba(15,23,42,0.15); color: #0f172a; }}
    .feedback-stars {{ display: flex; gap: 8px; margin-bottom: 20px; }}
    .feedback-stars span {{ font-size: 1.75rem; cursor: pointer; color: rgba(255,255,255,0.25); transition: color 0.2s; user-select: none; }}
    .feedback-stars span:hover, .feedback-stars span.filled {{ color: #fbbf24; }}
    .feedback-box .btn {{ width: 100%; padding: 14px; font-size: 0.95rem; font-weight: 600; border-radius: 8px; cursor: pointer; border: none; background: #4F46E5; color: #fff; }}
    .feedback-box .btn:hover {{ background: #4338ca; }}
    .feedback-thanks {{ display: none; text-align: center; padding: 20px 0; }}
    .feedback-thanks.visible {{ display: block; }}
    .feedback-form.hidden {{ display: none !important; }}
    
    .scroll-arrow {{ position: absolute; top: 50%; transform: translateY(-50%); width: 40px; height: 40px; border-radius: 50%; background: rgba(255,255,255,0.15); color: #fff; border: 1px solid rgba(255,255,255,0.2); cursor: pointer; z-index: 10; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; box-shadow: 0 4px 12px rgba(0,0,0,0.3); transition: all 0.2s; opacity: 0; visibility: hidden; }}
    .scroll-arrow:hover {{ background: rgba(255,255,255,0.25); transform: translateY(-50%) scale(1.1); }}
    .scroll-arrow.visible {{ opacity: 1; visibility: visible; }}
    .scroll-arrow-left {{ left: 12px; }}
    .scroll-arrow-right {{ right: 12px; }}
    .scroll-arrow-left::before {{ content: '←'; }}
    .scroll-arrow-right::before {{ content: '→'; }}
    
    table {{ width: 100%; border-collapse: separate; border-spacing: 0; min-width: 1800px; }}
    th {{ text-align: left; padding: 14px 16px; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: rgba(255,255,255,0.5); background: #161616; border-bottom: 2px solid rgba(255,255,255,0.1); cursor: pointer; white-space: nowrap; user-select: none; position: sticky; top: 0; }}
    th:hover {{ color: rgba(255,255,255,0.9); }}
    th.sorted-asc::after {{ content: ' ↑'; color: #fff; }}
    th.sorted-desc::after {{ content: ' ↓'; color: #fff; }}
    td {{ padding: 14px 16px; font-size: 0.85rem; border-bottom: 1px solid rgba(255,255,255,0.06); vertical-align: middle; line-height: 1.5; }}
    td:nth-child(5), td:nth-child(6), td:nth-child(7), td:nth-child(8), td:nth-child(9), td:nth-child(10) {{ max-width: 220px; }}
    td:nth-child(5), td:nth-child(6), td:nth-child(9) {{ overflow: hidden; text-overflow: ellipsis; }}
    .desc-cell {{ overflow: visible; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:nth-child(even) {{ background: rgba(255,255,255,0.015); }}
    tr:hover {{ background: rgba(255,255,255,0.04); }}
    .mono {{ font-family: 'SF Mono', Monaco, monospace; font-size: 0.75rem; color: rgba(255,255,255,0.5); }}
    .note {{ font-size: 0.78rem; color: rgba(255,255,255,0.4); max-width: 150px; }}
    th.th-warnings {{ text-align: center; }}
    .warnings-cell {{ vertical-align: middle; min-width: 160px; max-width: 320px; }}
    .warnings-stack {{
        display: flex; flex-direction: column; justify-content: center; gap: 6px; align-items: flex-start;
    }}
    .warnings-empty {{ color: rgba(255,255,255,0.25); font-size: 0.85rem; }}
    .warn-pill {{
        display: inline-block; padding: 6px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 600;
        line-height: 1.35; white-space: normal; word-break: break-word; text-align: left; max-width: 100%;
    }}
    .warn-pill--err {{
        background: rgba(239,68,68,0.28); color: #fecaca; border: 1px solid rgba(239,68,68,0.55);
        box-shadow: 0 1px 0 rgba(0,0,0,0.2);
    }}
    .warn-pill--warn {{
        background: rgba(245,158,11,0.22); color: #fde68a; border: 1px solid rgba(245,158,11,0.5);
        box-shadow: 0 1px 0 rgba(0,0,0,0.15);
    }}
    [data-theme="light"] .warnings-empty {{ color: rgba(15,23,42,0.35); }}
    [data-theme="light"] .warn-pill--err {{ background: rgba(254,226,226,0.95); color: #991b1b; border-color: rgba(220,38,38,0.45); }}
    [data-theme="light"] .warn-pill--warn {{ background: rgba(254,243,199,0.95); color: #92400e; border-color: rgba(217,119,6,0.45); }}
    .new-content {{ color: #fff; font-weight: 500; }}
    .th-center {{ text-align: center; }}
    .score-cell {{ text-align: center; white-space: nowrap; }}
    .link-cell {{ text-align: center; }}

    .col-sticky {{ position: sticky; z-index: 2; }}
    .col-action {{ right: 0; min-width: 110px; }}
    .col-score {{ right: 110px; min-width: 180px; }}
    th.col-sticky {{ z-index: 3; background: #161616; }}
    td.col-sticky {{ background: #111; }}
    tr:nth-child(even) td.col-sticky {{ background: #131313; }}
    tr:hover td.col-sticky {{ background: #1a1a1a; }}
    td.col-sticky, th.col-score {{ border-left: 1px solid rgba(255,255,255,0.08); }}
    [data-theme="light"] th.col-sticky {{ background: #f1f5f9; }}
    [data-theme="light"] td.col-sticky {{ background: #fff; }}
    [data-theme="light"] tr:nth-child(even) td.col-sticky {{ background: #f8fafc; }}
    [data-theme="light"] tr:hover td.col-sticky {{ background: #f1f5f9; }}
    [data-theme="light"] td.col-sticky, [data-theme="light"] th.col-score {{ border-left-color: rgba(15,23,42,0.08); }}
    .product-link {{ display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 6px; background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.9); text-decoration: none; font-size: 0.9rem; transition: all 0.2s; }}
    .product-link:hover {{ background: rgba(255,255,255,0.2); transform: scale(1.1); }}
    .no-link {{ color: rgba(255,255,255,0.2); }}

    .img-cell {{ text-align: center; width: 60px; padding: 8px !important; }}
    .img-thumb-link {{ display: inline-block; border-radius: 6px; overflow: hidden; transition: transform 0.2s; }}
    .img-thumb-link:hover {{ transform: scale(1.15); }}
    .img-thumb {{ width: 44px; height: 44px; object-fit: cover; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); display: block; }}
    [data-theme="light"] .img-thumb {{ background: rgba(15,23,42,0.04); border-color: rgba(15,23,42,0.1); }}

    .badge {{ display: inline-block; padding: 5px 10px; font-size: 0.68rem; font-weight: 600; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.04em; background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.7); }}
    .pill {{ display: inline-block; padding: 5px 12px; font-size: 0.68rem; font-weight: 700; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.03em; }}
    .pill-done {{ background: rgba(255,255,255,0.12); color: #e5e5e5; }}
    .pill-needs_review {{ background: rgba(251,191,36,0.15); color: #fbbf24; }}
    .pill-failed {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
    .pill-skipped {{ background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.5); }}

    .score {{ display: inline-block; padding: 5px 12px; font-size: 0.75rem; font-weight: 700; border-radius: 6px; min-width: 42px; text-align: center; }}
    .score-high {{ background: rgba(255,255,255,0.12); color: #fff; }}
    .score-mid {{ background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.85); }}
    .score-low {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
    
    .score-improve {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.75rem; white-space: nowrap; }}
    .score-old {{ color: rgba(255,255,255,0.4); font-weight: 500; }}
    .score-delta {{ color: #22c55e; font-weight: 600; font-size: 0.7rem; }}
    
    .editable-cell {{ cursor: text; border: 1px solid transparent; border-radius: 4px; padding: 8px 12px !important; transition: all 0.2s; min-width: 120px; max-width: 250px; }}
    .editable-cell:hover {{ background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.1); }}
    .editable-cell:focus {{ outline: none; background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.3); box-shadow: 0 0 0 2px rgba(255,255,255,0.1); }}
    .editable-cell.modified {{ background: rgba(34,197,94,0.08); border-color: rgba(34,197,94,0.3); }}
    .editable-cell.saving {{ opacity: 0.6; pointer-events: none; }}
    
    .desc-cell {{ max-width: 220px; vertical-align: top; }}
    .desc-wrapper {{ position: relative; padding: 0; }}
    .desc-wrapper .desc-text {{ display: block; font-size: 0.85rem; line-height: 1.5; word-break: break-word; padding: 8px 12px !important; }}
    .desc-wrapper .desc-text.desc-collapsed {{ display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
    .expand-btn {{ margin: 6px 0 0 12px; padding: 4px 10px; font-size: 0.7rem; font-weight: 600; color: rgba(255,255,255,0.9); background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; cursor: pointer; transition: all 0.2s; display: inline-flex; align-items: center; gap: 4px; }}
    .expand-btn:hover {{ background: rgba(255,255,255,0.15); border-color: rgba(255,255,255,0.3); color: #fff; }}
    .expand-btn:active {{ transform: scale(0.98); }}
    .expand-icon {{ font-size: 0.6rem; opacity: 0.9; }}
    
    .badge.action-done {{ background: rgba(34,197,94,0.15); color: #22c55e; }}

    input[type="checkbox"] {{ width: 18px; height: 18px; accent-color: #fff; cursor: pointer; }}

    /* GMC Validation Panel — horizontal compact layout */
    .gmc-panel {{ display: flex; align-items: center; gap: 24px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 16px 24px; margin-bottom: 20px; flex-wrap: wrap; }}
    .gmc-panel-left {{ display: flex; align-items: center; gap: 12px; flex-shrink: 0; }}
    .gmc-panel-icon {{ color: rgba(255,255,255,0.5); display: flex; align-items: center; }}
    .gmc-panel-title {{ font-size: 0.82rem; font-weight: 600; color: rgba(255,255,255,0.9); white-space: nowrap; }}
    .gmc-panel-subtitle {{ font-size: 0.72rem; color: rgba(255,255,255,0.4); margin-top: 2px; }}
    .gmc-panel-center {{ flex: 1; min-width: 0; }}
    .gmc-panel-bar {{ height: 6px; border-radius: 3px; background: rgba(255,255,255,0.06); display: flex; overflow: hidden; }}
    .gmc-bar-fill {{ height: 100%; transition: width 0.4s ease; }}
    .gmc-bar-pass {{ background: #22c55e; }}
    .gmc-bar-warn {{ background: #f59e0b; }}
    .gmc-bar-err {{ background: #ef4444; }}
    .gmc-legend {{ display: flex; gap: 16px; margin-top: 8px; }}
    .gmc-legend-item {{ display: inline-flex; align-items: center; gap: 5px; font-size: 0.72rem; color: rgba(255,255,255,0.55); }}
    .gmc-legend-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
    .gmc-dot-pass {{ background: #22c55e; }}
    .gmc-dot-warn {{ background: #f59e0b; }}
    .gmc-dot-err {{ background: #ef4444; }}
    .gmc-panel-right {{ flex-shrink: 0; }}
    .gmc-pass-ring {{ position: relative; width: 52px; height: 52px; }}
    .gmc-ring-svg {{ width: 100%; height: 100%; transform: rotate(-90deg); }}
    .gmc-ring-bg {{ fill: none; stroke: rgba(255,255,255,0.06); stroke-width: 3; }}
    .gmc-ring-fill {{ fill: none; stroke: #22c55e; stroke-width: 3; stroke-linecap: round; }}
    .gmc-ring-fill--warn {{ fill: none; stroke: #f59e0b; stroke-width: 3; stroke-linecap: round; }}
    .gmc-ring-label {{ position: absolute; top: 42%; left: 50%; transform: translate(-50%, -50%); font-size: 0.72rem; font-weight: 700; color: rgba(255,255,255,0.9); white-space: nowrap; }}
    .gmc-ring-sublabel {{ position: absolute; top: 62%; left: 50%; transform: translate(-50%, -50%); font-size: 0.55rem; color: rgba(255,255,255,0.4); white-space: nowrap; }}

    /* Inline GMC tags inside title/description cells */
    .gmc-tags {{ display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }}
    .gmc-tag {{ display: inline-flex; align-items: center; gap: 3px; padding: 2px 8px; border-radius: 4px; font-size: 0.68rem; font-weight: 600; line-height: 1.4; white-space: nowrap; }}
    .gmc-tag-err {{ background: rgba(239,68,68,0.12); color: #ef4444; }}
    .gmc-tag-warn {{ background: rgba(245,158,11,0.12); color: #f59e0b; }}
    .gmc-tag-fixed {{ background: rgba(34,197,94,0.12); color: #22c55e; }}
    .cell-with-gmc {{ display: flex; flex-direction: column; }}

    /* Top issues list inside GMC panel */
    .gmc-top-issues {{ width: 100%; border-top: 1px solid rgba(255,255,255,0.06); margin-top: 4px; padding-top: 12px; }}
    .gmc-ti-label {{ font-size: 0.72rem; font-weight: 600; color: rgba(255,255,255,0.45); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
    .gmc-ti-list {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }}
    .gmc-ti-item {{ display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 6px; background: rgba(255,255,255,0.02); font-size: 0.8rem; }}
    .gmc-ti-icon {{ flex-shrink: 0; font-size: 0.7rem; width: 16px; text-align: center; }}
    .gmc-ti-text {{ flex: 1; color: rgba(255,255,255,0.8); }}
    .gmc-ti-count {{ flex-shrink: 0; font-size: 0.72rem; font-weight: 700; padding: 1px 8px; border-radius: 10px; background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.6); }}
    .gmc-ti-err .gmc-ti-icon {{ color: #ef4444; }}
    .gmc-ti-err .gmc-ti-count {{ background: rgba(239,68,68,0.12); color: #ef4444; }}
    .gmc-ti-warn .gmc-ti-icon {{ color: #f59e0b; }}
    .gmc-ti-warn .gmc-ti-count {{ background: rgba(245,158,11,0.12); color: #f59e0b; }}

    /* Light theme GMC */
    [data-theme="light"] .gmc-panel {{ background: rgba(255,255,255,0.8); border-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] .gmc-panel-icon {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .gmc-panel-title {{ color: #0f172a; }}
    [data-theme="light"] .gmc-panel-subtitle {{ color: rgba(15,23,42,0.45); }}
    [data-theme="light"] .gmc-panel-bar {{ background: rgba(15,23,42,0.08); }}
    [data-theme="light"] .gmc-legend-item {{ color: rgba(15,23,42,0.55); }}
    [data-theme="light"] .gmc-ring-bg {{ stroke: rgba(15,23,42,0.08); }}
    [data-theme="light"] .gmc-ring-label {{ color: #0f172a; }}
    [data-theme="light"] .gmc-ring-sublabel {{ color: rgba(15,23,42,0.4); }}
    [data-theme="light"] .gmc-tag-err {{ background: rgba(239,68,68,0.1); }}
    [data-theme="light"] .gmc-tag-warn {{ background: rgba(245,158,11,0.1); }}
    [data-theme="light"] .gmc-tag-fixed {{ background: rgba(34,197,94,0.1); }}
    [data-theme="light"] .gmc-top-issues {{ border-top-color: rgba(15,23,42,0.08); }}
    [data-theme="light"] .gmc-ti-label {{ color: rgba(15,23,42,0.45); }}
    [data-theme="light"] .gmc-ti-item {{ background: rgba(15,23,42,0.02); }}
    [data-theme="light"] .gmc-ti-text {{ color: rgba(15,23,42,0.8); }}
    [data-theme="light"] .gmc-ti-count {{ background: rgba(15,23,42,0.06); color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .gmc-ti-err .gmc-ti-count {{ background: rgba(239,68,68,0.1); color: #ef4444; }}
    [data-theme="light"] .gmc-ti-warn .gmc-ti-count {{ background: rgba(245,158,11,0.1); color: #f59e0b; }}

    .batch-history {{ margin-bottom: 28px; padding: 20px 22px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.02); }}
    .batch-history-title {{ font-size: 1rem; font-weight: 600; margin-bottom: 14px; color: rgba(255,255,255,0.95); }}
    .batch-history-scroll {{ overflow-x: auto; }}
    .batch-history-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; min-width: 520px; }}
    .batch-history-table th {{ text-align: left; padding: 10px 12px; color: rgba(255,255,255,0.45); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.68rem; border-bottom: 1px solid rgba(255,255,255,0.08); }}
    .batch-history-table td {{ padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: middle; }}
    .batch-history-row--current {{ background: rgba(34,211,238,0.06); }}
    .batch-history-link {{ color: #22D3EE; font-weight: 600; text-decoration: none; }}
    .batch-history-link:hover {{ text-decoration: underline; }}
    .batch-history-meta {{ color: rgba(255,255,255,0.5); white-space: nowrap; }}
    .batch-history-pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 600; }}
    .batch-history-pill--closed {{ background: rgba(148,163,184,0.2); color: #e2e8f0; }}
    .batch-history-pill--sent {{ background: rgba(34,211,238,0.15); color: #67e8f9; }}
    .batch-history-pill--pending {{ background: rgba(245,158,11,0.2); color: #fde68a; }}
    .batch-history-pill--new {{ background: rgba(99,102,241,0.2); color: #c7d2fe; }}
    .batch-history-actions {{ white-space: nowrap; }}
    .batch-history-actions .btn {{ margin-left: 6px; }}
    .batch-history-hint {{ font-size: 0.78rem; color: rgba(255,255,255,0.4); margin-top: 12px; margin-bottom: 0; line-height: 1.45; }}
    .btn-sm {{ padding: 6px 12px; font-size: 0.75rem; }}
    [data-theme="light"] .batch-history {{ background: rgba(255,255,255,0.9); border-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] .batch-history-title {{ color: #0f172a; }}
    [data-theme="light"] .batch-history-table th {{ color: rgba(15,23,42,0.45); border-bottom-color: rgba(15,23,42,0.08); }}
    [data-theme="light"] .batch-history-table td {{ border-bottom-color: rgba(15,23,42,0.06); }}
    [data-theme="light"] .batch-history-row--current {{ background: rgba(34,211,238,0.1); }}
    [data-theme="light"] .batch-history-meta {{ color: rgba(15,23,42,0.55); }}
    [data-theme="light"] .batch-history-hint {{ color: rgba(15,23,42,0.5); }}
    .batch-history-empty {{ font-size: 0.88rem; color: rgba(255,255,255,0.55); line-height: 1.5; }}
    .batch-history-empty-link {{ color: #22D3EE; text-decoration: none; }}
    .batch-history-empty-link:hover {{ text-decoration: underline; }}
    [data-theme="light"] .batch-history-empty {{ color: rgba(15,23,42,0.55); }}

    .review-tabs {{ margin-bottom: 0; }}
    .review-tabs-bar {{ display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 0; }}
    .review-tab {{ border: none; background: transparent; color: rgba(255,255,255,0.5); font-size: 0.85rem; font-weight: 600; padding: 10px 14px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; font-family: inherit; }}
    .review-tab.is-active {{ color: #fff; border-bottom-color: #22D3EE; }}
    .review-tab:hover {{ color: rgba(255,255,255,0.9); }}
    .review-tab-aux {{ margin-left: auto; font-size: 0.8rem; color: #22D3EE; text-decoration: none; }}
    .review-tab-aux:hover {{ text-decoration: underline; }}
    .review-tab-panel[hidden] {{ display: none !important; }}
    [data-theme="light"] .review-tab {{ color: rgba(15,23,42,0.45); }}
    [data-theme="light"] .review-tab.is-active {{ color: #0f172a; border-bottom-color: #22D3EE; }}

    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} .container {{ padding: 24px; }} .gmc-panel {{ flex-direction: column; align-items: stretch; }} .gmc-legend {{ flex-wrap: wrap; gap: 8px; }} .review-tab-aux {{ margin-left: 0; width: 100%; padding: 4px 14px 10px; }} }}
    </style>
</head>
<body>
{GTM_BODY}
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="nav-links">
            <a href="/batches/history" class="nav-link">Batch history</a>
            {_admin_nav_links(user_role=user_role)}
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
        </div>
    </nav>

    <div class="container">
        <div class="header">
            <div>
                <h1>Batch review</h1>
                <p class="batch-id">ID: {batch_id}</p>
            </div>
            <div class="header-actions">
                <a href="/upload" class="btn btn-outline">&larr; New batch</a>
                <button type="button" onclick="pushToMerchant()" class="btn btn-merchant-push" id="merchantPushBtn">Push to Merchant</button>
                <button onclick="downloadSelected()" class="btn btn-primary">&#8681; Download selected</button>
                <button type="button" onclick="downloadAll()" class="btn btn-outline">&#8681; Download all</button>
            </div>
        </div>

        <div class="review-tabs">
        <div class="review-tabs-bar" role="tablist" aria-label="Batch views">
            <button type="button" class="review-tab is-active" role="tab" aria-selected="true" aria-controls="review-panel-current" id="tab-review-current" data-panel="review-panel-current">Current batch</button>
            <button type="button" class="review-tab" role="tab" aria-selected="false" aria-controls="review-panel-history" id="tab-review-history" data-panel="review-panel-history">Batch history</button>
            <a class="review-tab-aux" href="/batches/history">Open full page</a>
        </div>
        <div id="review-panel-current" class="review-tab-panel" role="tabpanel" aria-labelledby="tab-review-current">

        <div class="review-summary-bar" role="region" aria-label="Optimization summary">
            <span class="review-summary-lead">&#9889; <strong>{done}</strong>/<strong>{total}</strong> optimized <span class="m">&middot;</span> avg <strong>{avg_score}</strong>/100</span>
            <span class="review-summary-meta">
                Total <strong>{total}</strong><span class="m">&middot;</span>
                Done <strong>{done}</strong><span class="m">&middot;</span>
                Review <strong class="c-review">{review}</strong><span class="m">&middot;</span>
                Failed <strong class="c-fail">{failed}</strong><span class="m">&middot;</span>
                Skipped <strong>{skipped}</strong>
            </span>
        </div>

        <div class="gmc-panel">
            <div class="gmc-panel-left">
                <div class="gmc-panel-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>
                </div>
                <div>
                    <div class="gmc-panel-title">GMC Validation</div>
                    <div class="gmc-panel-subtitle">{gmc_err_count} errors, {gmc_warn_count} warnings across {total - skipped} products &middot; {ptype_label}</div>
                </div>
            </div>
            <div class="gmc-panel-center">
                <div class="gmc-panel-bar">
                    <div class="gmc-bar-fill gmc-bar-pass" style="width:{round(gmc_products_clean / (total - skipped) * 100) if (total - skipped) > 0 else 0}%"></div>
                    <div class="gmc-bar-fill gmc-bar-warn" style="width:{round(gmc_products_with_warnings / (total - skipped) * 100) if (total - skipped) > 0 else 0}%"></div>
                    <div class="gmc-bar-fill gmc-bar-err" style="width:{round(gmc_products_with_errors / (total - skipped) * 100) if (total - skipped) > 0 else 0}%"></div>
                </div>
                <div class="gmc-legend">
                    <span class="gmc-legend-item"><span class="gmc-legend-dot gmc-dot-pass"></span> {gmc_products_clean} clean</span>
                    <span class="gmc-legend-item"><span class="gmc-legend-dot gmc-dot-warn"></span> {gmc_products_with_warnings} warnings only</span>
                    <span class="gmc-legend-item"><span class="gmc-legend-dot gmc-dot-err"></span> {gmc_products_with_errors} errors</span>
                </div>
            </div>
            <div class="gmc-panel-right">
                <div class="gmc-pass-ring" title="Error-free rate: {gmc_error_free_pct}% of products have no hard errors">
                    <svg viewBox="0 0 36 36" class="gmc-ring-svg">
                        <path class="gmc-ring-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                        <path class="gmc-ring-fill{'--warn' if gmc_products_with_errors == 0 and gmc_products_with_warnings > 0 else ''}" stroke-dasharray="{gmc_error_free_pct}, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                    </svg>
                    <div class="gmc-ring-label">{gmc_error_free_pct}%</div>
                    <div class="gmc-ring-sublabel">error-free</div>
                </div>
            </div>
            {top_issues_html}
        </div>

        <div class="controls">
            <div class="controls-left">
                <input id="search" class="search" placeholder="Search products..." oninput="applyFilters()" />
                <select id="statusFilter" class="filter" onchange="applyFilters()">
                    <option value="">All statuses</option>
                    <option value="done">Done</option>
                    <option value="needs_review">Needs review</option>
                    <option value="failed">Failed</option>
                    <option value="skipped">Skipped</option>
                </select>
                <select id="gmcFilter" class="filter" onchange="applyFilters()">
                    <option value="">All GMC</option>
                    <option value="pass">&#10004; Passed</option>
                    <option value="warn">&#9888; Warnings</option>
                    <option value="error">&#10006; Errors</option>
                </select>
            </div>
            <button type="submit" form="regen-form" class="btn btn-primary">&#x21bb; Regenerate selected</button>
        </div>

        <div class="table-container" id="tableContainer">
            <button class="scroll-arrow scroll-arrow-left" id="scrollLeft" onclick="scrollTableLeft()"></button>
            <button class="scroll-arrow scroll-arrow-right" id="scrollRight" onclick="scrollTableRight()"></button>
            <div class="table-wrap" id="tableWrap">
                <form id="regen-form" onsubmit="submitRegenerate(event)">
                    <table>
                        <thead>
                            <tr>
                                <th style="width:40px;"><input type="checkbox" onclick="toggleAll(this)" /></th>
                                <th onclick="sortTable(1)" class="th-warnings">Warnings</th>
                                <th style="width:60px;" class="th-center">Image</th>
                                <th style="width:50px;" class="th-center">Link</th>
                                <th onclick="sortTable(4)">Old title</th>
                                <th onclick="sortTable(5)">New title</th>
                                <th onclick="sortTable(6)">Old description</th>
                                <th onclick="sortTable(7)">New description</th>
                                <th onclick="sortTable(8)">Translated title</th>
                                <th onclick="sortTable(9)">Translated desc</th>
                                <th onclick="sortTable(10)" class="th-center col-sticky col-score">Score</th>
                                <th onclick="sortTable(11)" class="th-center col-sticky col-action">Action</th>
                            </tr>
                        </thead>
                        <tbody>{rows_html}</tbody>
                    </table>
                </form>
            </div>
            <div class="scroll-hint" id="scrollHint">&#8596; Scroll horizontally to see all columns</div>
        </div>
        </div>
        <div id="review-panel-history" class="review-tab-panel" role="tabpanel" aria-labelledby="tab-review-history" hidden>
            {batch_history_html}
        </div>
        </div>
    </div>

    <script>
    (function(){{
        var tabs = document.querySelectorAll(".review-tab[data-panel]");
        var panels = document.querySelectorAll(".review-tab-panel");
        function activate(id) {{
            tabs.forEach(function(t) {{
                var on = t.getAttribute("data-panel") === id;
                t.classList.toggle("is-active", on);
                t.setAttribute("aria-selected", on ? "true" : "false");
            }});
            panels.forEach(function(p) {{
                var show = p.id === id;
                if (show) {{ p.removeAttribute("hidden"); }} else {{ p.setAttribute("hidden", ""); }}
            }});
        }}
        tabs.forEach(function(btn) {{
            btn.addEventListener("click", function() {{
                activate(btn.getAttribute("data-panel"));
            }});
        }});
    }})();
    function applyFilters(){{
        const s=document.getElementById("search").value.toLowerCase();
        const f=document.getElementById("statusFilter").value;
        const g=document.getElementById("gmcFilter").value;
        document.querySelectorAll("tbody tr").forEach(row=>{{
            const text=row.innerText.toLowerCase();
            const st=row.dataset.status||"";
            const gmc=row.dataset.gmc||"";
            row.style.display=((!s||text.includes(s))&&(!f||st===f)&&(!g||gmc===g))?"":"none";
        }});
    }}
    let sortCol=-1, sortAsc=true;
    const numericCols=new Set([10]);
    function sortTable(colIdx){{
        const tbody=document.querySelector("tbody");
        const rows=Array.from(tbody.querySelectorAll("tr"));
        if(sortCol===colIdx)sortAsc=!sortAsc;else{{sortCol=colIdx;sortAsc=true;}}
        rows.sort((a,b)=>{{
            const aT=(a.children[colIdx]||{{}}).textContent||"";
            const bT=(b.children[colIdx]||{{}}).textContent||"";
            if(numericCols.has(colIdx)){{const aN=parseFloat(aT)||0,bN=parseFloat(bT)||0;return sortAsc?aN-bN:bN-aN;}}
            return sortAsc?aT.localeCompare(bT):bT.localeCompare(aT);
        }});
        rows.forEach(r=>tbody.appendChild(r));
        document.querySelectorAll("th").forEach((th,i)=>{{th.classList.remove("sorted-asc","sorted-desc");if(i===colIdx)th.classList.add(sortAsc?"sorted-asc":"sorted-desc");}});
    }}
    async function submitRegenerate(e){{
        e.preventDefault();
        const ids=Array.from(document.querySelectorAll("input[name='product_id']:checked")).map(c=>c.value);
        if(!ids.length){{alert("Select at least one product.");return;}}
        const r=await fetch("/batches/{batch_id}/regenerate",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(ids)}});
        if(!r.ok){{alert("Regeneration failed.");return;}}
        window.location.reload();
    }}
    function toggleAll(src){{document.querySelectorAll("input[name='product_id']").forEach(c=>c.checked=src.checked);}}
    
    // Description expand/collapse
    function toggleDesc(btn) {{
        const wrapper = btn.closest('.desc-wrapper');
        const textEl = wrapper.querySelector('.desc-text');
        const full = textEl.dataset.full || '';
        const isExpanded = btn.classList.contains('expanded');
        
        if (isExpanded) {{
            const short = full.length > 120 ? full.substring(0, 120) + '...' : full;
            textEl.textContent = short;
            btn.innerHTML = '<span class="expand-icon">&#9660;</span> show more';
            btn.classList.remove('expanded');
        }} else {{
            textEl.textContent = full;
            btn.innerHTML = '<span class="expand-icon">&#9650;</span> show less';
            btn.classList.add('expanded');
        }}
    }}
    
    function toggleDescEditable(btn) {{
        const wrapper = btn.closest('.desc-wrapper');
        const textEl = wrapper.querySelector('.desc-text');
        const isExpanded = btn.classList.contains('expanded');
        
        if (isExpanded) {{
            textEl.classList.add('desc-collapsed');
            btn.innerHTML = '<span class="expand-icon">&#9660;</span> show more';
            btn.classList.remove('expanded');
        }} else {{
            textEl.classList.remove('desc-collapsed');
            btn.innerHTML = '<span class="expand-icon">&#9650;</span> show less';
            btn.classList.add('expanded');
        }}
    }}
    
    // Editable cells functionality
    const editableCells = document.querySelectorAll('.editable-cell');
    const originalValues = new Map();
    
    editableCells.forEach(cell => {{
        originalValues.set(cell, cell.textContent);
        
        cell.addEventListener('focus', function() {{
            this.dataset.original = this.textContent;
        }});
        
        cell.addEventListener('blur', async function() {{
            const newValue = this.textContent.trim();
            const originalValue = this.dataset.original || '';
            
            if (newValue !== originalValue) {{
                this.classList.add('saving');
                const productId = this.dataset.product;
                const field = this.dataset.field;
                
                try {{
                    const resp = await fetch('/batches/{batch_id}/update-product', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ product_id: productId, field: field, value: newValue }})
                    }});
                    
                    if (resp.ok) {{
                        this.classList.add('modified');
                        this.classList.remove('saving');
                    }} else {{
                        alert('Failed to save changes');
                        this.textContent = originalValue;
                        this.classList.remove('saving');
                    }}
                }} catch (e) {{
                        alert('Failed to save changes');
                    this.textContent = originalValue;
                    this.classList.remove('saving');
                }}
            }}
        }});
        
        cell.addEventListener('keydown', function(e) {{
            if (e.key === 'Enter' && !e.shiftKey) {{
                e.preventDefault();
                this.blur();
            }}
            if (e.key === 'Escape') {{
                this.textContent = this.dataset.original || '';
                this.blur();
            }}
        }});
    }});
    
    function merchantPushCloseOverlay() {{
        var ov = document.getElementById("merchantPushOverlay");
        if (ov) {{ ov.classList.remove("visible"); ov.setAttribute("aria-hidden", "true"); }}
    }}
    function merchantPushShowLoading() {{
        var ov = document.getElementById("merchantPushOverlay");
        var loadEl = document.getElementById("merchantPushLoading");
        var resEl = document.getElementById("merchantPushResult");
        if (loadEl) loadEl.classList.remove("is-hidden");
        if (resEl) resEl.classList.add("is-hidden");
        if (ov) {{ ov.classList.add("visible"); ov.setAttribute("aria-hidden", "false"); }}
    }}
    function merchantPushShowResult(isError, title, bodyText) {{
        var loadEl = document.getElementById("merchantPushLoading");
        var resEl = document.getElementById("merchantPushResult");
        var titleEl = document.getElementById("merchantPushResultTitle");
        var bodyEl = document.getElementById("merchantPushResultBody");
        var iconOk = document.getElementById("merchantPushIconOk");
        var iconErr = document.getElementById("merchantPushIconErr");
        if (loadEl) loadEl.classList.add("is-hidden");
        if (resEl) resEl.classList.remove("is-hidden");
        if (titleEl) titleEl.textContent = title || (isError ? "Could not upload" : "Upload finished");
        if (bodyEl) bodyEl.textContent = bodyText || "";
        if (iconOk) iconOk.classList.toggle("is-hidden", !!isError);
        if (iconErr) iconErr.classList.toggle("is-hidden", !isError);
        var gBtn = document.getElementById("merchantPushGotIt");
        if (gBtn) gBtn.onclick = function() {{ merchantPushCloseOverlay(); }};
    }}

    async function pushToMerchant() {{
        const btn = document.getElementById("merchantPushBtn");
        const checked = Array.from(document.querySelectorAll("input[name='product_id']:checked")).map(function(c) {{ return c.value; }});
        let payload;
        if (checked.length) {{
            payload = {{ product_ids: checked }};
        }} else {{
            if (!confirm("No rows selected. Push ALL products in this batch to your linked Google Merchant Center account?")) return;
            payload = {{}};
        }}
        if (btn) btn.disabled = true;
        merchantPushShowLoading();
        try {{
            const r = await fetch("/api/batches/{batch_id}/merchant-push", {{
                method: "POST",
                headers: {{
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }},
                credentials: "same-origin",
                body: JSON.stringify(payload)
            }});
            const raw = await r.text();
            let data = {{}};
            try {{ data = raw ? JSON.parse(raw) : {{}}; }} catch (e) {{ data = {{}}; }}
            if (!r.ok) {{
                let msg = "";
                if (typeof data.detail === "string") msg = data.detail;
                else if (Array.isArray(data.detail)) msg = data.detail.map(function(x){{ return (x.msg || x.type || "") + (x.loc ? " " + x.loc.join(".") : ""); }}).filter(Boolean).join("\\n");
                else if (data.detail != null) msg = JSON.stringify(data.detail);
                if (!msg && raw) msg = raw.length < 1200 ? raw : raw.slice(0, 1200) + "…";
                if (!msg) msg = "HTTP " + r.status;
                merchantPushShowResult(true, "Could not upload", msg);
                return;
            }}
            const line = "Inserted " + (data.inserted||0) + ", skipped " + (data.skipped||0) + ", failed " + (data.failed||0);
            var tips = [];
            var bodyLines = [line];
            if (data.merchant_id) {{ bodyLines.push("Merchant ID: " + data.merchant_id); }}
            if (data.feed_label || data.content_language) {{
                bodyLines.push("Feed: " + (data.feed_label||"") + " · Language: " + (data.content_language||"") + " · Country: " + (data.target_country||""));
            }}
            if (data.data_source) bodyLines.push("Data source: " + data.data_source);
            if (data.processing_note) bodyLines.push(data.processing_note);
            var ex = (data.details||[]).filter(function(x){{ return x.merchant_resource_name; }}).slice(0, 6).map(function(x){{ return x.merchant_resource_name; }});
            if (ex.length) bodyLines.push("productInput names (Google):\\n" + ex.join("\\n"));
            var mapi = data.merchant_products_api;
            if (mapi && typeof mapi === "object") {{
                if (mapi.count_on_page != null) bodyLines.push("Processed products (API, first page): " + mapi.count_on_page + (mapi.has_more ? " (more pages)" : ""));
                if (mapi.sample_product_names && mapi.sample_product_names.length) bodyLines.push("Sample: " + mapi.sample_product_names.slice(0,3).join(" · "));
                if (mapi.error) bodyLines.push("products.list: " + mapi.error);
            }}
            var ver = data.merchant_verification;
            if (ver && typeof ver === "object") {{
                if (ver.list_error) bodyLines.push("Verification error: " + ver.list_error);
                if (ver.expected != null && ver.expected > 0) {{
                    bodyLines.push("Catalog match: " + (ver.found_in_catalog||0) + " / " + ver.expected + " offerIds found in Merchant processed catalog (products.list).");
                    if (ver.note) bodyLines.push(ver.note);
                    if (ver.catalog_match_complete) bodyLines.push("Check: all pushed offerIds appear in the API catalog for this merchant.");
                    else if (ver.not_yet_in_catalog && ver.not_yet_in_catalog.length) bodyLines.push("Still processing (sample offerIds): " + ver.not_yet_in_catalog.slice(0, 8).join(", "));
                }}
            }}
            if (data.skipped > 0 && data.details && data.details.length) {{
                var skips = data.details.filter(function(x){{ return x.status === "skipped"; }}).slice(0, 20).map(function(x){{ return x.product_id + ": " + (x.reason || "skipped"); }}).join("\\n");
                if (skips) bodyLines.push("\\nSkipped rows:\\n" + skips);
            }}
            if (data.failed > 0 && data.details && data.details.length) {{
                var errs = data.details.filter(function(x){{ return x.status === "error"; }}).slice(0, 12).map(function(x){{ return x.product_id + ": " + (x.message||""); }}).join("\\n");
                if (errs) bodyLines.push("\\nAPI errors:\\n" + errs);
            }}
            var okTitle = ((data.failed||0) > 0) ? "Finished with issues" : "Upload finished";
            merchantPushShowResult(false, okTitle, bodyLines.join("\\n\\n"));
        }} catch (e) {{
            merchantPushShowResult(true, "Could not upload", (e && e.message) ? String(e.message) : "Network error.");
        }} finally {{
            if (btn) btn.disabled = false;
        }}
    }}

    // Download all products (fetch + blob to stay on page, no navigation)
    async function downloadAll() {{
        try {{
            const resp = await fetch('/batches/{batch_id}/export');
            if (!resp.ok) {{ alert('Failed to download'); return; }}
            const blob = await resp.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'batch_{batch_id}.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }} catch (e) {{ alert('Download failed'); }}
    }}

    // Download selected products
    async function downloadSelected() {{
        const ids = Array.from(document.querySelectorAll("input[name='product_id']:checked")).map(c => c.value);
        if (!ids.length) {{
            alert("Please select at least one product to download.");
            return;
        }}
        
        const resp = await fetch('/batches/{batch_id}/export-selected', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(ids)
        }});
        
        if (resp.ok) {{
            const blob = await resp.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'selected_products_{batch_id[:8]}.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }} else {{
            alert('Failed to download selected products');
        }}
    }}
    
    // Scroll arrows functionality
    const tableWrap = document.getElementById('tableWrap');
    const scrollLeftBtn = document.getElementById('scrollLeft');
    const scrollRightBtn = document.getElementById('scrollRight');
    const scrollHint = document.getElementById('scrollHint');
    const scrollAmount = 400;
    
    function updateScrollArrows() {{
        const {{ scrollLeft, scrollWidth, clientWidth }} = tableWrap;
        const canScroll = scrollWidth > clientWidth;
        const canScrollLeft = scrollLeft > 5;
        const canScrollRight = scrollLeft < scrollWidth - clientWidth - 5;
        
        scrollLeftBtn.classList.toggle('visible', canScrollLeft);
        scrollRightBtn.classList.toggle('visible', canScrollRight);
        scrollHint.classList.toggle('hidden', !canScroll);
    }}
    
    function scrollTableLeft() {{
        tableWrap.scrollBy({{ left: -scrollAmount, behavior: 'smooth' }});
    }}
    
    function scrollTableRight() {{
        tableWrap.scrollBy({{ left: scrollAmount, behavior: 'smooth' }});
    }}
    
    tableWrap.addEventListener('scroll', updateScrollArrows);
    window.addEventListener('resize', updateScrollArrows);
    setTimeout(updateScrollArrows, 100);
    
    // Click-and-drag to scroll
    let isDragging = false, startX, startScrollLeft;
    
    function canStartDrag(el) {{
        return !el.closest('.editable-cell, button, a, input, select, [contenteditable="true"]');
    }}
    
    function stopDrag() {{
        isDragging = false;
        tableWrap.classList.remove('dragging');
        document.removeEventListener('mousemove', onDragMove);
        document.removeEventListener('mouseup', stopDrag);
    }}
    
    function onDragMove(e) {{
        if (!isDragging) return;
        e.preventDefault();
        const walk = (e.pageX - startX) * 1.2;
        tableWrap.scrollLeft = startScrollLeft - walk;
    }}
    
    tableWrap.addEventListener('mousedown', function(e) {{
        if (!canStartDrag(e.target)) return;
        isDragging = true;
        startX = e.pageX;
        startScrollLeft = tableWrap.scrollLeft;
        tableWrap.classList.add('dragging');
        document.addEventListener('mousemove', onDragMove);
        document.addEventListener('mouseup', stopDrag);
    }});
    (function(){{
        const t=document.getElementById("themeToggle");
        if(t){{const k="hp-theme";function g(){{return localStorage.getItem(k)||"dark";}}function s(v){{document.documentElement.setAttribute("data-theme",v);localStorage.setItem(k,v);t.textContent=v==="dark"?"\u2600":"\u263E";}}t.onclick=()=>s(g()==="dark"?"light":"dark");s(g());}}
    }})();
    </script>
    <div id="merchantPushOverlay" class="merchant-push-overlay" aria-hidden="true">
        <div class="merchant-push-modal" role="dialog" aria-modal="true" aria-labelledby="merchantPushLoadingTitle" onclick="event.stopPropagation()">
            <div id="merchantPushLoading" class="merchant-push-state">
                <div class="merchant-push-spinner" aria-hidden="true"></div>
                <p class="merchant-push-title" id="merchantPushLoadingTitle">Uploading to Merchant Center</p>
                <p class="merchant-push-sub">Sending products to your linked account. Please keep this page open.</p>
            </div>
            <div id="merchantPushResult" class="merchant-push-state is-hidden">
                <div id="merchantPushIconOk" class="merchant-push-icon-ok">&#10003;</div>
                <div id="merchantPushIconErr" class="merchant-push-icon-err is-hidden">!</div>
                <p class="merchant-push-title" id="merchantPushResultTitle">Done</p>
                <div id="merchantPushResultBody" class="merchant-push-body"></div>
                <button type="button" class="btn-merchant-gotit" id="merchantPushGotIt" onclick="merchantPushCloseOverlay()">Got it</button>
            </div>
        </div>
    </div>
    <script>
    (function() {{
        var ov = document.getElementById("merchantPushOverlay");
        if (ov) ov.addEventListener("click", function(e) {{ if (e.target === ov) merchantPushCloseOverlay(); }});
        var g = document.getElementById("merchantPushGotIt");
        if (g && !g.onclick) g.onclick = function() {{ merchantPushCloseOverlay(); }};
    }})();
    </script>
    <div id="feedbackOverlay" class="feedback-overlay">
        <div class="feedback-box" onclick="event.stopPropagation()">
            <div id="feedbackForm" class="feedback-form">
                <h3>Quick feedback</h3>
                <p>This service is free — the only thing we ask is a few words about your experience.</p>
                <textarea id="feedbackText" placeholder="Your feedback (optional)..." maxlength="500"></textarea>
                <div class="feedback-stars">
                    <span class="feedback-star" data-r="1">&#9733;</span><span class="feedback-star" data-r="2">&#9733;</span><span class="feedback-star" data-r="3">&#9733;</span><span class="feedback-star" data-r="4">&#9733;</span><span class="feedback-star" data-r="5">&#9733;</span>
                </div>
                <button type="button" class="btn" id="feedbackSubmit">Send</button>
            </div>
            <div id="feedbackThanks" class="feedback-thanks">
                <h3>Thank you!</h3>
                <p>We appreciate your feedback.</p>
            </div>
        </div>
    </div>
    <script>
    // Feedback form — show after 30 seconds OR when user scrolls past 70%
    (function(){{
        const overlay=document.getElementById("feedbackOverlay");
        const form=document.getElementById("feedbackForm");
        const thanks=document.getElementById("feedbackThanks");
        const stars=document.querySelectorAll(".feedback-star");
        const textarea=document.getElementById("feedbackText");
        const submitBtn=document.getElementById("feedbackSubmit");
        let rating=0;
        let shown=false;
        const FEEDBACK_KEY="feedback_sent_{batch_id[:8]}";
        function showFeedback(){{
            if(shown||localStorage.getItem(FEEDBACK_KEY))return;
            shown=true;
            overlay.classList.add("visible");
        }}
        if(!overlay)return;
        stars.forEach((s,i)=>{{
            s.onclick=()=>{{rating=i+1;stars.forEach((st,j)=>{{st.classList.toggle("filled",j<i+1);}});}};
            s.onmouseenter=()=>{{stars.forEach((st,j)=>{{st.classList.toggle("filled",j<=i);}});}};
        }});
        var starsEl=document.querySelector(".feedback-stars");
        if(starsEl)starsEl.addEventListener("mouseleave",function(){{stars.forEach(function(st,j){{st.classList.toggle("filled",j<rating);}});}});
        setTimeout(showFeedback,30000);
        window.addEventListener("scroll",function(){{
            var max=document.documentElement.scrollHeight-window.innerHeight;
            if(max>0&&window.scrollY/max>=0.7)showFeedback();
        }},{{passive:true}});
        overlay.onclick=function(e){{if(e.target===overlay)overlay.classList.remove("visible");}};
        submitBtn.onclick=async function(){{
            var text=(textarea.value||"").trim();
            if(rating<1){{alert("Please select a rating.");return;}}
            var sanitized=text.replace(/[<>\\[\\]{{}}\\\\`]/g,"").replace(/<[^>]*>/g,"").substring(0,500);
            try{{
                var r=await fetch("/api/feedback",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{rating:rating,text:sanitized,batch_id:"{batch_id[:8]}"}})}});
                if(r.ok){{localStorage.setItem(FEEDBACK_KEY,"1");form.classList.add("hidden");thanks.classList.add("visible");setTimeout(function(){{overlay.classList.remove("visible");}},5000);}}
                else{{alert("Could not send. Try again.");}}
            }}catch(e){{alert("Could not send. Try again.");}}
        }};
    }})();
    (function(){{
        document.querySelectorAll(".batch-history-close").forEach(function(btn){{
            btn.addEventListener("click", async function(){{
                var bid = btn.getAttribute("data-batch-id");
                if (!bid || !confirm("Close this batch? It will be marked Closed in your history.")) return;
                try {{
                    var r = await fetch("/batches/" + encodeURIComponent(bid) + "/close", {{
                        method: "POST",
                        credentials: "same-origin",
                        headers: {{ "Accept": "application/json" }}
                    }});
                    if (!r.ok) {{ alert("Could not close batch."); return; }}
                    window.location.reload();
                }} catch (e) {{ alert("Could not close batch."); }}
            }});
        }});
    }})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""
    r = HTMLResponse(content=html)
    _onboarding_track(request, r, 5)
    return r


@app.post("/api/feedback")
async def submit_feedback(request: Request, data: dict):
    """Collect user feedback. Sanitized server-side."""
    import re
    rating = data.get("rating")
    text = (data.get("text") or "").strip()
    batch_id = (data.get("batch_id") or "")[:20]
    if not isinstance(rating, (int, float)) or rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="Invalid rating")
    safe_text = re.sub(r"[<>\[\]{}\\\"`]", "", text)
    safe_text = re.sub(r"<[^>]*>", "", safe_text)[:500]
    user = get_current_user(request)
    from .db import get_db
    from .services.db_repository import add_feedback
    with get_db() as db:
        add_feedback(db, int(rating), safe_text, batch_id, user.get("email", "") if user else "", user.get("name", "") if user else "")
    return {"status": "ok"}


def _request_is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else None
    if not host:
        return False
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    return host.startswith("::ffff:127.0.0.1")


@app.get("/health")
def health(request: Request):
    """Loopback clients get main_py path — use to verify which code instance serves :8000."""
    out: dict = {"status": "ok", "upload_ui": UPLOAD_UI_REVISION}
    if _request_is_loopback(request):
        out["main_py"] = __file__
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Settings page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    redir = require_admin_redirect(request, "/settings")
    if redir:
        return redir
    s = _get_settings()
    import html as _html
    from .google_cloud import get_google_oauth_env_summary

    _gc = get_google_oauth_env_summary()
    gcp_pid = _gc.get("google_cloud_project_id") or ""
    gcp_hint = _gc.get("oauth_client_id_hint") or ""
    gcp_oauth_ok = _gc.get("oauth_client_configured")
    gcp_hint_line = f'<br/>Client ID: <code>{_html.escape(gcp_hint)}</code>' if gcp_hint else ""
    api_key_masked = ""
    if s.get("openai_api_key"):
        key = s["openai_api_key"]
        api_key_masked = key[:7] + "..." + key[-4:] if len(key) > 15 else "••••••••"
    from .db import get_db
    from .services.db_repository import get_all_feedback, get_all_users, get_all_chat_sessions

    with get_db() as db:
        feedback_list = get_all_feedback(db)
        users_list = get_all_users(db)
        chat_sessions_list = get_all_chat_sessions(db)

    feedback_rows = ""
    for i, fb in enumerate(feedback_list):
        stars = "&#9733;" * fb.get("rating", 0) + "&#9734;" * (5 - fb.get("rating", 0))
        ts = fb.get("timestamp", "")[:19].replace("T", " ") if fb.get("timestamp") else "—"
        text = _html.escape(fb.get("text", ""))[:200]
        email = _html.escape(fb.get("email", "—"))
        name = _html.escape(fb.get("name", ""))
        batch = _html.escape(fb.get("batch_id", ""))
        feedback_rows += f"""<tr><td>{i + 1}</td><td class="stars">{stars}</td><td class="text-cell">{text}</td><td>{name}<br><span class="email">{email}</span></td><td class="mono">{batch}</td><td class="ts">{ts}</td></tr>"""

    users_rows = ""
    for i, u in enumerate(users_list):
        name = _html.escape(u.get("name", "—"))
        email = _html.escape(u.get("email", ""))
        provider = _html.escape(u.get("provider", ""))
        role = u.get("role", "customer")
        role_badge = '<span class="badge badge-admin">admin</span>' if role == "admin" else '<span class="badge badge-customer">customer</span>'
        last_login = u.get("last_login", "")[:19].replace("T", " ") if u.get("last_login") else "—"
        first_seen = u.get("first_seen", "")[:19].replace("T", " ") if u.get("first_seen") else "—"
        users_rows += f"""<tr><td>{i + 1}</td><td><strong>{name}</strong><br><span class="email">{email}</span></td><td>{provider}</td><td>{role_badge}</td><td class="ts">{first_seen}</td><td class="ts">{last_login}</td></tr>"""

    feedback_total = len(feedback_list)
    feedback_avg = round(sum(f.get("rating", 0) for f in feedback_list) / feedback_total, 1) if feedback_total else 0
    users_total = len(users_list)
    admins = sum(1 for u in users_list if u.get("role") == "admin")
    customers = users_total - admins

    import base64
    chat_sessions_rows = ""
    for i, cs in enumerate(chat_sessions_list):
        sid_raw = cs.get("session_id", "")
        sid_display = _html.escape(sid_raw[:12] + "..." if len(sid_raw) > 12 else sid_raw)
        email = _html.escape(cs.get("user_email", "—") or "—")
        msgs = cs.get("messages", [])
        msg_count = len(msgs)
        first_msg = _html.escape((msgs[0].get("content", "")[:60] + "…") if msgs else "—")
        updated = cs.get("updated_at", "")[:19].replace("T", " ") if cs.get("updated_at") else "—"
        msgs_b64 = base64.b64encode(json.dumps(msgs).encode()).decode()
        chat_sessions_rows += f'<tr><td>{i + 1}</td><td class="mono">{sid_display}</td><td class="email">{email}</td><td>{msg_count}</td><td class="text-cell">{first_msg}</td><td class="ts">{updated}</td><td><button type="button" class="btn btn-small" onclick="viewChatSession(this)" data-msgs="{msgs_b64}">View</button></td></tr>'

    tab_param = request.query_params.get("tab", "prompts")
    if tab_param not in ("prompts", "api", "seo", "users", "feedback", "chats"):
        tab_param = "prompts"
    prompt_sub_param = request.query_params.get("sub", "products")
    if prompt_sub_param not in ("products", "writter"):
        prompt_sub_param = "products"

    def _tx_esc(val: str) -> str:
        return (val or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    wp_ps = _tx_esc(s.get("writter_prompt_problem_solving", ""))
    wp_fp = _tx_esc(s.get("writter_prompt_feature_presentation", ""))
    wp_inf = _tx_esc(s.get("writter_prompt_informational", ""))
    wp_uc = _tx_esc(s.get("writter_prompt_use_cases", ""))
    wp_cmp = _tx_esc(s.get("writter_prompt_comparison", ""))
    wp_chk = _tx_esc(s.get("writter_prompt_checklist_template", ""))

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Settings &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <link rel="stylesheet" href="/static/styles.css" />
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    [data-theme="light"] .tabs {{ border-bottom-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] .tab {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .tab:hover {{ color: rgba(15,23,42,0.8); }}
    [data-theme="light"] .tab.active {{ color: #0f172a; }}
    [data-theme="light"] .tab.active::after {{ background: #0f172a; }}
    [data-theme="light"] .group-desc {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .group-desc code {{ background: rgba(15,23,42,0.1); }}
    [data-theme="light"] textarea {{ border-color: rgba(15,23,42,0.15); background: rgba(255,255,255,0.9); color: #0f172a; }}
    [data-theme="light"] textarea:focus {{ border-color: rgba(15,23,42,0.3); }}
    [data-theme="light"] input[type="password"] {{ border-color: rgba(15,23,42,0.15); background: rgba(255,255,255,0.9); color: #0f172a; }}
    [data-theme="light"] input[type="password"]:focus {{ border-color: rgba(15,23,42,0.3); }}
    [data-theme="light"] .key-status {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .key-status code {{ background: rgba(15,23,42,0.1); }}
    [data-theme="light"] .btn-primary {{ background: #0f172a; color: #fff; }}
    [data-theme="light"] .note-box {{ background: rgba(255,255,255,0.8); border-color: rgba(15,23,42,0.1); }}
    [data-theme="light"] .note-box p {{ color: rgba(15,23,42,0.7); }}
    [data-theme="light"] .note-box strong {{ color: #0f172a; }}

    .container {{ max-width: 1100px; margin: 48px auto; padding: 0 24px; }}
    .title {{ font-size: 1.75rem; font-weight: 600; margin-bottom: 32px; letter-spacing: -0.02em; }}

    .tabs {{ display: flex; gap: 8px; margin-bottom: 32px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 0; }}
    .tab {{ padding: 12px 20px; font-size: 0.9rem; font-weight: 500; color: rgba(255,255,255,0.5); background: none; border: none; cursor: pointer; position: relative; transition: color 0.2s; }}
    .tab:hover {{ color: rgba(255,255,255,0.8); }}
    .tab.active {{ color: #fff; }}
    .tab.active::after {{ content: ''; position: absolute; bottom: -1px; left: 0; right: 0; height: 2px; background: #fff; }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}

    .prompt-subtabs {{ display: flex; gap: 8px; margin-bottom: 22px; flex-wrap: wrap; }}
    .prompt-subtab {{ padding: 8px 16px; font-size: 0.85rem; font-weight: 500; color: rgba(255,255,255,0.55); background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; cursor: pointer; transition: color 0.2s, background 0.2s, border-color 0.2s; }}
    .prompt-subtab:hover {{ color: rgba(255,255,255,0.85); background: rgba(255,255,255,0.07); }}
    .prompt-subtab.active {{ color: #fff; background: rgba(255,255,255,0.12); border-color: rgba(255,255,255,0.22); }}
    [data-theme="light"] .prompt-subtab {{ color: rgba(15,23,42,0.55); background: rgba(15,23,42,0.04); border-color: rgba(15,23,42,0.12); }}
    [data-theme="light"] .prompt-subtab:hover {{ color: rgba(15,23,42,0.85); }}
    [data-theme="light"] .prompt-subtab.active {{ color: #0f172a; background: rgba(15,23,42,0.08); border-color: rgba(15,23,42,0.18); }}
    .prompt-subpanel {{ display: none; }}
    .prompt-subpanel.active {{ display: block; }}

    .group {{ margin-bottom: 28px; }}
    .group-title {{ font-weight: 600; font-size: 1rem; margin-bottom: 8px; }}
    .group-desc {{ font-size: 0.85rem; color: rgba(255,255,255,0.5); margin-bottom: 14px; line-height: 1.5; }}
    .group-desc a {{ color: #4F46E5; }}
    .group-desc code {{ background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; }}

    textarea {{ width: 100%; min-height: 140px; padding: 14px 16px; font-size: 0.85rem; font-family: monospace; line-height: 1.5; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; background: rgba(255,255,255,0.05); color: #fff; resize: vertical; }}
    textarea:focus {{ outline: none; border-color: rgba(255,255,255,0.3); }}

    input[type="password"] {{ width: 100%; padding: 12px 16px; font-size: 0.9rem; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; background: rgba(255,255,255,0.05); color: #fff; }}
    input[type="password"]:focus {{ outline: none; border-color: rgba(255,255,255,0.3); }}

    .key-status {{ font-size: 0.85rem; color: rgba(255,255,255,0.5); margin-bottom: 14px; }}
    .key-status code {{ background: rgba(255,255,255,0.1); padding: 2px 8px; border-radius: 4px; }}

    .btn {{ padding: 12px 24px; font-size: 0.9rem; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; transition: all 0.2s; }}
    .btn-primary {{ background: #fff; color: #000; }}
    .btn-primary:hover {{ opacity: 0.9; }}

    .save-msg {{ display: inline-flex; align-items: center; gap: 6px; margin-left: 14px; font-size: 0.85rem; color: #4F46E5; opacity: 0; transition: opacity 0.3s; }}
    .save-msg.show {{ opacity: 1; }}

    .note-box {{ margin-top: 28px; padding: 16px 20px; border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); }}
    .note-box p {{ font-size: 0.85rem; color: rgba(255,255,255,0.6); margin: 0; line-height: 1.5; }}
    .note-box strong {{ color: rgba(255,255,255,0.8); }}

    .stats {{ display: flex; gap: 24px; margin-bottom: 24px; flex-wrap: wrap; }}
    .stat {{ padding: 20px 28px; border-radius: 12px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); flex: 1; min-width: 120px; }}
    [data-theme="light"] .stat {{ background: rgba(255,255,255,0.8); border-color: rgba(15,23,42,0.08); }}
    .stat-val {{ font-size: 1.5rem; font-weight: 700; }}
    .stat-label {{ font-size: 0.8rem; color: rgba(255,255,255,0.4); margin-top: 4px; }}
    [data-theme="light"] .stat-label {{ color: rgba(15,23,42,0.5); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{ text-align: left; padding: 12px 16px; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: rgba(255,255,255,0.4); border-bottom: 1px solid rgba(255,255,255,0.1); }}
    [data-theme="light"] th {{ color: rgba(15,23,42,0.5); border-bottom-color: rgba(15,23,42,0.1); }}
    td {{ padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: top; }}
    [data-theme="light"] td {{ border-bottom-color: rgba(15,23,42,0.06); }}
    tr:hover td {{ background: rgba(255,255,255,0.02); }}
    [data-theme="light"] tr:hover td {{ background: rgba(15,23,42,0.02); }}
    .stars {{ color: #f59e0b; font-size: 1rem; white-space: nowrap; }}
    .text-cell {{ max-width: 300px; word-break: break-word; }}
    .email {{ font-size: 0.78rem; color: rgba(255,255,255,0.4); }}
    [data-theme="light"] .email {{ color: rgba(15,23,42,0.4); }}
    .mono {{ font-family: monospace; font-size: 0.78rem; }}
    .ts {{ font-size: 0.78rem; white-space: nowrap; color: rgba(255,255,255,0.5); }}
    [data-theme="light"] .ts {{ color: rgba(15,23,42,0.5); }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }}
    .badge-admin {{ background: rgba(79,70,229,0.15); color: #4F46E5; }}
    .badge-customer {{ background: rgba(99,102,241,0.15); color: #818cf8; }}
    [data-theme="light"] .badge-admin {{ background: rgba(79,70,229,0.1); }}
    [data-theme="light"] .badge-customer {{ background: rgba(99,102,241,0.1); }}
    .empty {{ text-align: center; padding: 60px 24px; color: rgba(255,255,255,0.3); font-size: 1rem; }}
    [data-theme="light"] .empty {{ color: rgba(15,23,42,0.3); }}
    input[type="text"], input[type="url"] {{ width: 100%; padding: 12px 16px; font-size: 0.9rem; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; background: rgba(255,255,255,0.05); color: #fff; }}
    input[type="text"]:focus, input[type="url"]:focus {{ outline: none; border-color: rgba(255,255,255,0.3); }}
    [data-theme="light"] input[type="text"], [data-theme="light"] input[type="url"] {{ border-color: rgba(15,23,42,0.15); background: rgba(255,255,255,0.9); color: #0f172a; }}
    [data-theme="light"] input[type="text"]:focus, [data-theme="light"] input[type="url"]:focus {{ border-color: rgba(15,23,42,0.3); }}
    .btn-small {{ padding: 6px 14px; font-size: 0.82rem; }}
    .modal {{ position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 2000; display: flex; align-items: center; justify-content: center; padding: 24px; }}
    .modal-content {{ background: #1a1a1e; border-radius: 12px; padding: 24px; max-height: 90vh; overflow: auto; border: 1px solid rgba(255,255,255,0.1); }}
    [data-theme="light"] .modal-content {{ background: #fff; border-color: rgba(15,23,42,0.1); }}
    .chat-msg {{ padding: 10px 14px; border-radius: 8px; margin-bottom: 8px; font-size: 0.88rem; }}
    .chat-msg.user {{ background: rgba(255,255,255,0.08); margin-left: 20px; }}
    .chat-msg.assistant {{ background: rgba(79,70,229,0.12); margin-right: 20px; }}
    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} .container {{ margin: 32px auto; }} .stats {{ flex-direction: column; gap: 12px; }} }}
    </style>
</head>
<body>
{GTM_BODY}
    {admin_top_nav_html('settings')}

    <div class="container">
        <h1 class="title">Settings</h1>

        <div class="tabs">
            <button class="tab{' active' if tab_param == 'prompts' else ''}" data-tab="tab-prompts" onclick="switchTab('tab-prompts','prompts')">Prompts</button>
            <button class="tab{' active' if tab_param == 'api' else ''}" data-tab="tab-api" onclick="switchTab('tab-api','api')">API Keys</button>
            <button class="tab{' active' if tab_param == 'seo' else ''}" data-tab="tab-seo" onclick="switchTab('tab-seo','seo')">SEO</button>
            <button class="tab{' active' if tab_param == 'users' else ''}" data-tab="tab-users" onclick="switchTab('tab-users','users')">Users</button>
            <button class="tab{' active' if tab_param == 'feedback' else ''}" data-tab="tab-feedback" onclick="switchTab('tab-feedback','feedback')">Feedback</button>
            <button class="tab{' active' if tab_param == 'chats' else ''}" data-tab="tab-chats" onclick="switchTab('tab-chats','chats')">Chat Sessions</button>
        </div>

        <div id="tab-prompts" class="tab-content{' active' if tab_param == 'prompts' else ''}">
            <div class="prompt-subtabs">
                <button type="button" class="prompt-subtab{' active' if prompt_sub_param == 'products' else ''}" data-sub="products" onclick="switchPromptSub('products')">Product feed</button>
                <button type="button" class="prompt-subtab{' active' if prompt_sub_param == 'writter' else ''}" data-sub="writter" onclick="switchPromptSub('writter')">Blog article types</button>
            </div>

            <div id="prompt-sub-products" class="prompt-subpanel{' active' if prompt_sub_param == 'products' else ''}">
            <div class="group">
                <div class="group-title">Title Optimization Prompt</div>
                <p class="group-desc">
                    This prompt is sent to the AI when optimizing product titles.
                    Variables: <code>{{{{title}}}}</code>, <code>{{{{category}}}}</code>, <code>{{{{brand}}}}</code>, <code>{{{{attributes}}}}</code>
                </p>
                <textarea id="prompt_title">{s["prompt_title"]}</textarea>
            </div>

            <div class="group">
                <div class="group-title">Description Generation Prompt</div>
                <p class="group-desc">
                    This prompt is sent to the AI when generating product descriptions.
                    Variables: <code>{{{{title}}}}</code>, <code>{{{{category}}}}</code>, <code>{{{{brand}}}}</code>, <code>{{{{attributes}}}}</code>, <code>{{{{description}}}}</code>
                </p>
                <textarea id="prompt_description">{s["prompt_description"]}</textarea>
            </div>

            <div style="display:flex;align-items:center;">
                <button class="btn btn-primary" onclick="savePrompts()">Save prompts</button>
                <span id="prompts-status" class="save-msg">&#10003; Saved</span>
            </div>
            </div>

            <div id="prompt-sub-writter" class="prompt-subpanel{' active' if prompt_sub_param == 'writter' else ''}">
            <p class="group-desc" style="margin-bottom:18px;">Extra instructions for each <strong>article type</strong> in the Writter. They are combined with topic, keywords, rules, and the selected visual — those fields are never ignored.</p>
            <div class="group">
                <div class="group-title">Problem Solving</div>
                <p class="group-desc">Optional. Applied when the article type is Problem Solving.</p>
                <textarea id="writter_prompt_problem_solving" style="min-height:120px;">{wp_ps}</textarea>
            </div>
            <div class="group">
                <div class="group-title">Feature Presentation</div>
                <p class="group-desc">Optional. Applied when the article type is Feature Presentation.</p>
                <textarea id="writter_prompt_feature_presentation" style="min-height:120px;">{wp_fp}</textarea>
            </div>
            <div class="group">
                <div class="group-title">Informational</div>
                <p class="group-desc">Optional. Applied when the article type is Informational.</p>
                <textarea id="writter_prompt_informational" style="min-height:120px;">{wp_inf}</textarea>
            </div>
            <div class="group">
                <div class="group-title">Use Cases</div>
                <p class="group-desc">Optional. Applied when the article type is Use Cases.</p>
                <textarea id="writter_prompt_use_cases" style="min-height:120px;">{wp_uc}</textarea>
            </div>
            <div class="group">
                <div class="group-title">Comparison</div>
                <p class="group-desc">Optional. Applied when the article type is Comparison.</p>
                <textarea id="writter_prompt_comparison" style="min-height:120px;">{wp_cmp}</textarea>
            </div>
            <div class="group">
                <div class="group-title">Checklist / template</div>
                <p class="group-desc">Optional. Applied when the article type is Checklist / template.</p>
                <textarea id="writter_prompt_checklist_template" style="min-height:120px;">{wp_chk}</textarea>
            </div>
            <div style="display:flex;align-items:center;">
                <button class="btn btn-primary" onclick="saveWritterPrompts()">Save article-type prompts</button>
                <span id="writter-prompts-status" class="save-msg">&#10003; Saved</span>
            </div>
            </div>
        </div>

        <div id="tab-api" class="tab-content{' active' if tab_param == 'api' else ''}">
            <div class="group">
                <div class="group-title">OpenAI API Key</div>
                <p class="group-desc">
                    Enter your OpenAI API key to enable AI-powered generation.
                    Get your key from <a href="https://platform.openai.com/api-keys" target="_blank">platform.openai.com</a>.
                </p>
                <div class="key-status">
                    Current: <code id="key-display" style="{'display:inline;' if api_key_masked else 'display:none;'}">{api_key_masked}</code>
                    <span id="no-key" style="{'display:none;' if api_key_masked else ''}">Not set</span>
                </div>
                <input type="password" id="openai_key" placeholder="sk-..." />
            </div>

            <div style="display:flex;align-items:center;">
                <button class="btn btn-primary" onclick="saveApiKey()">Save API key</button>
                <span id="apikey-status" class="save-msg">&#10003; Saved</span>
            </div>

            <div class="note-box">
                <p><strong>Note:</strong> With an API key, the system uses OpenAI GPT-4o-mini for generation. Without one, a placeholder algorithm demonstrates the flow.</p>
            </div>

            <div class="group" style="margin-top:32px;">
                <div class="group-title">Google Cloud (OAuth)</div>
                <p class="group-desc">
                    User login and Merchant Center connection use the <strong>same</strong> OAuth 2.0 Web Client in one Google Cloud project.
                    Set <code>GOOGLE_CLOUD_PROJECT_ID</code> to that project’s ID (Console top bar). Enable APIs and redirect URIs there.
                </p>
                <div class="key-status">
                    GCP project ID: <code>{_html.escape(gcp_pid) if gcp_pid else "—"}</code><br/>
                    OAuth client: <code>{"configured" if gcp_oauth_ok else "missing GOOGLE_CLIENT_ID / SECRET"}</code>{gcp_hint_line}
                </div>
            </div>
        </div>

        <div id="tab-seo" class="tab-content{' active' if tab_param == 'seo' else ''}">
            <p class="group-desc" style="margin-bottom:24px;">Edit meta tags for search engines and social sharing. Applied to the homepage.</p>
            <div class="group">
                <div class="group-title">Meta Title</div>
                <p class="group-desc">Page title for search results (recommended 50–60 chars).</p>
                <input type="text" id="seo_meta_title" placeholder="Cartozo.ai — AI-Powered Product Feed Optimization" value="{s.get("seo_meta_title", "").replace(chr(34), "&quot;")}" maxlength="120" />
            </div>
            <div class="group">
                <div class="group-title">Meta Description</div>
                <p class="group-desc">Description for search results (recommended 150–160 chars).</p>
                <textarea id="seo_meta_description" placeholder="AI-powered optimization for your product titles..." maxlength="320">{s.get("seo_meta_description", "").replace("<", "&lt;").replace(">", "&gt;")}</textarea>
            </div>
            <div class="group">
                <div class="group-title">Open Graph Title</div>
                <p class="group-desc">Title when shared on Facebook, LinkedIn, etc.</p>
                <input type="text" id="seo_og_title" placeholder="Same as Meta Title" value="{s.get("seo_og_title", "").replace(chr(34), "&quot;")}" maxlength="120" />
            </div>
            <div class="group">
                <div class="group-title">Open Graph Description</div>
                <p class="group-desc">Description when shared on social.</p>
                <textarea id="seo_og_description" placeholder="Same as Meta Description" maxlength="320">{s.get("seo_og_description", "").replace("<", "&lt;").replace(">", "&gt;")}</textarea>
            </div>
            <div class="group">
                <div class="group-title">Open Graph Image URL</div>
                <p class="group-desc">Full URL to image for social sharing. Recommended 1200×630px.</p>
                <input type="url" id="seo_og_image" placeholder="https://..." value="{s.get("seo_og_image", "").replace(chr(34), "&quot;")}" />
            </div>
            <div class="group">
                <div class="group-title">Site Name</div>
                <p class="group-desc">Brand/site name for Open Graph.</p>
                <input type="text" id="seo_og_site_name" placeholder="Cartozo.ai" value="{s.get("seo_og_site_name", "").replace(chr(34), "&quot;")}" maxlength="64" />
            </div>
            <div style="display:flex;align-items:center;">
                <button class="btn btn-primary" onclick="saveSeo()">Save SEO settings</button>
                <span id="seo-status" class="save-msg">&#10003; Saved</span>
            </div>
        </div>

        <div id="tab-users" class="tab-content{' active' if tab_param == 'users' else ''}">
            <p class="group-desc" style="margin-bottom:24px;">{users_total} users have signed in</p>
            <div class="stats">
                <div class="stat"><div class="stat-val">{users_total}</div><div class="stat-label">Total users</div></div>
                <div class="stat"><div class="stat-val">{admins}</div><div class="stat-label">Admins</div></div>
                <div class="stat"><div class="stat-val">{customers}</div><div class="stat-label">Customers</div></div>
            </div>
            {"<table><thead><tr><th>#</th><th>User</th><th>Provider</th><th>Role</th><th>First seen</th><th>Last login</th></tr></thead><tbody>" + users_rows + "</tbody></table>" if users_total else '<div class="empty">No users have signed in yet.</div>'}
        </div>

        <div id="tab-feedback" class="tab-content{' active' if tab_param == 'feedback' else ''}">
            <p class="group-desc" style="margin-bottom:24px;">{feedback_total} feedback entries collected</p>
            <div class="stats">
                <div class="stat"><div class="stat-val">{feedback_total}</div><div class="stat-label">Total responses</div></div>
                <div class="stat"><div class="stat-val">{feedback_avg}</div><div class="stat-label">Average rating</div></div>
                <div class="stat"><div class="stat-val">{"&#9733;" * round(feedback_avg) + "&#9734;" * (5 - round(feedback_avg)) if feedback_total else "—"}</div><div class="stat-label">Stars</div></div>
            </div>
            {"<table><thead><tr><th>#</th><th>Rating</th><th>Feedback</th><th>User</th><th>Batch</th><th>Date</th></tr></thead><tbody>" + feedback_rows + "</tbody></table>" if feedback_total else '<div class="empty">No feedback yet. Feedback will appear here as customers submit it.</div>'}
        </div>

        <div id="tab-chats" class="tab-content{' active' if tab_param == 'chats' else ''}">
            <p class="group-desc" style="margin-bottom:24px;">{len(chat_sessions_list)} chat sessions with AI agent</p>
            <div class="stats">
                <div class="stat"><div class="stat-val">{len(chat_sessions_list)}</div><div class="stat-label">Total sessions</div></div>
            </div>
            {"<table><thead><tr><th>#</th><th>Session ID</th><th>User</th><th>Messages</th><th>Preview</th><th>Updated</th><th></th></tr></thead><tbody>" + chat_sessions_rows + "</tbody></table>" if chat_sessions_list else '<div class="empty">No chat sessions yet. Sessions will appear here as visitors use the homepage AI chat.</div>'}
            <div id="chatModal" class="modal" style="display:none;">
                <div class="modal-content" style="max-width:600px;">
                    <h3 style="margin-bottom:16px;">Chat Session</h3>
                    <div id="chatModalBody" style="max-height:400px;overflow-y:auto;font-size:0.9rem;"></div>
                    <button class="btn btn-primary" style="margin-top:16px;" onclick="document.getElementById('chatModal').style.display='none'">Close</button>
                </div>
            </div>
        </div>
    </div>

    <script>
    function switchTab(tabId, tabName){{
        document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
        document.querySelector('[data-tab="'+tabId+'"]').classList.add('active');
        document.getElementById(tabId).classList.add('active');
        if(tabName){{
            let q='?tab='+tabName;
            if(tabName==='prompts'){{
                const active=document.querySelector('.prompt-subtab.active');
                const sub=active&&active.getAttribute('data-sub')?active.getAttribute('data-sub'):'products';
                q+='&sub='+sub;
            }}
            history.replaceState(null,'','/settings'+q);
        }}
    }}
    function switchPromptSub(name){{
        document.querySelectorAll('.prompt-subtab').forEach(b=>b.classList.toggle('active', b.getAttribute('data-sub')===name));
        document.querySelectorAll('.prompt-subpanel').forEach(p=>p.classList.toggle('active', p.id==='prompt-sub-'+name));
        history.replaceState(null,'','/settings?tab=prompts&sub='+name);
    }}
    async function saveSeo(){{
        const data={{seo_meta_title:document.getElementById('seo_meta_title').value,seo_meta_description:document.getElementById('seo_meta_description').value,seo_og_title:document.getElementById('seo_og_title').value,seo_og_description:document.getElementById('seo_og_description').value,seo_og_image:document.getElementById('seo_og_image').value,seo_og_site_name:document.getElementById('seo_og_site_name').value}};
        const resp=await fetch('/api/admin/seo',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}});
        if(resp.ok)showSaved('seo-status');
    }}
    async function savePrompts(){{
        const resp=await fetch('/api/settings/prompts',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{prompt_title:document.getElementById('prompt_title').value,prompt_description:document.getElementById('prompt_description').value}})}});
        if(resp.ok)showSaved('prompts-status');
    }}
    async function saveWritterPrompts(){{
        const body={{
            writter_prompt_problem_solving:document.getElementById('writter_prompt_problem_solving').value,
            writter_prompt_feature_presentation:document.getElementById('writter_prompt_feature_presentation').value,
            writter_prompt_informational:document.getElementById('writter_prompt_informational').value,
            writter_prompt_use_cases:document.getElementById('writter_prompt_use_cases').value,
            writter_prompt_comparison:document.getElementById('writter_prompt_comparison').value,
            writter_prompt_checklist_template:document.getElementById('writter_prompt_checklist_template').value
        }};
        const resp=await fetch('/api/settings/writter-prompts',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
        if(resp.ok)showSaved('writter-prompts-status');
    }}
    async function saveApiKey(){{
        const key=document.getElementById('openai_key').value;
        const resp=await fetch('/api/settings/apikey',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{openai_api_key:key}})}});
        if(resp.ok){{
            showSaved('apikey-status');
            if(key){{document.getElementById('key-display').textContent=key.substring(0,7)+'...'+key.slice(-4);document.getElementById('key-display').style.display='inline';document.getElementById('no-key').style.display='none';}}
            document.getElementById('openai_key').value='';
        }}
    }}
    function showSaved(id){{const el=document.getElementById(id);el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2500);}}
    function viewChatSession(btn){{
        const b64=btn.getAttribute('data-msgs');
        if(!b64)return;
        try{{
            const msgs=JSON.parse(atob(b64));
            const body=document.getElementById('chatModalBody');
            body.innerHTML=msgs.map(m=>'<div class="chat-msg '+m.role+'">'+(m.content||'').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</div>').join('');
            document.getElementById('chatModal').style.display='flex';
        }}catch(e){{}}
    }}
    {ADMIN_THEME_SCRIPT}
    {ADMIN_MERCHANT_SCRIPT}
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─────────────────────────────────────────────────────────────────────────────
# Chat API (AI agent for homepage)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def api_chat(request: Request):
    """Chat with AI agent about Cartozo.ai. Uses same OpenAI API as titles/descriptions."""
    data = await request.json()
    session_id = data.get("session_id") or str(uuid.uuid4())
    user_message = (data.get("message") or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message is required")

    s = _get_settings()
    storage._ai.set_api_key(s.get("openai_api_key", "") or "")
    storage._ai.set_prompts(s.get("prompt_title", ""), s.get("prompt_description", ""))

    from .db import get_db
    from .services.db_repository import (
        get_chat_session,
        create_chat_session,
        update_chat_session,
    )

    user = get_current_user(request)
    user_email = user.get("email", "") if user else ""

    with get_db() as db:
        sess = get_chat_session(db, session_id)
        if not sess:
            create_chat_session(db, session_id, user_email)
            messages = []
        else:
            messages = list(sess["messages"])

    messages.append({"role": "user", "content": user_message})
    reply = storage._ai.chat(messages)
    messages.append({"role": "assistant", "content": reply})

    with get_db() as db:
        update_chat_session(db, session_id, messages)

    return JSONResponse({"reply": reply, "session_id": session_id})


@app.post("/api/chat/upload-csv")
async def api_chat_upload_csv(file: UploadFile = File(...)):
    """Accept CSV from hero chat, parse, validate, save to pending_uploads. No login required."""
    if file.content_type not in {"text/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=400, detail="Only CSV upload is supported.")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")

    is_safe, security_error = validate_csv_content(text, len(content))
    if not is_safe:
        raise HTTPException(status_code=400, detail=security_error)

    records = parse_csv_file(io.StringIO(text))
    if not records:
        raise HTTPException(status_code=400, detail="CSV appears empty or has no rows.")

    upload_id = str(uuid.uuid4())
    from .db import get_db
    from .services.db_repository import save_pending_upload
    with get_db() as db:
        save_pending_upload(db, upload_id, records, "optimize", "", "standard")

    return JSONResponse({"upload_id": upload_id})


@app.post("/api/settings/prompts")
async def save_prompts(request: Request):
    require_admin_http(request)

    data = await request.json()
    from .db import get_db
    from .services.db_repository import set_setting
    with get_db() as db:
        if "prompt_title" in data:
            set_setting(db, "prompt_title", str(data["prompt_title"]))
        if "prompt_description" in data:
            set_setting(db, "prompt_description", str(data["prompt_description"]))
    s = _get_settings()
    storage._ai.set_prompts(s["prompt_title"], s["prompt_description"])
    return JSONResponse({"ok": True})


_WRITTER_PROMPT_KEYS = (
    "writter_prompt_problem_solving",
    "writter_prompt_feature_presentation",
    "writter_prompt_informational",
    "writter_prompt_use_cases",
    "writter_prompt_comparison",
    "writter_prompt_checklist_template",
)


@app.post("/api/settings/writter-prompts")
async def save_writter_prompts(request: Request):
    require_admin_http(request)

    data = await request.json()
    from .db import get_db
    from .services.db_repository import set_setting
    with get_db() as db:
        for key in _WRITTER_PROMPT_KEYS:
            if key in data:
                set_setting(db, key, str(data[key]))
    return JSONResponse({"ok": True})


@app.post("/api/settings/apikey")
async def save_api_key(request: Request):
    require_admin_http(request)

    data = await request.json()
    from .db import get_db
    from .services.db_repository import set_setting
    if "openai_api_key" in data:
        with get_db() as db:
            set_setting(db, "openai_api_key", str(data["openai_api_key"]))
        storage._ai.set_api_key(data["openai_api_key"])
    s = _get_settings()
    storage._ai.set_prompts(s["prompt_title"], s["prompt_description"])
    return JSONResponse({"ok": True})


@app.get("/api/settings")
async def get_settings(request: Request):
    require_admin_http(request)
    s = _get_settings()
    from .google_cloud import get_google_oauth_env_summary

    return {
        "prompt_title": s["prompt_title"],
        "prompt_description": s["prompt_description"],
        "has_api_key": bool(s.get("openai_api_key")),
        "google_cloud": get_google_oauth_env_summary(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# User / role API
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/me")
async def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return {
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "role": user.get("role", "customer"),
        "provider": user.get("provider", ""),
    }


@app.get("/api/admin/feedback")
async def api_admin_feedback(request: Request):
    require_admin_http(request)
    from .db import get_db
    from .services.db_repository import get_all_feedback
    with get_db() as db:
        feedback_list = get_all_feedback(db)
    return {"feedback": feedback_list}


@app.get("/api/admin/users")
async def api_admin_users(request: Request):
    require_admin_http(request)
    from .db import get_db
    from .services.db_repository import get_all_users
    with get_db() as db:
        users_list = get_all_users(db)
    return {"users": users_list, "total": len(users_list)}


# ─────────────────────────────────────────────────────────────────────────────
# Admin: Contact results page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/admin/contact-results", response_class=HTMLResponse)
async def admin_contact_results_page(request: Request):
    redir = require_admin_redirect(request, "/admin/contact-results")
    if redir:
        return redir
    import html as _html
    from .db import get_db
    from .services.db_repository import get_all_contact_submissions
    with get_db() as db:
        submissions = get_all_contact_submissions(db)
    rows = ""
    for i, s in enumerate(submissions):
        name = _html.escape(s.get("name", ""))
        surname = _html.escape(s.get("surname", ""))
        email = _html.escape(s.get("email", ""))
        phone = _html.escape(s.get("phone", "") or "—")
        ts = s.get("created_at", "")[:19].replace("T", " ") if s.get("created_at") else "—"
        rows += f"<tr><td>{i + 1}</td><td><strong>{name} {surname}</strong></td><td class=\"email\">{email}</td><td>{phone}</td><td class=\"ts\">{ts}</td></tr>"
    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Contact results &mdash; Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B0F19; color: #E5E7EB; min-height: 100vh; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    .nav {{ display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
    [data-theme="light"] .nav {{ border-bottom-color: rgba(15,23,42,0.08); }}
    .nav-logo img {{ height: 32px; }}
    .nav-logo .logo-light {{ display: block; filter: brightness(0) invert(1); }}
    .nav-logo .logo-dark {{ display: none; }}
    [data-theme="light"] .nav-logo .logo-light {{ display: none; }}
    [data-theme="light"] .nav-logo .logo-dark {{ display: block; filter: none; }}
    .nav-links {{ display: flex; align-items: center; gap: 32px; }}
    .nav-link {{ color: rgba(255,255,255,0.6); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }}
    .nav-link:hover, .nav-link.active {{ color: #fff; }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover, [data-theme="light"] .nav-link.active {{ color: #0f172a; }}
    .theme-btn {{ width: 36px; height: 36px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: rgba(255,255,255,0.6); cursor: pointer; font-size: 1rem; }}
    .container {{ max-width: 900px; margin: 48px auto; padding: 0 24px; }}
    .title {{ font-size: 1.75rem; font-weight: 600; margin-bottom: 32px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{ text-align: left; padding: 12px 16px; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: rgba(255,255,255,0.4); border-bottom: 1px solid rgba(255,255,255,0.1); }}
    [data-theme="light"] th {{ color: rgba(15,23,42,0.5); }}
    td {{ padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
    [data-theme="light"] td {{ border-bottom-color: rgba(15,23,42,0.06); }}
    .email {{ font-size: 0.85rem; }}
    .ts {{ font-size: 0.78rem; white-space: nowrap; color: rgba(255,255,255,0.5); }}
    [data-theme="light"] .ts {{ color: rgba(15,23,42,0.5); }}
    .empty {{ text-align: center; padding: 60px 24px; color: rgba(255,255,255,0.3); }}
    </style>
</head>
<body>
{GTM_BODY}
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="nav-links">
            <a href="/batches/history" class="nav-link">Batch history</a>
            <a href="/admin/onboarding-analytics" class="nav-link">Dashboard</a>
            <a href="/admin/writter" class="nav-link">Writter</a>
            <a href="/settings" class="nav-link">Settings</a>
            <button type="button" class="theme-btn" id="themeToggle" aria-label="Toggle theme">&#9728;</button>
            <a href="/logout" class="nav-link">Log out</a>
        </div>
    </nav>
    <div class="container">
        <h1 class="title">Contact results</h1>
        <table>
            <thead><tr><th>#</th><th>Name</th><th>Email</th><th>Phone</th><th>Date</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="5" class="empty">No submissions yet.</td></tr>'}</tbody>
        </table>
    </div>
    <script>
    (function(){{const t=document.getElementById('themeToggle');if(t){{const k='hp-theme';function g(){{return localStorage.getItem(k)||'dark';}}function s(v){{document.documentElement.setAttribute('data-theme',v);localStorage.setItem(k,v);t.textContent=v==='dark'?'\u2600':'\u263E';}}t.onclick=()=>s(g()==='dark'?'light':'dark');s(g());}}}})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


# Admin: Feedback page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/admin/feedback", response_class=HTMLResponse)
async def admin_feedback_page(request: Request):
    redir = require_admin_redirect(request, "/admin/feedback")
    if redir:
        return redir
    return RedirectResponse(url="/settings?tab=feedback", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# Admin: Users page (redirect to settings tab)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    redir = require_admin_redirect(request, "/admin/users")
    if redir:
        return redir
    return RedirectResponse(url="/settings?tab=users", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# Admin: SEO page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/admin/seo")
async def api_admin_seo(request: Request):
    require_admin_http(request)
    s = _get_settings()
    return {
        "seo_meta_title": s.get("seo_meta_title", ""),
        "seo_meta_description": s.get("seo_meta_description", ""),
        "seo_og_title": s.get("seo_og_title", ""),
        "seo_og_description": s.get("seo_og_description", ""),
        "seo_og_image": s.get("seo_og_image", ""),
        "seo_og_site_name": s.get("seo_og_site_name", ""),
    }


@app.post("/api/admin/seo")
async def api_admin_seo_save(request: Request):
    require_admin_http(request)
    data = await request.json()
    from .db import get_db
    from .services.db_repository import set_setting
    with get_db() as db:
        if "seo_meta_title" in data:
            set_setting(db, "seo_meta_title", str(data["seo_meta_title"]))
        if "seo_meta_description" in data:
            set_setting(db, "seo_meta_description", str(data["seo_meta_description"]))
        if "seo_og_title" in data:
            set_setting(db, "seo_og_title", str(data["seo_og_title"]))
        if "seo_og_description" in data:
            set_setting(db, "seo_og_description", str(data["seo_og_description"]))
        if "seo_og_image" in data:
            set_setting(db, "seo_og_image", str(data["seo_og_image"]))
        if "seo_og_site_name" in data:
            set_setting(db, "seo_og_site_name", str(data["seo_og_site_name"]))
    return JSONResponse({"ok": True})


@app.get("/admin/seo", response_class=HTMLResponse)
async def admin_seo_page(request: Request):
    redir = require_admin_redirect(request, "/admin/seo")
    if redir:
        return redir
    return RedirectResponse(url="/settings?tab=seo", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding analytics (admin) + public tracking API
# ─────────────────────────────────────────────────────────────────────────────

def _format_total_seconds_summary(total_sec: int) -> tuple:
    """Human-readable total time + minutes string for display."""
    if total_sec <= 0:
        return "0m", "0"
    total_min = total_sec // 60
    if total_sec >= 86400:
        main = f"{total_sec // 86400}d {total_sec % 86400 // 3600}h"
    elif total_sec >= 3600:
        main = f"{total_sec // 3600}h {total_sec % 3600 // 60}m"
    else:
        main = f"{max(1, total_min)}m"
    return main, str(total_min)


@app.post("/api/onboarding/start")
async def api_onboarding_start(request: Request):
    """Start a new onboarding session (call from your onboarding wizard)."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    from .db import get_db
    from .services.db_repository import create_onboarding_session

    with get_db() as db:
        public_id = create_onboarding_session(
            db,
            email=data.get("email"),
            name=data.get("name"),
            source=(data.get("source") or data.get("utm_source") or None),
        )
    return JSONResponse({"session_id": public_id})


@app.post("/api/onboarding/step")
async def api_onboarding_step(request: Request):
    """Report progress: step 1–7, optional source (how they found us)."""
    data = await request.json()
    sid = data.get("session_id")
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required")
    step = int(data.get("step", 1))
    from .db import get_db
    from .services.db_repository import update_onboarding_progress

    with get_db() as db:
        ok = update_onboarding_progress(
            db,
            sid,
            step,
            source=data.get("source"),
        )
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"ok": True})


@app.post("/api/onboarding/complete")
async def api_onboarding_complete(request: Request):
    """Mark onboarding as completed (sets duration)."""
    data = await request.json()
    sid = data.get("session_id")
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required")
    from .db import get_db
    from .services.db_repository import complete_onboarding

    with get_db() as db:
        ok = complete_onboarding(db, sid)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"ok": True})


@app.post("/api/onboarding/found-us")
async def api_onboarding_found_us(request: Request):
    """Store self-reported attribution (How they found us) on the cookie-bound session."""
    require_login_http(request)
    sid = request.cookies.get(_OB_COOKIE)
    if not sid:
        raise HTTPException(status_code=400, detail="No onboarding session; open /upload first.")
    try:
        data = await request.json()
    except Exception:
        data = {}
    raw = (data.get("found_via") or data.get("source") or "").strip()
    if not raw or len(raw) > 128:
        raise HTTPException(status_code=400, detail="found_via required (max 128 chars)")
    from .db import get_db
    from .services.db_repository import update_onboarding_progress

    with get_db() as db:
        ok = update_onboarding_progress(db, sid, 1, source=raw)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"ok": True})


@app.get("/api/admin/onboarding-analytics")
async def api_admin_onboarding_analytics(request: Request):
    require_admin_http(request)
    from .db import get_db
    from .services.db_repository import (
        get_onboarding_analytics_summary,
        list_onboarding_sessions,
        get_onboarding_source_filter_options,
    )

    q = request.query_params.get("q") or ""
    source = request.query_params.get("source") or "all"
    status = request.query_params.get("status") or "all"
    with get_db() as db:
        summary = get_onboarding_analytics_summary(db)
        rows = list_onboarding_sessions(db, q=q or None, source=source, status=status)
        src_opts = get_onboarding_source_filter_options(db)
    return {
        "summary": summary,
        "rows": rows,
        "filters": {"source_options": src_opts},
    }


@app.post("/api/admin/onboarding-analytics/clear")
async def api_admin_onboarding_analytics_clear(request: Request):
    """Delete all rows in onboarding_sessions (admin only). Use after removing test/seed data."""
    require_admin_http(request)
    from .db import get_db
    from .services.db_repository import delete_all_onboarding_sessions

    with get_db() as db:
        delete_all_onboarding_sessions(db)
    return JSONResponse({"ok": True})


@app.get("/admin/onboarding-analytics/export")
async def admin_onboarding_export_csv(request: Request):
    """CSV export of onboarding sessions (admin only)."""
    redir = require_admin_redirect(request, "/admin/onboarding-analytics")
    if redir:
        return redir
    import csv as _csv
    import io
    import html as _html
    from .db import get_db
    from .services.db_repository import list_onboarding_sessions

    q = request.query_params.get("q") or ""
    source = request.query_params.get("source") or "all"
    status = request.query_params.get("status") or "all"
    with get_db() as db:
        rows = list_onboarding_sessions(db, q=q or None, source=source, status=status)
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["name", "email", "found_via", "steps", "status", "duration", "date"])
    for r in rows:
        w.writerow(
            [
                r.get("name", ""),
                r.get("email", ""),
                r.get("source", ""),
                r.get("steps", ""),
                r.get("status", ""),
                r.get("duration_label", ""),
                r.get("date", ""),
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="onboarding_sessions.csv"'},
    )


@app.get("/admin/onboarding-analytics", response_class=HTMLResponse)
async def admin_onboarding_analytics_page(
    request: Request,
    q: str = "",
    source: str = "all",
    status: str = "all",
):
    import html as _html
    from .db import get_db
    from .services.db_repository import (
        get_onboarding_analytics_summary,
        list_onboarding_sessions,
        get_onboarding_source_filter_options,
    )

    redir = require_admin_redirect(request, "/admin/onboarding-analytics")
    if redir:
        return redir
    with get_db() as db:
        summary = get_onboarding_analytics_summary(db)
        rows = list_onboarding_sessions(db, q=q or None, source=source, status=status)
        src_opts = get_onboarding_source_filter_options(db)

    started = summary["started"]
    completed = summary["completed"]
    rate = summary["completion_rate"]
    drop_step = _html.escape(summary["biggest_drop_step"])
    total_main, total_min = _format_total_seconds_summary(summary["total_time_seconds"])
    funnel = summary["funnel"]
    funnel_max = max(funnel[0], 1) if funnel else 1
    by_src = summary["by_source"][:12]
    src_max = max((x["count"] for x in by_src), default=1)

    chart_colors = ["#4F46E5", "#22D3EE", "#A78BFA", "#6366f1", "#06b6d4", "#c4b5fd"]

    def hbar_items(items, vmax):
        out = ""
        for i, it in enumerate(items):
            label = _html.escape(it["label"])
            c = it["count"]
            pct = min(100, round(100 * c / vmax)) if vmax else 0
            col = chart_colors[i % len(chart_colors)]
            out += f'<div class="oa-hbar-row"><span class="oa-hbar-label">{label}</span><div class="oa-hbar-track"><div class="oa-hbar-fill" style="width:{pct}%;background:{col}"></div></div><span class="oa-hbar-num">{c}</span></div>'
        return out or '<div class="oa-empty">No data yet</div>'

    funnel_rows = ""
    for i, cnt in enumerate(funnel):
        step_n = i + 1
        h = min(100, round(100 * cnt / funnel_max)) if funnel_max else 0
        funnel_rows += f'<div class="oa-funnel-col"><div class="oa-funnel-bar" style="height:{h}%"></div><span class="oa-funnel-n">{cnt}</span><span class="oa-funnel-s">Step {step_n}</span></div>'

    table_rows = ""
    for r in rows:
        name = _html.escape(r.get("name") or "—")
        email = _html.escape(r.get("email") or "—")
        src = _html.escape(r.get("source") or "—")
        st = r.get("status") or ""
        badge = "oa-badge-done" if st == "completed" else ("oa-badge-warn" if st == "in_progress" else "oa-badge-muted")
        if st == "completed":
            st_label = "Done"
        elif st == "in_progress":
            st_label = "In progress"
        elif st == "abandoned":
            st_label = "Abandoned"
        else:
            st_label = _html.escape(st)
        table_rows += f"""
        <tr>
          <td>{name}</td>
          <td class="oa-mono">{email}</td>
          <td><span class="oa-link">{src}</span></td>
          <td>{_html.escape(r.get("steps") or "")}</td>
          <td><span class="oa-badge {badge}">{st_label}</span></td>
          <td>{_html.escape(r.get("duration_label") or "—")}</td>
          <td>{_html.escape(r.get("date") or "")}</td>
        </tr>"""

    if not table_rows:
        table_rows = '<tr><td colspan="7" class="oa-empty">No sessions match filters.</td></tr>'

    def opt_sel(options, val, name):
        opts = f'<option value="all">All {name}</option>'
        for o in options:
            sel = " selected" if o == val else ""
            opts += f'<option value="{_html.escape(o)}"{sel}>{_html.escape(o)}</option>'
        return opts

    q_esc = _html.escape(q)
    src_sel = opt_sel(src_opts, source, "Sources")
    stat_opts = (
        f'<option value="all"{" selected" if status == "all" else ""}>All statuses</option>'
        f'<option value="completed"{" selected" if status == "completed" else ""}>Done</option>'
        f'<option value="in_progress"{" selected" if status == "in_progress" else ""}>In progress</option>'
        f'<option value="abandoned"{" selected" if status == "abandoned" else ""}>Abandoned</option>'
    )

    from urllib.parse import urlencode

    export_href = "/admin/onboarding-analytics/export?" + urlencode(
        {"q": q, "source": source, "status": status}
    )

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Dashboard — Cartozo.ai</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <link rel="stylesheet" href="/static/styles.css" />
    <style>
    :root {{
      --oa-bg: #0B0F19;
      --oa-surface: #111827;
      --oa-border: rgba(255,255,255,0.08);
      --oa-text: #E5E7EB;
      --oa-muted: #9ca3af;
      --oa-primary: #4F46E5;
      --oa-accent: #22D3EE;
      --oa-violet: #A78BFA;
    }}
    [data-theme="light"] {{
      --oa-bg: #f8fafc;
      --oa-surface: #fff;
      --oa-border: rgba(15,23,42,0.1);
      --oa-text: #0f172a;
      --oa-muted: #64748b;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: var(--oa-bg); color: var(--oa-text); min-height: 100vh; display: flex; flex-direction: column; }}
    .oa-layout {{ display: flex; flex: 1; min-height: 0; }}
    .oa-sidebar {{
      width: 260px; flex-shrink: 0; background: #0a0e18; border-right: 1px solid var(--oa-border);
      display: flex; flex-direction: column; padding: 24px 16px;
    }}
    [data-theme="light"] .oa-sidebar {{ background: #fff; }}
    .oa-brand {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; padding: 0 8px; }}
    .oa-brand img {{ height: 28px; }}
    .oa-brand .logo-light {{ display: block; filter: brightness(0) invert(1); }}
    .oa-brand .logo-dark {{ display: none; }}
    [data-theme="light"] .oa-brand .logo-light {{ display: none; }}
    [data-theme="light"] .oa-brand .logo-dark {{ display: block; filter: none; }}
    .oa-admin-badge {{
      display: inline-block; font-size: 0.65rem; font-weight: 700; letter-spacing: 0.06em;
      padding: 4px 10px; border-radius: 6px; background: rgba(79,70,229,0.2); color: #A78BFA; margin: 12px 8px 24px;
    }}
    .oa-nav {{ display: flex; flex-direction: column; gap: 4px; flex: 1; }}
    .oa-nav a {{
      display: block; padding: 10px 14px; border-radius: 8px; color: var(--oa-muted); text-decoration: none; font-size: 0.9rem;
    }}
    .oa-nav a:hover {{ background: rgba(255,255,255,0.05); color: var(--oa-text); }}
    [data-theme="light"] .oa-nav a:hover {{ background: rgba(15,23,42,0.06); }}
    .oa-nav a.active {{ background: rgba(79,70,229,0.15); color: #4F46E5; font-weight: 600; }}
    .oa-logout {{ margin-top: auto; padding-top: 24px; }}
    .oa-main {{ flex: 1; padding: 28px 32px 48px; overflow-x: auto; }}
    .oa-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 28px; flex-wrap: wrap; gap: 16px; }}
    .oa-title {{ font-size: 1.65rem; font-weight: 700; letter-spacing: -0.02em; }}
    .oa-sub {{ color: var(--oa-muted); font-size: 0.95rem; margin-top: 6px; }}
    .oa-btn-export {{
      display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 8px;
      background: #4F46E5; color: #fff; font-size: 0.88rem; font-weight: 600; text-decoration: none; border: none; cursor: pointer;
    }}
    .oa-btn-export:hover {{ filter: brightness(1.05); }}
    .oa-btn-danger {{
      display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 8px;
      background: transparent; color: #f87171; font-size: 0.88rem; font-weight: 600; border: 1px solid rgba(248,113,113,0.45); cursor: pointer;
    }}
    .oa-btn-danger:hover {{ background: rgba(248,113,113,0.12); }}
    .oa-cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 28px; }}
    @media (max-width: 1200px) {{ .oa-cards {{ grid-template-columns: repeat(3, 1fr); }} }}
    @media (max-width: 768px) {{ .oa-layout {{ flex-direction: column; }} .oa-sidebar {{ width: 100%; border-right: none; border-bottom: 1px solid var(--oa-border); }} .oa-cards {{ grid-template-columns: 1fr 1fr; }} }}
    .oa-card {{
      background: var(--oa-surface); border: 1px solid var(--oa-border); border-radius: 14px; padding: 18px 20px;
    }}
    .oa-card-label {{ font-size: 0.78rem; color: var(--oa-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }}
    .oa-card-val {{ font-size: 1.75rem; font-weight: 700; }}
    .oa-card-hint {{ font-size: 0.75rem; color: var(--oa-muted); margin-top: 6px; line-height: 1.4; }}
    .oa-charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 28px; }}
    @media (max-width: 1024px) {{ .oa-charts {{ grid-template-columns: 1fr; }} }}
    .oa-chart {{
      background: var(--oa-surface); border: 1px solid var(--oa-border); border-radius: 14px; padding: 18px;
    }}
    .oa-chart h3 {{ font-size: 0.95rem; font-weight: 600; margin-bottom: 16px; }}
    .oa-funnel {{
      display: flex; align-items: flex-end; justify-content: space-between; gap: 8px; height: 220px; padding-top: 8px;
    }}
    .oa-funnel-col {{ flex: 1; display: flex; flex-direction: column; align-items: center; gap: 8px; height: 100%; }}
    .oa-funnel-bar {{
      width: 100%; max-width: 48px; margin-top: auto; background: linear-gradient(180deg, #4F46E5, #6366f1);
      border-radius: 6px 6px 0 0; min-height: 4px; transition: height 0.3s ease;
    }}
    .oa-funnel-n {{ font-weight: 700; font-size: 0.9rem; }}
    .oa-funnel-s {{ font-size: 0.68rem; color: var(--oa-muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .oa-hbar-row {{ display: grid; grid-template-columns: 1fr 1fr auto; gap: 10px; align-items: center; margin-bottom: 10px; font-size: 0.82rem; }}
    .oa-hbar-label {{ color: var(--oa-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .oa-hbar-track {{ height: 8px; background: rgba(255,255,255,0.06); border-radius: 99px; overflow: hidden; }}
    [data-theme="light"] .oa-hbar-track {{ background: rgba(15,23,42,0.08); }}
    .oa-hbar-fill {{ height: 100%; border-radius: 99px; min-width: 2px; }}
    .oa-hbar-num {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
    .oa-toolbar {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; align-items: center; }}
    .oa-toolbar input, .oa-toolbar select {{
      padding: 10px 14px; border-radius: 8px; border: 1px solid var(--oa-border); background: var(--oa-surface); color: var(--oa-text); font-size: 0.88rem;
    }}
    .oa-toolbar input {{ flex: 1; min-width: 200px; max-width: 360px; }}
    .oa-table-wrap {{ overflow-x: auto; border: 1px solid var(--oa-border); border-radius: 12px; }}
    table.oa-table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    .oa-table th {{
      text-align: left; padding: 12px 14px; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--oa-muted);
      border-bottom: 1px solid var(--oa-border); background: rgba(79,70,229,0.06);
    }}
    .oa-table td {{ padding: 12px 14px; border-bottom: 1px solid var(--oa-border); }}
    .oa-table tr:last-child td {{ border-bottom: none; }}
    .oa-mono {{ font-size: 0.82rem; }}
    .oa-link {{ color: #22D3EE; text-decoration: none; }}
    .oa-link:hover {{ text-decoration: underline; }}
    .oa-pill {{
      display: inline-block; padding: 4px 10px; border-radius: 8px; font-size: 0.78rem; font-weight: 500;
      background: rgba(167,139,250,0.15); color: #A78BFA; border: 1px solid rgba(167,139,250,0.25);
    }}
    .oa-badge {{ display: inline-block; padding: 4px 10px; border-radius: 8px; font-size: 0.78rem; font-weight: 600; }}
    .oa-badge-done {{ background: rgba(34,197,94,0.15); color: #4ade80; }}
    .oa-badge-warn {{ background: rgba(251,191,36,0.2); color: #fbbf24; }}
    .oa-badge-muted {{ background: rgba(148,163,184,0.15); color: #94a3b8; }}
    .oa-empty {{ text-align: center; padding: 24px; color: var(--oa-muted); }}
    </style>
</head>
<body>
{GTM_BODY}
    {admin_top_nav_html('dashboard')}
    <div class="oa-layout">
      <aside class="oa-sidebar">
        <div class="oa-brand">
          <a href="/"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        </div>
        <span class="oa-admin-badge">ADMIN</span>
        <nav class="oa-nav">
          <a href="/admin/onboarding-analytics" class="active">Dashboard</a>
          <a href="/admin/writter">Writter</a>
          <a href="/admin/contact-results">Contact results</a>
          <a href="/settings">Settings</a>
        </nav>
        <div class="oa-logout">
          <a href="/logout" class="oa-nav" style="padding:10px 14px;border-radius:8px;color:var(--oa-muted);">Log out</a>
        </div>
      </aside>
      <main class="oa-main">
        <div class="oa-header">
          <div>
            <h1 class="oa-title">Dashboard</h1>
            <p class="oa-sub">{started} users started onboarding</p>
          </div>
          <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
            <a class="oa-btn-export" href="{_html.escape(export_href)}">Export CSV</a>
            <button type="button" class="oa-btn-danger" id="oaClearAll">Clear all data</button>
          </div>
        </div>
        <div class="oa-cards">
          <div class="oa-card">
            <div class="oa-card-label">Started</div>
            <div class="oa-card-val">{started}</div>
          </div>
          <div class="oa-card">
            <div class="oa-card-label">Completed</div>
            <div class="oa-card-val">{completed}</div>
          </div>
          <div class="oa-card">
            <div class="oa-card-label">Completion rate</div>
            <div class="oa-card-val">{rate}%</div>
          </div>
          <div class="oa-card">
            <div class="oa-card-label">Biggest drop-off</div>
            <div class="oa-card-val" style="font-size:1.35rem;">{drop_step}</div>
          </div>
          <div class="oa-card">
            <div class="oa-card-label">Total time</div>
            <div class="oa-card-val">{_html.escape(total_main)}</div>
            <div class="oa-card-hint">Sum of all completed session durations · {total_min} min total</div>
          </div>
        </div>
        <div class="oa-charts">
          <div class="oa-chart">
            <h3>Onboarding funnel</h3>
            <div class="oa-funnel">{funnel_rows}</div>
          </div>
          <div class="oa-chart">
            <h3>How they found us</h3>
            {hbar_items(by_src, src_max)}
          </div>
        </div>
        <form class="oa-toolbar" method="get" action="/admin/onboarding-analytics">
          <input type="search" name="q" placeholder="Search by name or email…" value="{q_esc}" />
          <select name="source">{src_sel}</select>
          <select name="status">{stat_opts}</select>
          <button type="submit" class="oa-btn-export" style="background:#4338ca;">Apply</button>
        </form>
        <div class="oa-table-wrap">
          <table class="oa-table">
            <thead>
              <tr>
                <th>Name</th><th>Email</th><th>Found us via</th><th>Steps</th><th>Status</th><th>Time</th><th>Date</th>
              </tr>
            </thead>
            <tbody>{table_rows}</tbody>
          </table>
        </div>
      </main>
    </div>
    <script>
    {ADMIN_THEME_SCRIPT}
    {ADMIN_MERCHANT_SCRIPT}
    (function(){{var b=document.getElementById('oaClearAll');if(!b)return;b.onclick=function(){{if(!confirm('Delete all onboarding rows in this database? Cannot be undone.'))return;b.disabled=true;fetch('/api/admin/onboarding-analytics/clear',{{method:'POST',credentials:'same-origin'}}).then(function(r){{if(r.ok)location.reload();else r.text().then(function(t){{alert('Failed: '+t);b.disabled=false;}});}}).catch(function(e){{alert(e);b.disabled=false;}});}};}})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


register_writter_routes(app)
