"""
Security helpers: production detection, HTTP headers, rate limiting, SSRF checks,
HTML sanitization, and startup validation.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import secrets
import socket
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict, Optional, Tuple
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("uvicorn.error")

CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE = "XSRF-TOKEN"
CSRF_FORM_FIELD = "csrf_token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/payments/wayforpay/service",
        "/api/cron/writter-auto-daily",
    }
)

_DEFAULT_SESSION_SECRET = "change-me-in-production"
_WEAK_SESSION_SECRETS = frozenset(
    {
        _DEFAULT_SESSION_SECRET,
        "your-random-secret-at-least-32-chars",
        "secret",
        "changeme",
    }
)

# Blog/CMS HTML allowlist (bleach).
_BLOG_ALLOWED_TAGS = frozenset(
    {
        "a",
        "article",
        "blockquote",
        "br",
        "code",
        "div",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_BLOG_ALLOWED_ATTRIBUTES: Dict[str, Tuple[str, ...]] = {
    "*": ("class", "id"),
    "a": ("href", "title", "rel", "target"),
    "img": ("src", "alt", "title", "width", "height", "loading", "decoding"),
    "td": ("colspan", "rowspan"),
    "th": ("colspan", "rowspan"),
}
_BLOG_ALLOWED_PROTOCOLS = ("http", "https", "mailto", "tel")

_IMAGE_SIGNATURES: Tuple[Tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP checked below
)

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("100::/64"),
    ipaddress.ip_network("2001:db8::/32"),
)


def is_production() -> bool:
    """True when running in a deployed/production environment."""
    env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    if env in ("production", "prod", "live"):
        return True
    deploy = (os.getenv("DEPLOY_URL") or "").strip()
    return bool(deploy)


def validate_startup_security() -> None:
    """Fail fast when production is misconfigured."""
    secret = (os.getenv("SESSION_SECRET") or _DEFAULT_SESSION_SECRET).strip()
    if is_production():
        if secret in _WEAK_SESSION_SECRETS or len(secret) < 32:
            raise RuntimeError(
                "SESSION_SECRET must be set to a random string of at least 32 characters in production."
            )
        if not (
            os.getenv("GOOGLE_CLIENT_ID")
            or os.getenv("APPLE_CLIENT_ID")
        ):
            raise RuntimeError(
                "Production requires OAuth configuration (GOOGLE_CLIENT_ID or APPLE_CLIENT_ID)."
            )
        if os.getenv("AUTH_DEV_BYPASS", "").lower() in ("1", "true", "yes"):
            raise RuntimeError("AUTH_DEV_BYPASS must not be enabled in production.")
        if os.getenv("AUTH_LOCAL_ADMIN", "").lower() in ("1", "true", "yes"):
            raise RuntimeError("AUTH_LOCAL_ADMIN must not be enabled in production.")
        from .secrets_crypto import encryption_configured

        if not encryption_configured():
            raise RuntimeError(
                "Production requires SECRETS_ENCRYPTION_KEY (Fernet key) for encrypting API secrets at rest."
            )
    elif secret in _WEAK_SESSION_SECRETS:
        logger.warning(
            "Using default SESSION_SECRET — set a strong random value before deploying."
        )


def session_middleware_kwargs() -> dict:
    """Session cookie options tuned for environment."""
    return {
        "secret_key": os.getenv("SESSION_SECRET", _DEFAULT_SESSION_SECRET),
        "https_only": is_production(),
        "same_site": "lax",
        "max_age": 60 * 60 * 24 * 14,
    }


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RateLimiter:
    """Simple in-memory sliding-window rate limiter (per IP + route key)."""

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def check_request(
        self,
        request: Request,
        route_key: str,
        *,
        limit: int,
        window_seconds: int = 60,
    ) -> None:
        from fastapi import HTTPException

        ip = _client_ip(request)
        key = f"{route_key}:{ip}"
        if not self.allow(key, limit=limit, window_seconds=window_seconds):
            raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


class RedisRateLimiter:
    """Shared sliding-window rate limiter backed by Redis (multi-instance safe)."""

    def __init__(self, redis_url: str) -> None:
        import redis

        self._client = redis.from_url(redis_url, decode_responses=True)

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.time()
        redis_key = f"rl:{key}"
        member = f"{now}:{secrets.token_hex(4)}"
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(redis_key, 0, now - window_seconds)
        pipe.zadd(redis_key, {member: now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds + 1)
        _, _, count, _ = pipe.execute()
        return int(count) <= limit

    def check_request(
        self,
        request: Request,
        route_key: str,
        *,
        limit: int,
        window_seconds: int = 60,
    ) -> None:
        from fastapi import HTTPException

        ip = _client_ip(request)
        key = f"{route_key}:{ip}"
        try:
            allowed = self.allow(key, limit=limit, window_seconds=window_seconds)
        except Exception:
            logger.exception("Redis rate limiter unavailable; falling back to in-memory limiter")
            _fallback_rate_limiter.check_request(
                request, route_key, limit=limit, window_seconds=window_seconds
            )
            return
        if not allowed:
            raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


_fallback_rate_limiter = RateLimiter()
_rate_limiter: Optional[object] = None


def get_rate_limiter():
    global _rate_limiter
    if _rate_limiter is not None:
        return _rate_limiter
    redis_url = (os.getenv("REDIS_URL") or os.getenv("RATE_LIMIT_REDIS_URL") or "").strip()
    if redis_url:
        try:
            _rate_limiter = RedisRateLimiter(redis_url)
            logger.info("Rate limiting uses Redis backend")
            return _rate_limiter
        except Exception:
            logger.exception("Could not initialize Redis rate limiter; using in-memory fallback")
    _rate_limiter = _fallback_rate_limiter
    return _rate_limiter


class _RateLimiterProxy:
    def check_request(self, *args, **kwargs):
        return get_rate_limiter().check_request(*args, **kwargs)


rate_limiter = _RateLimiterProxy()


from .public_urls import is_private_path


_NOINDEX_EXACT: frozenset[str] = frozenset({"/login", "/upload", "/settings", "/oauth-debug"})


def _x_robots_tag_for_path(path: str) -> str | None:
    """Return noindex directive for private/app/generated routes."""
    if not path:
        return None
    if path in _NOINDEX_EXACT:
        return "noindex, nofollow"
    if path.startswith("/templates/") and path.endswith(".csv"):
        return "noindex, nofollow"
    if is_private_path(path):
        return "noindex, nofollow"
    return None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        path = request.url.path or ""
        robots = _x_robots_tag_for_path(path)
        if robots:
            response.headers.setdefault("X-Robots-Tag", robots)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        if is_production():
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        csp_parts = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com https://www.google-analytics.com",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self' https://www.google-analytics.com https://www.googletagmanager.com",
            "frame-src https://www.googletagmanager.com",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
        response.headers.setdefault("Content-Security-Policy", "; ".join(csp_parts))
        return response


def _is_blocked_ip(ip) -> bool:
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    for net in _PRIVATE_NETWORKS:
        if ip in net:
            return True
    return False


def _resolve_host_ips(hostname: str) -> list:
    hostname = (hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return []
    if hostname in ("localhost", "localhost.localdomain"):
        return [ipaddress.ip_address("127.0.0.1")]
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {hostname}") from exc
    ips = []
    for info in infos:
        addr = info[4][0]
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    return ips


def validate_ssrf_target(url: str) -> str:
    """
    Validate URL is safe to fetch (http/https, public host, no private/reserved IPs).
    Raises ValueError on unsafe targets.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs are allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL")
    host_lower = hostname.lower()
    if host_lower.endswith(".local") or host_lower.endswith(".internal"):
        raise ValueError("Internal hostnames are not allowed")
    if host_lower in ("metadata.google.internal", "metadata.goog"):
        raise ValueError("Metadata endpoints are not allowed")

    # Block literal IPs that are private/reserved.
    try:
        literal = ipaddress.ip_address(host_lower.strip("[]"))
        if _is_blocked_ip(literal):
            raise ValueError("Private or reserved IP addresses are not allowed")
        return url.strip()
    except ValueError as exc:
        if "does not appear to be an IPv4 or IPv6 address" not in str(exc):
            raise

    for ip in _resolve_host_ips(hostname):
        if _is_blocked_ip(ip):
            raise ValueError("URL resolves to a private or reserved IP address")
    return url.strip()


def sanitize_blog_html(html: str) -> str:
    """Sanitize CMS/blog HTML with an allowlist before public render or persist."""
    import bleach

    cleaned = bleach.clean(
        html or "",
        tags=list(_BLOG_ALLOWED_TAGS),
        attributes=_BLOG_ALLOWED_ATTRIBUTES,
        protocols=_BLOG_ALLOWED_PROTOCOLS,
        strip=True,
    )
    # Ensure rel=noopener on external links opened in new tab.
    cleaned = re.sub(
        r'(<a\b[^>]*\btarget=["\']_blank["\'][^>]*)(>)',
        lambda m: m.group(1) + (' rel="noopener noreferrer"' if 'rel=' not in m.group(1).lower() else "") + m.group(2),
        cleaned,
        flags=re.I,
    )
    return cleaned


def validate_image_content(raw: bytes, declared_type: str) -> str:
    """
    Verify image bytes match declared Content-Type via magic bytes.
    Returns normalized MIME type or raises ValueError.
    """
    if not raw:
        raise ValueError("Empty file")
    declared = (declared_type or "").split(";")[0].strip().lower()
    detected: Optional[str] = None
    for sig, mime in _IMAGE_SIGNATURES:
        if mime == "image/webp":
            if raw.startswith(b"RIFF") and len(raw) >= 12 and raw[8:12] == b"WEBP":
                detected = mime
                break
        elif raw.startswith(sig):
            detected = mime
            break
    if not detected:
        raise ValueError("File content is not a supported image format")
    if declared and declared != detected:
        raise ValueError(f"Content-Type {declared} does not match file content ({detected})")
    return detected


def require_not_production_debug(request: Request) -> None:
    """Block debug endpoints in production unless caller is admin."""
    if not is_production():
        return
    from .auth import is_admin

    if not is_admin(request):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Not found")


def protect_admin_docs(request: Request) -> None:
    """Restrict OpenAPI/Swagger to admins in production."""
    if not is_production():
        return
    from .auth import is_admin

    if not is_admin(request):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Not found")


def dev_auth_allowed() -> bool:
    """Dev login bypass only when explicitly enabled and not in production."""
    if is_production():
        return False
    if os.getenv("AUTH_DEV_BYPASS", "1").lower() not in ("1", "true", "yes"):
        return False
    if os.getenv("GOOGLE_CLIENT_ID") or os.getenv("APPLE_CLIENT_ID"):
        return False
    return True


def csrf_exempt(request: Request) -> bool:
    path = request.url.path or ""
    if path in _CSRF_EXEMPT_PATHS:
        return True
    # WayForPay POST return to /upload has no CSRF token.
    if request.method == "POST" and path == "/upload":
        return True
    return False


def get_or_create_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def csrf_hidden_input(token: str) -> str:
    import html

    return f'<input type="hidden" name="{CSRF_FORM_FIELD}" value="{html.escape(token)}" />'


def csrf_script_tag() -> str:
    return '<script src="/static/csrf.js"></script>'


def validate_csrf(request: Request, *, form_token: Optional[str] = None) -> None:
    """Validate double-submit CSRF token (header/form must match cookie or session)."""
    from fastapi import HTTPException

    if request.method in _SAFE_METHODS or csrf_exempt(request):
        return

    cookie_token = (request.cookies.get(CSRF_COOKIE) or "").strip()
    session_token = get_or_create_csrf_token(request)
    submitted = (
        request.headers.get(CSRF_HEADER)
        or request.headers.get("X-XSRF-TOKEN")
        or form_token
        or ""
    ).strip()
    if not submitted:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if cookie_token and secrets.compare_digest(submitted, cookie_token):
        return
    if session_token and secrets.compare_digest(submitted, session_token):
        return
    raise HTTPException(status_code=403, detail="CSRF validation failed")


class CsrfMiddleware(BaseHTTPMiddleware):
    """Issue CSRF cookie and validate mutating requests."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in _SAFE_METHODS and not csrf_exempt(request):
            form_token: Optional[str] = None
            content_type = (request.headers.get("content-type") or "").lower()
            if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
                try:
                    form = await request.form()
                    form_token = form.get(CSRF_FORM_FIELD)
                    if isinstance(form_token, list):
                        form_token = form_token[0] if form_token else None
                except Exception:
                    form_token = None
            validate_csrf(request, form_token=form_token)

        response = await call_next(request)

        token = get_or_create_csrf_token(request)
        response.set_cookie(
            CSRF_COOKIE,
            token,
            secure=is_production(),
            httponly=False,
            samesite="lax",
            max_age=60 * 60 * 24 * 14,
            path="/",
        )
        return response
