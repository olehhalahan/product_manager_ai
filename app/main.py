from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.middleware.sessions import SessionMiddleware
from typing import List, Optional
import io
import csv
import uuid

from .models import NormalizedProduct, BatchStatus, BatchSummary
from .services.importer import parse_csv_file
from .services.normalizer import normalize_records, guess_mapping, INTERNAL_FIELDS
from .services.rule_engine import decide_actions_for_products
from .services.exporter import generate_result_csv
from .services.storage import InMemoryStorage
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


app = FastAPI(title="Product Content Optimizer", docs_url=None)
app.add_middleware(SessionMiddleware, secret_key=get_session_secret())

storage = InMemoryStorage()

# Settings storage (in-memory, would be DB in production)
_settings: dict = {
    "openai_api_key": "",
    "prompt_title": """You are an SEO expert. Optimize the following product title for search engines.
Keep it under 120 characters. Include relevant keywords. Use a pipe separator for secondary phrases.

Original title: {title}
Category: {category}
Brand: {brand}
Attributes: {attributes}

Return only the optimized title, nothing else.""",
    "prompt_description": """You are an e-commerce copywriter. Write a compelling product description.
Keep it 2-3 paragraphs. Focus on benefits and features. Do not mention price.

Product: {title}
Category: {category}
Brand: {brand}
Attributes: {attributes}
Original description: {description}

Return only the description, nothing else.""",
}

# Temp store for uploaded CSV data waiting for column mapping confirmation.
_pending_uploads: dict = {}

import os as _os

_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA_DIR = _os.path.join(_PROJECT_ROOT, "data")
_os.makedirs(_DATA_DIR, exist_ok=True)

_FEEDBACK_FILE = _os.path.join(_DATA_DIR, "feedback.json")
_USERS_FILE = _os.path.join(_DATA_DIR, "users.json")


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _os.replace(tmp, path)


_feedback_store: list = _load_json(_FEEDBACK_FILE, [])
_users_db: dict = _load_json(_USERS_FILE, {})


def _save_feedback():
    _save_json(_FEEDBACK_FILE, _feedback_store)


def _save_users():
    _save_json(_USERS_FILE, _users_db)


def _track_user(user: dict):
    """Record user in tracking DB on login and persist to disk."""
    email = user.get("email", "")
    now = datetime.now(timezone.utc).isoformat()
    if email not in _users_db:
        _users_db[email] = {
            "name": user.get("name", ""),
            "email": email,
            "provider": user.get("provider", ""),
            "role": user.get("role", "customer"),
            "first_seen": now,
            "last_login": now,
        }
    else:
        _users_db[email]["last_login"] = now
        _users_db[email]["name"] = user.get("name", _users_db[email]["name"])
    _save_users()
app.mount("/static", StaticFiles(directory=_os.path.join(_PROJECT_ROOT, "static")), name="static")
app.mount("/assets", StaticFiles(directory=_os.path.join(_PROJECT_ROOT, "assets")), name="assets")


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
    import os
    has_google = bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))
    has_apple = bool(os.getenv("APPLE_CLIENT_ID") and os.getenv("APPLE_KEY_ID") and os.getenv("APPLE_TEAM_ID") and os.getenv("APPLE_PRIVATE_KEY"))
    next_url = request.query_params.get("next", "/upload")
    return HTMLResponse(content=_build_login_page(next_url=next_url, has_google=has_google, has_apple=has_apple))


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
    redirect_uri = str(request.url_for("auth_google_callback"))
    return await client.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback", name="auth_google_callback")
async def auth_google_callback(request: Request):
    """Handle Google OAuth callback."""
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
    import os
    if not (os.getenv("GOOGLE_CLIENT_ID") or os.getenv("APPLE_CLIENT_ID")):
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


def _admin_nav_links(active: str = "", user_role: str = "customer") -> str:
    """Generate admin-only nav links (Feedback, Users, Settings) if user is admin."""
    if user_role != "admin":
        return ""
    links = []
    links.append(f'<a href="/admin/feedback" class="nav-link{" active" if active == "feedback" else ""}">Feedback</a>')
    links.append(f'<a href="/admin/users" class="nav-link{" active" if active == "users" else ""}">Users</a>')
    links.append(f'<a href="/settings" class="nav-link{" active" if active == "settings" else ""}">Settings</a>')
    return "\n            ".join(links)


HOMEPAGE_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Sartozo.AI — AI-Powered Product Feed Optimization</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{opacity:0;transition:opacity .28s ease}body.page-transition-out{opacity:0;pointer-events:none}</style>
    <link rel="stylesheet" href="/static/styles.css" />
    <style>
    html { scroll-behavior: smooth; }
    :root, [data-theme="dark"] { --hp-bg: #000; --hp-text: #fff; --hp-muted: rgba(255,255,255,0.6); --hp-border: rgba(255,255,255,0.1); }
    [data-theme="light"] { --hp-bg: #f8fafc; --hp-text: #0f172a; --hp-muted: rgba(15,23,42,0.6); --hp-border: rgba(15,23,42,0.12); }

    .hp-body { background: var(--hp-bg); color: var(--hp-text); min-height: 100vh; overflow-x: hidden; position: relative; }
    .hp-container { max-width: 1440px; margin: 0 auto; }
    
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
    .hp-bg-glow { border-radius: 50%; background: radial-gradient(circle, rgba(193,68,14,0.08) 0%, transparent 70%); }

    /* Navigation */
    .hp-nav { display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; position: fixed; top: 0; left: 0; right: 0; z-index: 1000; background: rgba(0,0,0,0.85); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255,255,255,0.06); }
    [data-theme="light"] .hp-nav { background: rgba(248,250,252,0.95); border-bottom-color: rgba(15,23,42,0.08); }
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

    /* Hero */
    .hp-hero { text-align: center; padding: 160px 24px 120px; position: relative; min-height: 600px; }
    .hp-badge { display: inline-block; color: var(--hp-muted); font-size: 0.85rem; margin-bottom: 28px; letter-spacing: 0.02em; }
    .hp-title { font-size: clamp(2.5rem, 6vw, 4rem); font-weight: 600; line-height: 1.1; margin-bottom: 24px; letter-spacing: -0.03em; position: relative; z-index: 2; }
    .hp-sub { font-size: 1.1rem; color: var(--hp-muted); max-width: 540px; margin: 0 auto 40px; line-height: 1.6; position: relative; z-index: 2; }
    .hp-buttons { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; position: relative; z-index: 2; }
    .hp-btn { padding: 14px 28px; border-radius: 6px; font-size: 0.9rem; font-weight: 500; text-decoration: none; transition: all 0.3s ease; }
    .hp-btn-primary { background: var(--hp-text); color: var(--hp-bg); }
    .hp-btn-primary:hover { opacity: 0.9; transform: translateY(-2px); box-shadow: 0 10px 30px rgba(255,255,255,0.1); }
    .hp-btn-secondary { background: transparent; color: var(--hp-text); border: 1px solid var(--hp-border); }
    .hp-btn-secondary:hover { border-color: rgba(255,255,255,0.3); background: rgba(255,255,255,0.05); }

    /* Mars Planet - positioned left */
    .hp-planet-container { position: absolute; width: 380px; height: 380px; z-index: 1; animation: orbit-hero 260s ease-in-out infinite; transition: transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1); }
    .hp-planet-container.scared { animation-play-state: paused; }
    .hp-mars { cursor: pointer; pointer-events: auto; }
    @keyframes orbit-hero {
        0% { left: -100px; top: 30%; }
        25% { left: 85%; top: 10%; }
        50% { left: 90%; top: 70%; }
        75% { left: 5%; top: 80%; }
        100% { left: -100px; top: 30%; }
    }
    .hp-planet { position: relative; width: 100%; height: 100%; }
    .hp-mars { position: absolute; top: 50%; left: 50%; width: 180px; height: 180px; margin: -90px 0 0 -90px; border-radius: 50%; background: radial-gradient(circle at 30% 25%, #e8a87c, #c1440e 40%, #8b2500 70%, #4a1a0a 100%); box-shadow: 0 0 60px rgba(193,68,14,0.5), 0 0 120px rgba(193,68,14,0.3), inset -20px -20px 40px rgba(0,0,0,0.4), inset 10px 10px 30px rgba(255,200,150,0.15); animation: marsFloat 8s ease-in-out infinite; overflow: hidden; transition: background 0.5s, box-shadow 0.5s; }
    [data-theme="light"] .hp-mars { background: radial-gradient(circle at 30% 25%, #5a5a5a, #3d3d3d 40%, #252525 70%, #141414 100%); box-shadow: 0 0 60px rgba(60,60,60,0.35), 0 0 100px rgba(60,60,60,0.15), inset -20px -20px 40px rgba(0,0,0,0.3), inset 10px 10px 30px rgba(90,90,90,0.15); }
    .hp-crater { position: absolute; border-radius: 50%; background: rgba(74,26,10,0.4); box-shadow: inset 2px 2px 4px rgba(0,0,0,0.3); }
    [data-theme="light"] .hp-crater { background: rgba(20,20,20,0.5); }
    .hp-crater-1 { width: 20px; height: 20px; top: 35%; left: 40%; }
    .hp-crater-2 { width: 12px; height: 12px; top: 65%; left: 25%; }
    .hp-crater-3 { width: 15px; height: 15px; top: 25%; left: 65%; }
    @keyframes marsFloat { 0%, 100% { transform: translate(-50%, -50%) translateY(0); } 50% { transform: translate(-50%, -50%) translateY(-15px); } }
    @keyframes marsSpin { from { background-position: 0 0; } to { background-position: 200px 0; } }

    /* Mars glow */
    .hp-mars-glow { position: absolute; top: 50%; left: 50%; width: 280px; height: 280px; margin: -140px 0 0 -140px; border-radius: 50%; background: radial-gradient(circle, rgba(193,68,14,0.2) 0%, rgba(193,68,14,0.1) 40%, transparent 70%); animation: glowPulse 4s ease-in-out infinite; transition: background 0.5s; }
    [data-theme="light"] .hp-mars-glow { background: radial-gradient(circle, rgba(60,60,60,0.2) 0%, rgba(60,60,60,0.1) 40%, transparent 70%); }
    @keyframes glowPulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.15); opacity: 0.7; } }

    /* Orbits around Mars */
    .hp-orbit { position: absolute; top: 50%; left: 50%; border: 1px solid rgba(255,255,255,0.06); border-radius: 50%; }
    .hp-orbit-1 { width: 240px; height: 240px; margin: -120px 0 0 -120px; animation: orbitSpin 15s linear infinite; transform-origin: center; }
    .hp-orbit-2 { width: 320px; height: 320px; margin: -160px 0 0 -160px; animation: orbitSpin 25s linear infinite reverse; border-style: dashed; }
    .hp-orbit-3 { width: 380px; height: 380px; margin: -190px 0 0 -190px; animation: orbitSpin 35s linear infinite; border-color: rgba(255,255,255,0.03); }
    @keyframes orbitSpin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

    /* Moons/satellites */
    .hp-moon { position: absolute; border-radius: 50%; box-shadow: 0 0 15px currentColor; animation: moonGlow 2s ease-in-out infinite; }
    .hp-orbit-1 .hp-moon { width: 10px; height: 10px; top: -5px; left: 50%; margin-left: -5px; background: #f59e0b; color: rgba(245,158,11,0.6); }
    .hp-orbit-2 .hp-moon { width: 8px; height: 8px; top: 50%; right: -4px; margin-top: -4px; background: #ef4444; color: rgba(239,68,68,0.6); animation-delay: 0.5s; }
    .hp-orbit-3 .hp-moon { width: 6px; height: 6px; bottom: 20%; left: -3px; background: #a855f7; color: rgba(168,85,247,0.6); animation-delay: 1s; }
    @keyframes moonGlow { 0%, 100% { box-shadow: 0 0 10px currentColor; } 50% { box-shadow: 0 0 20px currentColor, 0 0 30px currentColor; } }

    /* Floating particles */
    .hp-particles { position: absolute; width: 100%; height: 100%; top: 0; left: 0; }
    .hp-particle { position: absolute; width: 3px; height: 3px; background: rgba(255,255,255,0.4); border-radius: 50%; animation: particleDrift 8s ease-in-out infinite; }
    .hp-particle:nth-child(1) { top: 20%; left: 30%; animation-delay: 0s; }
    .hp-particle:nth-child(2) { top: 60%; left: 70%; animation-delay: 2s; animation-duration: 10s; }
    .hp-particle:nth-child(3) { top: 40%; left: 85%; animation-delay: 4s; animation-duration: 12s; }
    .hp-particle:nth-child(4) { top: 80%; left: 20%; animation-delay: 1s; animation-duration: 9s; }
    @keyframes particleDrift { 0%, 100% { transform: translate(0, 0); opacity: 0.4; } 25% { transform: translate(10px, -15px); opacity: 0.8; } 50% { transform: translate(-5px, -25px); opacity: 0.4; } 75% { transform: translate(-15px, -10px); opacity: 0.7; } }

    /* Features — premium glassmorphism design */
    .hp-features { padding: 140px 48px 160px; position: relative; overflow: hidden; background: linear-gradient(180deg, transparent 0%, rgba(249,115,22,0.02) 30%, rgba(168,85,247,0.02) 70%, transparent 100%); }
    .hp-features .hp-container { position: relative; z-index: 1; max-width: 1200px; margin: 0 auto; }
    .hp-features-bg { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
    .hp-features-bg .circle-1 { position: absolute; width: 600px; height: 600px; top: -200px; right: -200px; background: radial-gradient(circle, rgba(249,115,22,0.08) 0%, rgba(168,85,247,0.04) 40%, transparent 70%); border-radius: 50%; filter: blur(60px); }
    .hp-features-bg .circle-2 { position: absolute; width: 500px; height: 500px; bottom: -150px; left: -150px; background: radial-gradient(circle, rgba(59,130,246,0.06) 0%, transparent 60%); border-radius: 50%; filter: blur(80px); }
    .hp-features-bg .glow-1 { position: absolute; width: 400px; height: 400px; top: 30%; left: 50%; transform: translateX(-50%); background: radial-gradient(circle, rgba(249,115,22,0.04) 0%, transparent 70%); border-radius: 50%; filter: blur(100px); }
    .hp-features-header { text-align: center; margin-bottom: 80px; opacity: 0; transform: translateY(40px); transition: all 0.9s cubic-bezier(0.16, 1, 0.3, 1); }
    .hp-features-header.visible { opacity: 1; transform: translateY(0); }
    .hp-features-title { font-size: clamp(2rem, 4vw, 3rem); font-weight: 700; margin-bottom: 20px; letter-spacing: -0.04em; line-height: 1.15; background: linear-gradient(135deg, #fff 0%, rgba(255,255,255,0.85) 50%, rgba(255,255,255,0.7) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    [data-theme="light"] .hp-features-title { background: linear-gradient(135deg, #0f172a 0%, #334155 50%, #475569 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .hp-features-sub { color: var(--hp-muted); font-size: 1.15rem; font-weight: 400; letter-spacing: 0.01em; max-width: 480px; margin: 0 auto; line-height: 1.7; }
    .hp-features-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 28px; max-width: 1160px; margin: 0 auto; }
    @media (max-width: 1024px) { .hp-features-grid { grid-template-columns: repeat(2, 1fr); gap: 24px; } }
    @media (max-width: 640px) { .hp-features-grid { grid-template-columns: 1fr; gap: 20px; } .hp-features { padding: 80px 24px 100px; } }
    
    .hp-feature { position: relative; padding: 36px 32px; border-radius: 20px; overflow: hidden; opacity: 0; transform: translateY(36px); transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1); 
      background: linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%); 
      border: 1px solid rgba(255,255,255,0.08); 
      backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
      box-shadow: 0 4px 24px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.06); }
    .hp-feature.visible { opacity: 1; transform: translateY(0); }
    .hp-feature:hover { transform: translateY(-6px) scale(1.01); 
      border-color: rgba(249,115,22,0.25); 
      box-shadow: 0 24px 48px rgba(0,0,0,0.3), 0 0 0 1px rgba(249,115,22,0.15), inset 0 1px 0 rgba(255,255,255,0.08); 
      background: linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(249,115,22,0.04) 100%); }
    .hp-feature::before { content: ''; position: absolute; inset: 0; border-radius: inherit; padding: 1px; background: linear-gradient(135deg, rgba(255,255,255,0.12), transparent 50%, rgba(249,115,22,0.08)); -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); -webkit-mask-composite: xor; mask-composite: exclude; pointer-events: none; opacity: 0; transition: opacity 0.4s; }
    .hp-feature:hover::before { opacity: 1; }
    [data-theme="light"] .hp-feature { background: linear-gradient(135deg, rgba(255,255,255,0.95) 0%, rgba(248,250,252,0.9) 100%); border-color: rgba(15,23,42,0.08); box-shadow: 0 4px 24px rgba(15,23,42,0.06); }
    [data-theme="light"] .hp-feature:hover { border-color: rgba(249,115,22,0.3); box-shadow: 0 24px 48px rgba(15,23,42,0.1); }
    
    .hp-feature-visual { position: relative; height: 100px; margin-bottom: 24px; display: flex; align-items: center; justify-content: center; }
    .hp-feature-icon-wrap { position: relative; width: 64px; height: 64px; display: flex; align-items: center; justify-content: center; border-radius: 16px; z-index: 2; transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
      background: linear-gradient(145deg, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0.04) 100%);
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: 0 4px 12px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.1);
      color: rgba(255,255,255,0.95); }
    .hp-feature-icon-wrap svg { flex-shrink: 0; }
    .hp-feature:hover .hp-feature-icon-wrap { transform: scale(1.08); 
      box-shadow: 0 8px 24px rgba(249,115,22,0.2), inset 0 1px 0 rgba(255,255,255,0.15);
      background: linear-gradient(145deg, rgba(249,115,22,0.2) 0%, rgba(249,115,22,0.05) 100%);
      border-color: rgba(249,115,22,0.3);
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
    .hp-feature:nth-child(odd) .hp-feature-dot { background: rgba(249,115,22,0.4); }
    @keyframes float-dot { 0%, 100% { transform: translateY(0) scale(1); opacity: 0.35; } 50% { transform: translateY(-10px) scale(1.3); opacity: 0.85; } }
    
    .hp-feature-ring { position: absolute; border: 1px solid rgba(255,255,255,0.06); border-radius: 50%; }
    .hp-feature-ring-1 { width: 100px; height: 100px; animation: pulse-ring 5s ease-in-out infinite; }
    .hp-feature-ring-2 { width: 150px; height: 150px; animation: pulse-ring 5s ease-in-out infinite 1.2s; }
    @keyframes pulse-ring { 0%, 100% { transform: scale(1); opacity: 0.2; } 50% { transform: scale(1.08); opacity: 0.5; } }
    
    .hp-feature-title { font-size: 1.1rem; font-weight: 700; margin-bottom: 12px; letter-spacing: -0.02em; color: var(--hp-text); line-height: 1.3; }
    .hp-feature-desc { font-size: 0.9rem; color: var(--hp-muted); line-height: 1.65; letter-spacing: 0.01em; }

    /* Feed structure showcase - Google Merchant (premium design) */
    .hp-feed-section { padding: 120px 48px; border-top: 1px solid var(--hp-border); position: relative; overflow: hidden; }
    .hp-feed-section::before { content: ''; position: absolute; inset: 0; background: radial-gradient(ellipse 80% 50% at 50% 0%, rgba(249,115,22,0.06) 0%, transparent 60%); pointer-events: none; }
    .hp-feed-section .hp-container { position: relative; z-index: 1; max-width: 1280px; }
    .hp-feed-header { text-align: center; margin-bottom: 56px; }
    .hp-feed-label { display: block; font-size: 0.8rem; font-weight: 500; letter-spacing: 0.12em; text-transform: uppercase; color: #f97316; margin-bottom: 16px; text-align: center; }
    .hp-feed-title { font-size: clamp(2rem, 4vw, 2.75rem); font-weight: 700; margin-bottom: 16px; letter-spacing: -0.04em; line-height: 1.2; padding: 0.08em 0; display: inline-block; background: linear-gradient(135deg, var(--hp-text) 0%, var(--hp-muted) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    [data-theme="light"] .hp-feed-title { background: linear-gradient(135deg, #0f172a 0%, #475569 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .hp-feed-sub { color: var(--hp-muted); font-size: 1.05rem; max-width: 520px; margin: 0 auto; line-height: 1.6; }
    .hp-feed-block { position: relative; border-radius: 20px; overflow: hidden; opacity: 0; transform: translateY(32px) perspective(1000px) rotateX(2deg); transition: opacity 0.9s cubic-bezier(0.16, 1, 0.3, 1), transform 0.9s cubic-bezier(0.16, 1, 0.3, 1); }
    .hp-feed-section.visible .hp-feed-block { opacity: 1; transform: translateY(0) perspective(1000px) rotateX(0); }
    .hp-feed-block::before { content: ''; position: absolute; inset: -2px; border-radius: 22px; padding: 2px; background: linear-gradient(135deg, rgba(249,115,22,0.6), rgba(168,85,247,0.4), rgba(249,115,22,0.5)); -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0); -webkit-mask-composite: xor; mask-composite: exclude; pointer-events: none; z-index: 2; animation: feedBorderGlow 4s ease-in-out infinite; }
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
    .hp-feed-window-badge { padding: 4px 12px; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.05em; border-radius: 6px; background: linear-gradient(135deg, rgba(249,115,22,0.2), rgba(249,115,22,0.1)); color: #f97316; border: 1px solid rgba(249,115,22,0.3); }
    .hp-feed-scan { position: absolute; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, transparent, rgba(249,115,22,0.6), rgba(168,85,247,0.4), transparent); animation: feedScan 5s ease-in-out infinite; pointer-events: none; z-index: 1; filter: blur(1px); }
    @keyframes feedScan { 0% { top: 52px; opacity: 0; } 5% { opacity: 1; } 95% { opacity: 1; } 100% { top: calc(100% - 80px); opacity: 0; } }
    .hp-feed-table-wrap { overflow-x: auto; padding: 0; margin: 0; }
    .hp-feed-table-wrap::-webkit-scrollbar { height: 8px; }
    .hp-feed-table-wrap::-webkit-scrollbar-track { background: rgba(255,255,255,0.03); border-radius: 4px; }
    .hp-feed-table-wrap::-webkit-scrollbar-thumb { background: rgba(249,115,22,0.3); border-radius: 4px; }
    .hp-feed-table-wrap::-webkit-scrollbar-thumb:hover { background: rgba(249,115,22,0.5); }
    .hp-feed-table { width: 100%; min-width: 950px; border-collapse: separate; border-spacing: 0; font-size: 0.76rem; font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace; }
    .hp-feed-table th, .hp-feed-table td { padding: 12px 16px; text-align: left; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); position: relative; }
    .hp-feed-table th { background: linear-gradient(180deg, rgba(249,115,22,0.12) 0%, rgba(249,115,22,0.06) 100%); color: #fbbf24; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.68rem; border-bottom: 1px solid rgba(249,115,22,0.2); }
    [data-theme="light"] .hp-feed-table th { background: linear-gradient(180deg, rgba(249,115,22,0.15) 0%, rgba(249,115,22,0.08) 100%); color: #b45309; border-bottom-color: rgba(249,115,22,0.25); }
    .hp-feed-table td { color: rgba(255,255,255,0.7); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-bottom: 1px solid rgba(255,255,255,0.04); }
    [data-theme="light"] .hp-feed-table td { color: rgba(15,23,42,0.8); border-bottom-color: rgba(15,23,42,0.06); }
    .hp-feed-table tbody tr:hover td { background: rgba(249,115,22,0.06); color: var(--hp-text); }
    [data-theme="light"] .hp-feed-table tbody tr:hover td { background: rgba(249,115,22,0.08); color: #0f172a; }
    .hp-feed-table th:hover { background: rgba(249,115,22,0.18); color: #fcd34d; }
    .hp-feed-table td:hover { background: rgba(249,115,22,0.1) !important; }
    .hp-feed-table .hp-feed-cell-id { color: #a78bfa; }
    .hp-feed-table .hp-feed-cell-title { color: #fbbf24; font-weight: 500; }
    .hp-feed-table .hp-feed-cell-price { color: #34d399; font-weight: 600; }
    .hp-feed-table .hp-feed-cell-brand { color: #60a5fa; }
    [data-theme="light"] .hp-feed-table .hp-feed-cell-id { color: #7c3aed; }
    [data-theme="light"] .hp-feed-table .hp-feed-cell-title { color: #b45309; }
    [data-theme="light"] .hp-feed-table .hp-feed-cell-price { color: #059669; }
    [data-theme="light"] .hp-feed-table .hp-feed-cell-brand { color: #2563eb; }
    .hp-feed-table tr { animation: feedRowReveal 0.6s cubic-bezier(0.16, 1, 0.3, 1) backwards; }
    .hp-feed-table thead tr { animation-delay: 0.15s; }
    .hp-feed-table tbody tr { animation-delay: 0.35s; }
    @keyframes feedRowReveal { from { opacity: 0; transform: translateX(-12px); } to { opacity: 1; transform: translateX(0); } }
    .hp-feed-footer { display: flex; align-items: center; justify-content: center; gap: 24px; flex-wrap: wrap; padding: 20px 24px; background: rgba(0,0,0,0.2); border-top: 1px solid rgba(255,255,255,0.06); }
    [data-theme="light"] .hp-feed-footer { background: rgba(15,23,42,0.03); border-top-color: rgba(15,23,42,0.08); }
    .hp-feed-badge { display: inline-flex; align-items: center; gap: 8px; padding: 8px 18px; font-size: 0.85rem; font-weight: 600; border-radius: 10px; background: linear-gradient(135deg, rgba(249,115,22,0.2), rgba(249,115,22,0.1)); color: #f97316; border: 1px solid rgba(249,115,22,0.3); }
    .hp-feed-badge::before { content: '✓'; font-weight: 700; color: #34d399; }
    [data-theme="light"] .hp-feed-badge { background: linear-gradient(135deg, rgba(249,115,22,0.15), rgba(249,115,22,0.08)); color: #c2410c; border-color: rgba(249,115,22,0.25); }
    .hp-feed-meta { font-size: 0.78rem; color: var(--hp-muted); }
    @media (max-width: 768px) { .hp-feed-section { padding: 80px 24px; } .hp-feed-table { font-size: 0.7rem; min-width: 750px; } .hp-feed-block::before { animation: none; } }

    /* How it works */
    .hp-steps { padding: 100px 48px; text-align: center; position: relative; overflow: hidden; }
    .hp-steps-bg { position: absolute; inset: 0; pointer-events: none; }
    .hp-steps-bg .line-1 { position: absolute; width: 1px; height: 200px; left: 20%; top: 0; background: linear-gradient(180deg, transparent, rgba(255,255,255,0.05), transparent); }
    .hp-steps-bg .line-2 { position: absolute; width: 1px; height: 250px; right: 15%; bottom: 0; background: linear-gradient(180deg, transparent, rgba(255,255,255,0.04), transparent); }
    .hp-steps-bg .circle-1 { position: absolute; width: 200px; height: 200px; border: 1px solid rgba(255,255,255,0.03); border-radius: 50%; left: 5%; top: 30%; }
    .hp-steps .hp-container { position: relative; z-index: 1; }
    .hp-steps-title { font-size: 2.2rem; font-weight: 600; margin-bottom: 12px; letter-spacing: -0.02em; }
    .hp-steps-sub { color: var(--hp-muted); font-size: 1rem; margin-bottom: 64px; }
    .hp-steps-grid { display: flex; justify-content: center; gap: 64px; flex-wrap: wrap; max-width: 900px; margin: 0 auto; }
    .hp-step { text-align: center; max-width: 240px; }
    .hp-step-num { width: 48px; height: 48px; border: 2px solid var(--hp-border); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.1rem; font-weight: 600; margin: 0 auto 20px; transition: border-color 0.3s, background 0.3s; }
    .hp-step:hover .hp-step-num { border-color: rgba(193,68,14,0.6); background: rgba(193,68,14,0.1); }
    [data-theme="light"] .hp-step:hover .hp-step-num { border-color: rgba(15,23,42,0.4); background: rgba(15,23,42,0.06); }
    .hp-step-title { font-size: 1rem; font-weight: 600; margin-bottom: 8px; }
    .hp-step-desc { font-size: 0.85rem; color: var(--hp-muted); line-height: 1.5; }

    /* CTA */
    .hp-cta { padding: 100px 48px; text-align: center; border-top: 1px solid var(--hp-border); position: relative; overflow: hidden; }
    .hp-cta-bg { position: absolute; inset: 0; pointer-events: none; }
    .hp-cta-bg .circle-1 { position: absolute; width: 600px; height: 600px; border: 1px dashed rgba(255,255,255,0.03); border-radius: 50%; left: 50%; top: 50%; transform: translate(-50%, -50%); }
    .hp-cta-bg .circle-2 { position: absolute; width: 400px; height: 400px; border: 1px solid rgba(255,255,255,0.04); border-radius: 50%; left: 50%; top: 50%; transform: translate(-50%, -50%); }
    .hp-cta-bg .glow { position: absolute; width: 300px; height: 300px; background: radial-gradient(circle, rgba(193,68,14,0.08) 0%, transparent 70%); border-radius: 50%; left: 50%; top: 50%; transform: translate(-50%, -50%); }
    .hp-cta .hp-container { position: relative; z-index: 1; }
    .hp-cta-title { font-size: 2rem; font-weight: 600; margin-bottom: 16px; letter-spacing: -0.02em; }
    .hp-cta-sub { color: var(--hp-muted); font-size: 1rem; margin-bottom: 32px; }

    /* Footer */
    .hp-footer { padding: 32px 48px; text-align: center; font-size: 0.82rem; color: var(--hp-muted); border-top: 1px solid var(--hp-border); }

    /* Back to top button */
    .back-to-top { position: fixed; bottom: 32px; right: 32px; width: 48px; height: 48px; border-radius: 50%; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15); color: var(--hp-text); font-size: 1.2rem; cursor: pointer; opacity: 0; visibility: hidden; transform: translateY(20px); transition: all 0.3s ease; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(10px); z-index: 999; }
    .back-to-top:hover { background: rgba(255,255,255,0.2); border-color: rgba(255,255,255,0.3); transform: translateY(-2px); }
    [data-theme="light"] .back-to-top { background: rgba(15,23,42,0.08); border-color: rgba(15,23,42,0.15); }
    [data-theme="light"] .back-to-top:hover { background: rgba(15,23,42,0.15); border-color: rgba(15,23,42,0.25); }
    .back-to-top.visible { opacity: 1; visibility: visible; transform: translateY(0); }

    @media (max-width: 1024px) {
        .hp-planet-container { width: 320px; height: 320px; animation-duration: 260s; }
        .hp-mars { width: 140px; height: 140px; margin: -70px 0 0 -70px; }
        .hp-mars-glow { width: 220px; height: 220px; margin: -110px 0 0 -110px; }
    }
    @media (max-width: 768px) {
        .hp-nav { padding: 16px 24px; }
        .hp-hero { padding: 120px 24px 100px; min-height: auto; }
        .hp-planet-container { position: relative; width: 280px; height: 280px; margin: 40px auto 0; animation: none; left: auto !important; top: auto !important; }
        .hp-mars { width: 100px; height: 100px; margin: -50px 0 0 -50px; }
        .hp-mars-glow { width: 160px; height: 160px; margin: -80px 0 0 -80px; }
        .hp-orbit-1 { width: 160px; height: 160px; margin: -80px 0 0 -80px; }
        .hp-orbit-2 { width: 220px; height: 220px; margin: -110px 0 0 -110px; }
        .hp-orbit-3 { width: 270px; height: 270px; margin: -135px 0 0 -135px; }
        .hp-features, .hp-steps, .hp-cta { padding: 60px 24px; }
    }
    </style>
</head>
<body class="hp-body">
    <div class="hp-stars">
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
        <div class="hp-star"></div><div class="hp-star"></div><div class="hp-star"></div>
    </div>
    <nav class="hp-nav">
        <a href="/" class="hp-nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Sartozo.AI" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Sartozo.AI" /></a>
        <div class="hp-nav-links">
            <a href="#features" class="hp-nav-link">Features</a>
            <a href="#feed-structure" class="hp-nav-link">Feed Structure</a>
            <a href="#how-it-works" class="hp-nav-link">How it works</a>
        </div>
        <div class="hp-nav-right">
            <button type="button" class="hp-theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/login" class="hp-nav-cta">Get Started</a>
        </div>
    </nav>

    <section class="hp-hero">
        <div class="hp-planet-container">
            <div class="hp-planet">
                <div class="hp-mars-glow"></div>
                <div class="hp-mars">
                    <div class="hp-crater hp-crater-1"></div>
                    <div class="hp-crater hp-crater-2"></div>
                    <div class="hp-crater hp-crater-3"></div>
                </div>
                <div class="hp-orbit hp-orbit-1"><div class="hp-moon"></div></div>
                <div class="hp-orbit hp-orbit-2"><div class="hp-moon"></div></div>
                <div class="hp-orbit hp-orbit-3"><div class="hp-moon"></div></div>
            </div>
        </div>

        <div class="hp-particles">
            <div class="hp-particle"></div>
            <div class="hp-particle"></div>
            <div class="hp-particle"></div>
            <div class="hp-particle"></div>
        </div>

        <div class="hp-badge">Sartozo.AI for E-commerce</div>
        <h1 class="hp-title">Optimize Every Product<br/>for Maximum Visibility</h1>
        <p class="hp-sub">
            AI-powered optimization for your product titles and descriptions. Boost search rankings, increase clicks, and drive more sales.
        </p>
        <div class="hp-buttons">
            <a href="/login" class="hp-btn hp-btn-primary">Get Started</a>
            <a href="#how-it-works" class="hp-btn hp-btn-secondary">Learn More</a>
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
        &copy; 2024 Sartozo.AI &mdash; AI-powered product feed optimization
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
    
    // Planet runs away on hover
    const planetContainer = document.querySelector('.hp-planet-container');
    const mars = document.querySelector('.hp-mars');
    if (mars && planetContainer) {
        mars.addEventListener('mouseenter', () => {
            const runX = (Math.random() - 0.5) * 300;
            const runY = (Math.random() - 0.5) * 200 - 100;
            planetContainer.classList.add('scared');
            planetContainer.style.transform = `translate(${runX}px, ${runY}px)`;
            
            setTimeout(() => {
                planetContainer.style.transform = '';
                setTimeout(() => planetContainer.classList.remove('scared'), 100);
            }, 800);
        });
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
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""


def _build_login_page(next_url: str = "/upload", has_google: bool = True, has_apple: bool = False) -> str:
    """Build login page HTML. Only show providers that are configured."""
    from urllib.parse import quote
    import os
    next_param = f"?next={quote(next_url)}" if next_url else ""
    providers = []
    if has_google:
        providers.append((f'<a href="/auth/google{next_param}" class="auth-btn auth-google">Continue with Google</a>', True))
    if has_apple:
        providers.append((f'<a href="/auth/apple{next_param}" class="auth-btn auth-apple">Continue with Apple</a>', True))
    # Dev bypass when OAuth not configured (for local testing)
    if not providers:
        dev_bypass = os.getenv("AUTH_DEV_BYPASS", "1").lower() in ("1", "true", "yes")
        if dev_bypass:
            providers.append((f'<a href="/auth/dev{next_param}" class="auth-btn auth-google">Continue (dev mode)</a>', True))
        else:
            providers.append(('<p class="auth-no-providers">OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, or AUTH_DEV_BYPASS=1 for local testing.</p>', False))
    providers_html = "\n".join(p[0] for p in providers if p[1]) or providers[0][0]
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Sign in &mdash; Sartozo.AI</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #000; color: #fff; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    .login-box {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 48px 40px; max-width: 400px; width: 100%; text-align: center; }}
    [data-theme="light"] .login-box {{ background: #fff; border-color: rgba(15,23,42,0.1); box-shadow: 0 4px 24px rgba(0,0,0,0.06); }}
    .login-box h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 8px; }}
    .login-box p {{ color: rgba(255,255,255,0.5); font-size: 0.9rem; margin-bottom: 32px; line-height: 1.5; }}
    [data-theme="light"] .login-box p {{ color: rgba(15,23,42,0.6); }}
    .auth-btn {{ display: flex; align-items: center; justify-content: center; gap: 12px; width: 100%; padding: 14px 24px; font-size: 1rem; font-weight: 500; border-radius: 8px; text-decoration: none; transition: all 0.2s; margin-bottom: 12px; border: 1px solid transparent; }}
    .auth-google {{ background: #fff; color: #1f1f1f; }}
    .auth-google:hover {{ background: #f5f5f5; }}
    .auth-apple {{ background: #000; color: #fff; border-color: rgba(255,255,255,0.2); }}
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
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/" class="nav-logo"><img src="/assets/logo-light.png" alt="Sartozo.AI" /></a>
        <button type="button" class="theme-btn" id="themeToggle" aria-label="Toggle theme">&#9728;</button>
    </nav>
    <div class="login-box">
        <h1>Sign in to continue</h1>
        <p>Use your Google or Apple account to access the uploader. No registration required.</p>
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
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Upload feed &mdash; Sartozo.AI</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{opacity:0;transition:opacity .28s ease}body.page-transition-out{opacity:0;pointer-events:none}</style>
    <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #000; color: #fff; min-height: 100vh; }
    [data-theme="light"] body { background: #f8fafc; color: #0f172a; }
    [data-theme="light"] .subtitle, [data-theme="light"] .label, [data-theme="light"] .hint { color: rgba(15,23,42,0.7) !important; }
    [data-theme="light"] .hint code { background: rgba(15,23,42,0.1); }
    [data-theme="light"] .dropzone { border-color: rgba(15,23,42,0.2); }
    [data-theme="light"] .dropzone:hover, [data-theme="light"] .dropzone.dragover { border-color: rgba(15,23,42,0.4); background: rgba(15,23,42,0.02); }
    [data-theme="light"] .dropzone.has-file { border-color: #ea580c; background: rgba(249,115,22,0.06); }
    [data-theme="light"] .dropzone-text { color: rgba(15,23,42,0.6); }
    [data-theme="light"] .dropzone-text strong { color: #0f172a; }
    [data-theme="light"] .dropzone.has-file .dropzone-text { color: #ea580c; }
    [data-theme="light"] .dropzone-icon { color: rgba(15,23,42,0.4); }
    [data-theme="light"] .dropzone.has-file .dropzone-icon { color: #ea580c; }
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
    .nav-links { display: flex; align-items: center; gap: 32px; }
    .nav-link { color: rgba(255,255,255,0.6); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; }
    .nav-link:hover, .nav-link.active { color: #fff; }
    .nav-cta { background: #fff; color: #000; padding: 10px 20px; border-radius: 6px; font-size: 0.85rem; font-weight: 500; text-decoration: none; }

    .container { max-width: 600px; margin: 80px auto; padding: 0 24px; }
    .title { font-size: 2rem; font-weight: 600; margin-bottom: 8px; letter-spacing: -0.02em; }
    .subtitle { color: rgba(255,255,255,0.6); font-size: 1rem; margin-bottom: 40px; line-height: 1.6; }

    .form-group { margin-bottom: 24px; }
    .form-actions-top { margin-bottom: 32px; }
    .label { display: block; font-size: 0.85rem; font-weight: 500; margin-bottom: 8px; color: rgba(255,255,255,0.8); }

    .dropzone { border: 2px dashed rgba(255,255,255,0.2); border-radius: 12px; padding: 48px 24px; text-align: center; cursor: pointer; transition: all 0.3s; }
    .dropzone:hover, .dropzone.dragover { border-color: rgba(255,255,255,0.4); background: rgba(255,255,255,0.02); }
    .dropzone.has-file { border-color: #f97316; border-style: solid; background: rgba(249,115,22,0.04); }
    .dropzone-icon { font-size: 2.5rem; margin-bottom: 12px; opacity: 0.5; transition: all 0.3s; }
    .dropzone.has-file .dropzone-icon { font-size: 2rem; color: #f97316; opacity: 1; animation: pop 0.3s ease-out; }
    .dropzone-text { font-size: 0.95rem; margin-bottom: 4px; color: rgba(255,255,255,0.6); }
    .dropzone-text strong { color: #fff; }
    .dropzone.has-file .dropzone-text { color: #f97316; }
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
    .combo-list { display: none; position: absolute; top: calc(100% + 4px); left: 0; right: 0; max-height: 260px; overflow-y: auto; background: #1a1a2e; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; list-style: none; margin: 0; padding: 4px 0; z-index: 50; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
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
<body>
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Sartozo.AI" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Sartozo.AI" /></a>
        <div class="nav-links">
            <a href="/upload" class="nav-link active">Optimize Feed</a>
            <!-- ADMIN_NAV -->
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/logout" class="nav-link">Log out</a>
        </div>
    </nav>

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
    return _UPLOAD_TEMPLATE.replace("<!-- ADMIN_NAV -->", admin_nav)


@app.get("/", response_class=HTMLResponse)
def homepage():
    return HTMLResponse(content=HOMEPAGE_HTML)


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    redir = require_login_redirect(request, "/upload")
    if redir:
        return redir
    user = get_current_user(request)
    role = user.get("role", "customer") if user else "customer"
    return HTMLResponse(content=_build_upload_page(user_role=role))


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

    records = parse_csv_file(io.StringIO(text))
    if not records:
        raise HTTPException(status_code=400, detail="CSV appears empty or has no rows.")

    if row_limit > 0:
        records = records[:row_limit]

    csv_columns = list(records[0].keys())
    guessed = guess_mapping(csv_columns)
    sample_rows = records[:5]

    upload_id = str(uuid.uuid4())
    _pending_uploads[upload_id] = {
        "records": records,
        "mode": mode,
        "target_language": target_language or "",
        "product_type": product_type,
    }

    user = get_current_user(request)
    role = user.get("role", "customer") if user else "customer"
    return HTMLResponse(content=_build_mapping_page(
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
    pending = _pending_uploads.get(upload_id)
    if not pending:
        raise HTTPException(status_code=400, detail="Upload session expired. Please re-upload your CSV.")

    user = get_current_user(request)
    role = user.get("role", "customer") if user else "customer"
    return HTMLResponse(content=_build_processing_page(upload_id, mode, target_language, mappings_json, optimize_fields, product_type=product_type, user_role=role))


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
    pending = _pending_uploads.pop(upload_id, None)
    if not pending:
        raise HTTPException(status_code=400, detail="Upload session expired.")

    custom_mapping: dict = json.loads(mappings_json)
    records = pending["records"]
    opt_set = set(optimize_fields.split(","))

    batch_id = str(uuid.uuid4())
    normalized_products: List[NormalizedProduct] = normalize_records(records, custom_mapping=custom_mapping)

    actions = decide_actions_for_products(normalized_products, mode=mode)
    storage.create_batch(batch_id=batch_id, products=normalized_products, actions=actions, product_type=product_type)

    if target_language:
        storage.default_target_language = target_language
    elif mode == "translate":
        storage.default_target_language = "en"

    # Pass current prompts to AI provider
    storage._ai.set_prompts(_settings["prompt_title"], _settings["prompt_description"])

    storage.process_batch_synchronously(batch_id, optimize_fields=opt_set)

    return {"batch_id": batch_id}


def _build_processing_page(upload_id: str, mode: str, target_language: str, mappings_json: str, optimize_fields: str = "title,description", product_type: str = "standard", user_role: str = "customer") -> str:
    mappings_escaped = mappings_json.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Processing &mdash; Sartozo.AI</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #000; color: #fff; min-height: 100vh; display: flex; flex-direction: column; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    [data-theme="light"] .thinking-sub, [data-theme="light"] .progress-pct {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .spinner {{ border-color: rgba(15,23,42,0.1); border-top-color: #f97316; }}
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
    .spinner {{ width: 64px; height: 64px; border: 3px solid rgba(255,255,255,0.1); border-top-color: #f97316; border-radius: 50%; animation: spin 1s cubic-bezier(0.4,0,0.2,1) infinite; }}
    .checkmark {{ display: none; width: 64px; height: 64px; border-radius: 50%; background: #f97316; color: #000; font-size: 32px; line-height: 64px; text-align: center; animation: popIn 0.35s cubic-bezier(0.2,0.8,0.2,1.2); }}
    .done .spinner {{ display: none; }}
    .done .checkmark {{ display: block; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @keyframes popIn {{ 0% {{ transform: scale(0); }} 100% {{ transform: scale(1); }} }}

    .thinking {{ font-size: 1.25rem; font-weight: 600; min-height: 1.6em; transition: opacity 0.35s ease; }}
    .thinking-sub {{ font-size: 0.9rem; color: rgba(255,255,255,0.5); margin-top: 8px; }}
    .dots::after {{ content: ''; animation: dots 1.5s steps(4, end) infinite; }}
    @keyframes dots {{ 0%{{content:'';}} 25%{{content:'.';}} 50%{{content:'..';}} 75%{{content:'...';}} }}

    .progress {{ width: 100%; height: 6px; background: rgba(255,255,255,0.1); border-radius: 999px; margin-top: 32px; overflow: hidden; }}
    .progress-fill {{ height: 100%; width: 0%; background: linear-gradient(90deg, #ea580c, #f97316); border-radius: 999px; transition: width 0.12s linear; }}
    .progress-pct {{ font-size: 0.8rem; color: rgba(255,255,255,0.4); margin-top: 10px; font-variant-numeric: tabular-nums; }}

    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} }}
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Sartozo.AI" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Sartozo.AI" /></a>
        <div class="nav-links">
            <a href="/upload" class="nav-link">Optimize Feed</a>
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
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Map columns &mdash; Sartozo.AI</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #000; color: #fff; min-height: 100vh; }}
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
    .nav {{ display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
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
    .nav-link:hover, .nav-link.active {{ color: #fff; }}
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
    .checkbox-label input {{ width: 18px; height: 18px; accent-color: #f97316; }}

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
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Sartozo.AI" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Sartozo.AI" /></a>
        <div class="nav-links">
            <a href="/upload" class="nav-link active">Optimize Feed</a>
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
        records = parse_csv_file(io.StringIO(content.decode("utf-8")))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")

    batch_id = str(uuid.uuid4())
    normalized_products: List[NormalizedProduct] = normalize_records(records)

    actions = decide_actions_for_products(normalized_products, mode=mode)
    storage.create_batch(batch_id=batch_id, products=normalized_products, actions=actions)

    if target_language:
        storage.default_target_language = target_language
    storage.process_batch_synchronously(batch_id)

    if redirect:
        return RedirectResponse(url=f"/batches/{batch_id}/review", status_code=303)

    return storage.get_batch_summary(batch_id)


@app.get("/batches/{batch_id}", response_model=BatchSummary)
def get_batch(request: Request, batch_id: str):
    require_login_http(request)
    summary = storage.get_batch_summary(batch_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return summary


@app.get("/batches/{batch_id}/export")
async def export_batch(request: Request, batch_id: str):
    require_login_http(request)
    batch = storage.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

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
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

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
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    product_id = data.get("product_id")
    field = data.get("field")
    value = data.get("value", "")

    allowed_fields = {"optimized_title", "optimized_description", "translated_title", "translated_description"}
    if field not in allowed_fields:
        raise HTTPException(status_code=400, detail=f"Field '{field}' is not editable.")

    for result in batch.products:
        if result.product.id == product_id:
            setattr(result, field, value)
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
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    # Filter to only selected products
    from .models import Batch as BatchModel
    selected_products = [r for r in batch.products if r.product.id in product_ids]
    
    if not selected_products:
        raise HTTPException(status_code=400, detail="No products selected.")

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


@app.get("/batches/{batch_id}/review", response_class=HTMLResponse)
async def review_batch(request: Request, batch_id: str):
    redir = require_login_redirect(request, f"/batches/{batch_id}/review")
    if redir:
        return redir
    batch = storage.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    user = get_current_user(request)
    user_role = user.get("role", "customer") if user else "customer"

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
    
    rows_html = ""
    for r in batch.products:
        pill_cls = f"pill-{r.status.value}"
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

        rows_html += f"""
        <tr data-id="{r.product.id}" data-status="{r.status.value}" data-gmc="{gmc_status}">
            <td><input type="checkbox" name="product_id" value="{r.product.id}" /></td>
            <td class="img-cell">{image_cell}</td>
            <td class="link-cell">{link_cell}</td>
            {old_title_cell}
            {new_title_cell}
            {old_desc_cell}
            {new_desc_cell}
            <td class="editable-cell" contenteditable="true" data-field="translated_title" data-product="{r.product.id}">{trans_title}</td>
            {trans_desc_cell}
            <td><span class="pill {pill_cls}">{r.status.value}</span></td>
            <td class="note">{r.notes or r.error or ''}</td>
            <td class="score-cell col-sticky col-score">{score_cell}</td>
            <td class="col-sticky col-action"><span class="badge {action_cls}">{action_display}</span></td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Review &mdash; {batch_id[:8]}</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0a; color: #fff; min-height: 100vh; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    [data-theme="light"] .nav {{ border-bottom-color: rgba(15,23,42,0.08); background: rgba(248,250,252,0.95); }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover {{ color: #0f172a; }}
    [data-theme="light"] .header .batch-id {{ color: rgba(15,23,42,0.5); }}
    [data-theme="light"] .btn-outline {{ border-color: rgba(15,23,42,0.2); color: #0f172a; }}
    [data-theme="light"] .btn-outline:hover {{ border-color: rgba(15,23,42,0.4); }}
    [data-theme="light"] .btn-primary {{ background: #0f172a; color: #fff; }}
    [data-theme="light"] .btn-primary:hover {{ background: #1e293b; }}
    [data-theme="light"] .insight {{ background: rgba(255,255,255,0.8); border-color: rgba(15,23,42,0.12); }}
    [data-theme="light"] .insight-icon {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .insight-title, [data-theme="light"] .insight-text strong {{ color: #0f172a; }}
    [data-theme="light"] .insight-text {{ color: rgba(15,23,42,0.8); }}
    [data-theme="light"] .stat {{ background: rgba(255,255,255,0.8); border-color: rgba(15,23,42,0.08); }}
    [data-theme="light"] .stat-value {{ color: #0f172a; }}
    [data-theme="light"] .stat-label {{ color: rgba(15,23,42,0.5); }}
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
    .btn:focus-visible, .expand-btn:focus-visible {{ outline: 2px solid #fff; outline-offset: 2px; }}

    .insight {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px 24px; margin-bottom: 24px; display: flex; gap: 16px; }}
    .insight-icon {{ font-size: 1.5rem; color: rgba(255,255,255,0.6); }}
    .insight-title {{ font-weight: 600; margin-bottom: 6px; color: #fff; }}
    .insight-text {{ font-size: 0.9rem; color: rgba(255,255,255,0.7); line-height: 1.6; }}
    .insight-text strong {{ color: #fff; }}

    .stats {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 16px; margin-bottom: 24px; }}
    @media (max-width: 900px) {{ .stats {{ grid-template-columns: repeat(3, 1fr); }} }}
    .stat {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 16px 20px; text-align: center; }}
    .stat-value {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }}
    .stat-label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: rgba(255,255,255,0.5); }}
    .stat-done {{ color: #fff; }}
    .stat-review {{ color: #e5e5e5; }}
    .stat-failed {{ color: #ef4444; }}
    .stat-score {{ color: #e5e5e5; }}
    [data-theme="light"] .stat-done {{ color: #0f172a; }}
    [data-theme="light"] .stat-review {{ color: #334155; }}
    [data-theme="light"] .stat-score {{ color: #334155; }}
    [data-theme="light"] .stat-failed {{ color: #dc2626; }}

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
    .feedback-box .btn {{ width: 100%; padding: 14px; font-size: 0.95rem; font-weight: 600; border-radius: 8px; cursor: pointer; border: none; background: #f97316; color: #fff; }}
    .feedback-box .btn:hover {{ background: #ea580c; }}
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
    td:nth-child(4), td:nth-child(5), td:nth-child(6), td:nth-child(7), td:nth-child(8), td:nth-child(9) {{ max-width: 220px; }}
    td:nth-child(4), td:nth-child(5), td:nth-child(8) {{ overflow: hidden; text-overflow: ellipsis; }}
    .desc-cell {{ overflow: visible; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:nth-child(even) {{ background: rgba(255,255,255,0.015); }}
    tr:hover {{ background: rgba(255,255,255,0.04); }}
    .mono {{ font-family: 'SF Mono', Monaco, monospace; font-size: 0.75rem; color: rgba(255,255,255,0.5); }}
    .note {{ font-size: 0.78rem; color: rgba(255,255,255,0.4); max-width: 150px; }}
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

    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} .container {{ padding: 24px; }} .gmc-panel {{ flex-direction: column; align-items: stretch; }} .gmc-legend {{ flex-wrap: wrap; gap: 8px; }} }}
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Sartozo.AI" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Sartozo.AI" /></a>
        <div class="nav-links">
            <a href="/upload" class="nav-link">Optimize Feed</a>
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
                <button onclick="downloadSelected()" class="btn btn-primary">&#8681; Download selected</button>
                <a href="/batches/{batch_id}/export" class="btn btn-outline">&#8681; Download all</a>
            </div>
        </div>

        <div class="insight">
            <div class="insight-icon">&#9889;</div>
            <div class="insight-body">
                <p class="insight-title">Optimization summary</p>
                <p class="insight-text">
                    <strong>{done}</strong> of <strong>{total}</strong> products optimized
                    with an average quality score of <strong>{avg_score}/100</strong>.
                    {"Titles and descriptions were expanded with relevant keywords, product type identifiers, and secondary search phrases with separators — a proven approach for improving visibility in search engines and marketplaces." if avg_score >= 50 else "Some products had limited metadata, which constrained optimization potential. Adding more attributes (category, material, color) will significantly improve results."}
                    Well-structured titles with descriptive keywords and category terms are indexed more effectively by search engines,
                    leading to higher rankings, better click-through rates, and stronger organic visibility — directly impacting your ROI.
                </p>
            </div>
        </div>

        <div class="stats">
            <div class="stat"><div class="stat-value">{total}</div><div class="stat-label">Total</div></div>
            <div class="stat"><div class="stat-value stat-done">{done}</div><div class="stat-label">Done</div></div>
            <div class="stat"><div class="stat-value stat-review">{review}</div><div class="stat-label">Needs review</div></div>
            <div class="stat"><div class="stat-value stat-failed">{failed}</div><div class="stat-label">Failed</div></div>
            <div class="stat"><div class="stat-value">{skipped}</div><div class="stat-label">Skipped</div></div>
            <div class="stat"><div class="stat-value stat-score">{avg_score}</div><div class="stat-label">Avg score</div></div>
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
                                <th style="width:60px;" class="th-center">Image</th>
                                <th style="width:50px;" class="th-center">Link</th>
                                <th onclick="sortTable(3)">Old title</th>
                                <th onclick="sortTable(4)">New title</th>
                                <th onclick="sortTable(5)">Old description</th>
                                <th onclick="sortTable(6)">New description</th>
                                <th onclick="sortTable(7)">Translated title</th>
                                <th onclick="sortTable(8)">Translated desc</th>
                                <th onclick="sortTable(9)">Status</th>
                                <th onclick="sortTable(10)">Notes</th>
                                <th onclick="sortTable(11)" class="th-center col-sticky col-score">Score</th>
                                <th onclick="sortTable(12)" class="th-center col-sticky col-action">Action</th>
                            </tr>
                        </thead>
                        <tbody>{rows_html}</tbody>
                    </table>
                </form>
            </div>
            <div class="scroll-hint" id="scrollHint">&#8596; Scroll horizontally to see all columns</div>
        </div>
    </div>

    <script>
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
    const numericCols=new Set([11]);
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
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


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
    _feedback_store.append({
        "rating": int(rating),
        "text": safe_text,
        "batch_id": batch_id,
        "email": user.get("email", "") if user else "",
        "name": user.get("name", "") if user else "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_feedback()
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Settings page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    redir = require_admin_redirect(request, "/settings")
    if redir:
        return redir
    api_key_masked = ""
    if _settings["openai_api_key"]:
        key = _settings["openai_api_key"]
        api_key_masked = key[:7] + "..." + key[-4:] if len(key) > 15 else "••••••••"

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Settings &mdash; Sartozo.AI</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #000; color: #fff; min-height: 100vh; }}
    [data-theme="light"] body {{ background: #f8fafc; color: #0f172a; }}
    [data-theme="light"] .nav {{ border-bottom-color: rgba(15,23,42,0.08); }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover, [data-theme="light"] .nav-link.active {{ color: #0f172a; }}
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
    .nav {{ display: flex; align-items: center; justify-content: space-between; padding: 16px 48px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
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
    .nav-link.active {{ color: #fff; }}

    .container {{ max-width: 700px; margin: 48px auto; padding: 0 24px; }}
    .title {{ font-size: 1.75rem; font-weight: 600; margin-bottom: 32px; letter-spacing: -0.02em; }}

    .tabs {{ display: flex; gap: 8px; margin-bottom: 32px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 0; }}
    .tab {{ padding: 12px 20px; font-size: 0.9rem; font-weight: 500; color: rgba(255,255,255,0.5); background: none; border: none; cursor: pointer; position: relative; transition: color 0.2s; }}
    .tab:hover {{ color: rgba(255,255,255,0.8); }}
    .tab.active {{ color: #fff; }}
    .tab.active::after {{ content: ''; position: absolute; bottom: -1px; left: 0; right: 0; height: 2px; background: #fff; }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}

    .group {{ margin-bottom: 28px; }}
    .group-title {{ font-weight: 600; font-size: 1rem; margin-bottom: 8px; }}
    .group-desc {{ font-size: 0.85rem; color: rgba(255,255,255,0.5); margin-bottom: 14px; line-height: 1.5; }}
    .group-desc a {{ color: #f97316; }}
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

    .save-msg {{ display: inline-flex; align-items: center; gap: 6px; margin-left: 14px; font-size: 0.85rem; color: #f97316; opacity: 0; transition: opacity 0.3s; }}
    .save-msg.show {{ opacity: 1; }}

    .note-box {{ margin-top: 28px; padding: 16px 20px; border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); }}
    .note-box p {{ font-size: 0.85rem; color: rgba(255,255,255,0.6); margin: 0; line-height: 1.5; }}
    .note-box strong {{ color: rgba(255,255,255,0.8); }}

    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} .container {{ margin: 32px auto; }} }}
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Sartozo.AI" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Sartozo.AI" /></a>
        <div class="nav-links">
            <a href="/upload" class="nav-link">Optimize Feed</a>
            {_admin_nav_links(active="settings", user_role="admin")}
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
        </div>
    </nav>

    <div class="container">
        <h1 class="title">Settings</h1>

        <div class="tabs">
            <button class="tab active" data-tab="tab-prompts" onclick="switchTab('tab-prompts')">Prompts</button>
            <button class="tab" data-tab="tab-api" onclick="switchTab('tab-api')">API Keys</button>
        </div>

        <div id="tab-prompts" class="tab-content active">
            <div class="group">
                <div class="group-title">Title Optimization Prompt</div>
                <p class="group-desc">
                    This prompt is sent to the AI when optimizing product titles.
                    Variables: <code>{{{{title}}}}</code>, <code>{{{{category}}}}</code>, <code>{{{{brand}}}}</code>, <code>{{{{attributes}}}}</code>
                </p>
                <textarea id="prompt_title">{_settings["prompt_title"]}</textarea>
            </div>

            <div class="group">
                <div class="group-title">Description Generation Prompt</div>
                <p class="group-desc">
                    This prompt is sent to the AI when generating product descriptions.
                    Variables: <code>{{{{title}}}}</code>, <code>{{{{category}}}}</code>, <code>{{{{brand}}}}</code>, <code>{{{{attributes}}}}</code>, <code>{{{{description}}}}</code>
                </p>
                <textarea id="prompt_description">{_settings["prompt_description"]}</textarea>
            </div>

            <div style="display:flex;align-items:center;">
                <button class="btn btn-primary" onclick="savePrompts()">Save prompts</button>
                <span id="prompts-status" class="save-msg">&#10003; Saved</span>
            </div>
        </div>

        <div id="tab-api" class="tab-content">
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
        </div>
    </div>

    <script>
    function switchTab(tabId){{
        document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
        document.querySelector('[data-tab="'+tabId+'"]').classList.add('active');
        document.getElementById(tabId).classList.add('active');
    }}
    async function savePrompts(){{
        const resp=await fetch('/api/settings/prompts',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{prompt_title:document.getElementById('prompt_title').value,prompt_description:document.getElementById('prompt_description').value}})}});
        if(resp.ok)showSaved('prompts-status');
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
    (function(){{
        const t=document.getElementById("themeToggle");
        if(t){{const k="hp-theme";function g(){{return localStorage.getItem(k)||"dark";}}function s(v){{document.documentElement.setAttribute("data-theme",v);localStorage.setItem(k,v);t.textContent=v==="dark"?"\u2600":"\u263E";}}t.onclick=()=>s(g()==="dark"?"light":"dark");s(g());}}
    }})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/api/settings/prompts")
async def save_prompts(request: Request, data: dict):
    require_admin_http(request)
    if "prompt_title" in data:
        _settings["prompt_title"] = data["prompt_title"]
    if "prompt_description" in data:
        _settings["prompt_description"] = data["prompt_description"]
    storage._ai.set_prompts(_settings["prompt_title"], _settings["prompt_description"])
    return {"status": "ok"}


@app.post("/api/settings/apikey")
async def save_api_key(request: Request, data: dict):
    require_admin_http(request)
    if "openai_api_key" in data:
        _settings["openai_api_key"] = data["openai_api_key"]
        storage._ai.set_api_key(data["openai_api_key"])
        storage._ai.set_prompts(_settings["prompt_title"], _settings["prompt_description"])
    return {"status": "ok"}


@app.get("/api/settings")
async def get_settings(request: Request):
    require_admin_http(request)
    return {
        "prompt_title": _settings["prompt_title"],
        "prompt_description": _settings["prompt_description"],
        "has_api_key": bool(_settings["openai_api_key"]),
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
    return {"feedback": list(reversed(_feedback_store))}


@app.get("/api/admin/users")
async def api_admin_users(request: Request):
    require_admin_http(request)
    return {"users": list(_users_db.values()), "total": len(_users_db)}


# ─────────────────────────────────────────────────────────────────────────────
# Admin: Feedback page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/admin/feedback", response_class=HTMLResponse)
async def admin_feedback_page(request: Request):
    redir = require_admin_redirect(request, "/admin/feedback")
    if redir:
        return redir

    rows_html = ""
    for i, fb in enumerate(reversed(_feedback_store)):
        stars = "&#9733;" * fb.get("rating", 0) + "&#9734;" * (5 - fb.get("rating", 0))
        ts = fb.get("timestamp", "")[:19].replace("T", " ") if fb.get("timestamp") else "—"
        import html as _html
        text = _html.escape(fb.get("text", ""))[:200]
        email = _html.escape(fb.get("email", "—"))
        name = _html.escape(fb.get("name", ""))
        batch = _html.escape(fb.get("batch_id", ""))
        rows_html += f"""<tr>
            <td>{i + 1}</td>
            <td class="stars">{stars}</td>
            <td class="text-cell">{text}</td>
            <td>{name}<br><span class="email">{email}</span></td>
            <td class="mono">{batch}</td>
            <td class="ts">{ts}</td>
        </tr>"""

    total = len(_feedback_store)
    avg = round(sum(f.get("rating", 0) for f in _feedback_store) / total, 1) if total else 0

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Feedback &mdash; Sartozo.AI Admin</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #000; color: #fff; min-height: 100vh; }}
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
    .nav-link:hover {{ color: #fff; }}
    .nav-link.active {{ color: #fff; }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover, [data-theme="light"] .nav-link.active {{ color: #0f172a; }}
    .theme-btn {{ display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: rgba(255,255,255,0.6); cursor: pointer; font-size: 1rem; transition: all 0.2s; }}
    .theme-btn:hover {{ color: #fff; background: rgba(255,255,255,0.08); }}
    [data-theme="light"] .theme-btn {{ border-color: rgba(15,23,42,0.15); color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .theme-btn:hover {{ color: #0f172a; background: rgba(15,23,42,0.06); }}

    .container {{ max-width: 1100px; margin: 48px auto; padding: 0 24px; }}
    .page-title {{ font-size: 1.75rem; font-weight: 600; margin-bottom: 8px; letter-spacing: -0.02em; }}
    .page-sub {{ color: rgba(255,255,255,0.5); font-size: 0.95rem; margin-bottom: 32px; }}
    [data-theme="light"] .page-sub {{ color: rgba(15,23,42,0.5); }}

    .stats {{ display: flex; gap: 24px; margin-bottom: 32px; }}
    .stat {{ padding: 20px 28px; border-radius: 12px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); flex: 1; }}
    [data-theme="light"] .stat {{ background: rgba(255,255,255,0.8); border-color: rgba(15,23,42,0.08); }}
    .stat-val {{ font-size: 1.75rem; font-weight: 700; }}
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
    .empty {{ text-align: center; padding: 60px 24px; color: rgba(255,255,255,0.3); font-size: 1rem; }}
    [data-theme="light"] .empty {{ color: rgba(15,23,42,0.3); }}

    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} .container {{ margin: 32px auto; }} .stats {{ flex-direction: column; gap: 12px; }} }}
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Sartozo.AI" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Sartozo.AI" /></a>
        <div class="nav-links">
            <a href="/upload" class="nav-link">Optimize Feed</a>
            {_admin_nav_links(active="feedback", user_role="admin")}
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/logout" class="nav-link">Log out</a>
        </div>
    </nav>

    <div class="container">
        <h1 class="page-title">Customer Feedback</h1>
        <p class="page-sub">{total} feedback entries collected</p>

        <div class="stats">
            <div class="stat"><div class="stat-val">{total}</div><div class="stat-label">Total responses</div></div>
            <div class="stat"><div class="stat-val">{avg}</div><div class="stat-label">Average rating</div></div>
            <div class="stat"><div class="stat-val">{"&#9733;" * round(avg) + "&#9734;" * (5 - round(avg)) if total else "—"}</div><div class="stat-label">Stars</div></div>
        </div>

        {"<table><thead><tr><th>#</th><th>Rating</th><th>Feedback</th><th>User</th><th>Batch</th><th>Date</th></tr></thead><tbody>" + rows_html + "</tbody></table>" if total else '<div class="empty">No feedback yet. Feedback will appear here as customers submit it.</div>'}
    </div>

    <script>
    (function(){{
        const t=document.getElementById("themeToggle");
        if(t){{const k="hp-theme";function g(){{return localStorage.getItem(k)||"dark";}}function s(v){{document.documentElement.setAttribute("data-theme",v);localStorage.setItem(k,v);t.textContent=v==="dark"?"\\u2600":"\\u263E";}}t.onclick=()=>s(g()==="dark"?"light":"dark");s(g());}}
    }})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─────────────────────────────────────────────────────────────────────────────
# Admin: Users page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    redir = require_admin_redirect(request, "/admin/users")
    if redir:
        return redir

    import html as _html
    users_list = sorted(_users_db.values(), key=lambda u: u.get("last_login", ""), reverse=True)
    rows_html = ""
    for i, u in enumerate(users_list):
        name = _html.escape(u.get("name", "—"))
        email = _html.escape(u.get("email", ""))
        provider = _html.escape(u.get("provider", ""))
        role = u.get("role", "customer")
        role_badge = '<span class="badge badge-admin">admin</span>' if role == "admin" else '<span class="badge badge-customer">customer</span>'
        last_login = u.get("last_login", "")[:19].replace("T", " ") if u.get("last_login") else "—"
        first_seen = u.get("first_seen", "")[:19].replace("T", " ") if u.get("first_seen") else "—"
        rows_html += f"""<tr>
            <td>{i + 1}</td>
            <td><strong>{name}</strong><br><span class="email">{email}</span></td>
            <td>{provider}</td>
            <td>{role_badge}</td>
            <td class="ts">{first_seen}</td>
            <td class="ts">{last_login}</td>
        </tr>"""

    total = len(users_list)
    admins = sum(1 for u in users_list if u.get("role") == "admin")
    customers = total - admins

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Users &mdash; Sartozo.AI Admin</title>
    <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
    <style>body{{opacity:0;transition:opacity .28s ease}}body.page-transition-out{{opacity:0;pointer-events:none}}</style>
    <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #000; color: #fff; min-height: 100vh; }}
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
    .nav-link:hover {{ color: #fff; }}
    .nav-link.active {{ color: #fff; }}
    [data-theme="light"] .nav-link {{ color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .nav-link:hover, [data-theme="light"] .nav-link.active {{ color: #0f172a; }}
    .theme-btn {{ display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.2); background: transparent; color: rgba(255,255,255,0.6); cursor: pointer; font-size: 1rem; transition: all 0.2s; }}
    .theme-btn:hover {{ color: #fff; background: rgba(255,255,255,0.08); }}
    [data-theme="light"] .theme-btn {{ border-color: rgba(15,23,42,0.15); color: rgba(15,23,42,0.6); }}
    [data-theme="light"] .theme-btn:hover {{ color: #0f172a; background: rgba(15,23,42,0.06); }}

    .container {{ max-width: 1000px; margin: 48px auto; padding: 0 24px; }}
    .page-title {{ font-size: 1.75rem; font-weight: 600; margin-bottom: 8px; letter-spacing: -0.02em; }}
    .page-sub {{ color: rgba(255,255,255,0.5); font-size: 0.95rem; margin-bottom: 32px; }}
    [data-theme="light"] .page-sub {{ color: rgba(15,23,42,0.5); }}

    .stats {{ display: flex; gap: 24px; margin-bottom: 32px; }}
    .stat {{ padding: 20px 28px; border-radius: 12px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); flex: 1; }}
    [data-theme="light"] .stat {{ background: rgba(255,255,255,0.8); border-color: rgba(15,23,42,0.08); }}
    .stat-val {{ font-size: 1.75rem; font-weight: 700; }}
    .stat-label {{ font-size: 0.8rem; color: rgba(255,255,255,0.4); margin-top: 4px; }}
    [data-theme="light"] .stat-label {{ color: rgba(15,23,42,0.5); }}

    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{ text-align: left; padding: 12px 16px; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: rgba(255,255,255,0.4); border-bottom: 1px solid rgba(255,255,255,0.1); }}
    [data-theme="light"] th {{ color: rgba(15,23,42,0.5); border-bottom-color: rgba(15,23,42,0.1); }}
    td {{ padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: top; }}
    [data-theme="light"] td {{ border-bottom-color: rgba(15,23,42,0.06); }}
    tr:hover td {{ background: rgba(255,255,255,0.02); }}
    [data-theme="light"] tr:hover td {{ background: rgba(15,23,42,0.02); }}
    .email {{ font-size: 0.78rem; color: rgba(255,255,255,0.4); }}
    [data-theme="light"] .email {{ color: rgba(15,23,42,0.4); }}
    .ts {{ font-size: 0.78rem; white-space: nowrap; color: rgba(255,255,255,0.5); }}
    [data-theme="light"] .ts {{ color: rgba(15,23,42,0.5); }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }}
    .badge-admin {{ background: rgba(249,115,22,0.15); color: #f97316; }}
    .badge-customer {{ background: rgba(99,102,241,0.15); color: #818cf8; }}
    [data-theme="light"] .badge-admin {{ background: rgba(249,115,22,0.1); }}
    [data-theme="light"] .badge-customer {{ background: rgba(99,102,241,0.1); }}
    .empty {{ text-align: center; padding: 60px 24px; color: rgba(255,255,255,0.3); font-size: 1rem; }}
    [data-theme="light"] .empty {{ color: rgba(15,23,42,0.3); }}

    @media (max-width: 768px) {{ .nav {{ padding: 16px 24px; }} .container {{ margin: 32px auto; }} .stats {{ flex-direction: column; gap: 12px; }} }}
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/" class="nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Sartozo.AI" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Sartozo.AI" /></a>
        <div class="nav-links">
            <a href="/upload" class="nav-link">Optimize Feed</a>
            {_admin_nav_links(active="users", user_role="admin")}
            <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/logout" class="nav-link">Log out</a>
        </div>
    </nav>

    <div class="container">
        <h1 class="page-title">Authenticated Users</h1>
        <p class="page-sub">{total} users have signed in</p>

        <div class="stats">
            <div class="stat"><div class="stat-val">{total}</div><div class="stat-label">Total users</div></div>
            <div class="stat"><div class="stat-val">{admins}</div><div class="stat-label">Admins</div></div>
            <div class="stat"><div class="stat-val">{customers}</div><div class="stat-label">Customers</div></div>
        </div>

        {"<table><thead><tr><th>#</th><th>User</th><th>Provider</th><th>Role</th><th>First seen</th><th>Last login</th></tr></thead><tbody>" + rows_html + "</tbody></table>" if total else '<div class="empty">No users have signed in yet.</div>'}
    </div>

    <script>
    (function(){{
        const t=document.getElementById("themeToggle");
        if(t){{const k="hp-theme";function g(){{return localStorage.getItem(k)||"dark";}}function s(v){{document.documentElement.setAttribute("data-theme",v);localStorage.setItem(k,v);t.textContent=v==="dark"?"\\u2600":"\\u263E";}}t.onclick=()=>s(g()==="dark"?"light":"dark");s(g());}}
    }})();
    </script>
    <script src="/static/page-transition.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)

