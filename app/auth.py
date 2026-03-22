"""
OAuth authentication (Google + Apple Sign-In).
No registration — users sign in with existing accounts only.
Role-based access: admin vs customer.

Google sign-in and Merchant Center use the same OAuth 2.0 Web Client created in
Google Cloud Console. Set GOOGLE_CLOUD_PROJECT_ID to that project’s ID; see app/google_cloud.py.
"""
from typing import Optional
from urllib.parse import quote
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

from .google_cloud import get_normalized_google_oauth_credentials

ADMIN_EMAILS = {"oleh.halahan@zanzarra.com"}

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
    """Return 'admin' if email is in ADMIN_EMAILS, otherwise 'customer'."""
    return "admin" if email.lower().strip() in ADMIN_EMAILS else "customer"


def is_admin(request: Request) -> bool:
    user = request.session.get("user")
    if not user:
        return False
    return user.get("role") == "admin"


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
