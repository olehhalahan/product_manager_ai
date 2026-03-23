"""
OAuth authentication (Google + Apple Sign-In).
No registration — users sign in with existing accounts only.
Role-based access: admin vs customer.

Google sign-in and Merchant Center use the same OAuth 2.0 Web Client created in
Google Cloud Console. Set GOOGLE_CLOUD_PROJECT_ID to that project’s ID; see app/google_cloud.py.
"""
import os
from typing import Optional
from urllib.parse import quote
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

from .google_cloud import get_normalized_google_oauth_credentials

# Base admin(s); extend with env ADMIN_EMAILS="a@x.com,b@y.com" (comma-separated, case-insensitive).
_ADMIN_EMAILS_BASE = frozenset({"oleh.halahan@zanzarra.com"})


def _admin_email_set() -> set:
    """Emails that receive admin role (session email must match)."""
    s = set(_ADMIN_EMAILS_BASE)
    extra = os.getenv("ADMIN_EMAILS", "") or ""
    for part in extra.split(","):
        e = part.strip().lower()
        if e:
            s.add(e)
    return s


def _local_admin_enabled(request: Request) -> bool:
    """
    When AUTH_LOCAL_ADMIN=1 and the request host is loopback only, treat any logged-in user as admin.
    For local development when Google OAuth returns an email not listed in ADMIN_EMAILS.
    """
    if os.getenv("AUTH_LOCAL_ADMIN", "").lower() not in ("1", "true", "yes"):
        return False
    host = (request.url.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")

_oauth = None
# Rebuild OAuth clients if env changes (avoids stale client_id after .env edit + hot reload edge cases)
_google_oauth_fingerprint: Optional[str] = None


def _google_credentials_fingerprint() -> str:
    gid, gsec = get_normalized_google_oauth_credentials()
    return f"{gid}\n{gsec}" if gid and gsec else ""


def get_oauth():
    global _oauth, _google_oauth_fingerprint
    import os

    fp = _google_credentials_fingerprint()
    if _oauth is not None and _google_oauth_fingerprint != fp:
        _oauth = None

    if _oauth is None:
        from authlib.integrations.starlette_client import OAuth
        oauth = OAuth()
        # Google (normalized: strip + quotes — see google_cloud.py)
        gid, gsec = get_normalized_google_oauth_credentials()
        if gid and gsec:
            oauth.register(
                name="google",
                client_id=gid,
                client_secret=gsec,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs={"scope": "openid email profile"},
            )
            # Same OAuth client; separate redirect URI for Merchant Center (Merchant API) + refresh token
            oauth.register(
                name="google_merchant",
                client_id=gid,
                client_secret=gsec,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs={"scope": "https://www.googleapis.com/auth/content"},
            )
        # Apple Sign-In (optional — requires Apple Developer setup)
        aid = os.getenv("APPLE_CLIENT_ID")
        akey = os.getenv("APPLE_KEY_ID")
        ateam = os.getenv("APPLE_TEAM_ID")
        akey_pem = os.getenv("APPLE_PRIVATE_KEY")
        if aid and akey and ateam and akey_pem:
            try:
                import jwt
                import time
                key_content = akey_pem
                if "-----BEGIN" in akey_pem:
                    key_content = akey_pem.replace("\\n", "\n")
                else:
                    try:
                        with open(akey_pem) as f:
                            key_content = f.read()
                    except OSError:
                        pass
                secret = jwt.encode(
                    {
                        "iss": ateam,
                        "iat": int(time.time()),
                        "exp": int(time.time()) + 86400 * 180,
                        "aud": "https://appleid.apple.com",
                        "sub": aid,
                    },
                    key_content,
                    algorithm="ES256",
                    headers={"kid": akey},
                )
                oauth.register(
                    name="apple",
                    client_id=aid,
                    client_secret=secret,
                    server_metadata_url="https://appleid.apple.com/.well-known/openid-configuration",
                    client_kwargs={"scope": "openid email name"},
                )
            except Exception:
                pass  # Skip Apple if config invalid
        _google_oauth_fingerprint = fp
        _oauth = oauth
    return _oauth


def get_session_secret() -> str:
    import os
    return os.getenv("SESSION_SECRET", "change-me-in-production")


def get_current_user(request: Request) -> Optional[dict]:
    """Return user dict if logged in, else None."""
    return request.session.get("user")


def get_user_role(email: str) -> str:
    """Return 'admin' if email is in the admin list (env + defaults), otherwise 'customer'."""
    em = (email or "").lower().strip()
    return "admin" if em in _admin_email_set() else "customer"


def is_admin(request: Request) -> bool:
    user = request.session.get("user")
    if not user:
        return False
    if _local_admin_enabled(request):
        return True
    # Re-check from email so ADMIN_EMAILS env applies without forcing re-login.
    return get_user_role(user.get("email") or "") == "admin"


def require_login_redirect(request: Request, next_url: str = "/upload") -> Optional[RedirectResponse]:
    """If not logged in, return redirect to login. Else None."""
    if not request.session.get("user"):
        return RedirectResponse(url=f"/login?next={quote(next_url, safe='')}", status_code=302)
    return None


def require_login_http(request: Request) -> None:
    """Raise 401 if not logged in (for API endpoints)."""
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Login required")


def require_admin_redirect(request: Request, next_url: str = "/upload") -> Optional[RedirectResponse]:
    """If not logged in redirect to login; if not admin redirect to upload."""
    if not request.session.get("user"):
        return RedirectResponse(url=f"/login?next={quote(next_url, safe='')}", status_code=302)
    if not is_admin(request):
        return RedirectResponse(url="/upload", status_code=302)
    return None


def require_admin_http(request: Request) -> None:
    """Raise 401/403 if not logged in or not admin."""
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Login required")
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")
