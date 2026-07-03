"""
Security helpers: production detection, HTTP headers, rate limiting, SSRF checks,
HTML sanitization, and startup validation.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict, Optional, Tuple
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("uvicorn.error")

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


rate_limiter = RateLimiter()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
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
