"""Canonical public URL collection for sitemap, RSS, IndexNow, robots, and QA."""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Set
from urllib.parse import quote, urlparse

from .seo import PUBLIC_SITEMAP_STATIC, canonical_url_blog_article, site_base_url

# Single source of truth for private/authenticated app areas.
# Used by robots.txt, X-Robots-Tag middleware, sitemap/RSS/llms/IndexNow filtering, and QA.
PRIVATE_ROUTE_PREFIXES: tuple[str, ...] = (
    "/admin",
    "/api/",
    "/articles/",
    "/auth/",
    "/batches",
    "/dashboard",
    "/app/",
    "/login",
    "/logout",
    "/upload",
    "/settings",
    "/merchant/",
    "/docs",
    "/oauth-debug",
    # Defensive SaaS prefixes (no public marketing pages at these paths today).
    "/account",
    "/billing",
    "/exports",
)

# Backward-compatible alias.
PRIVATE_PATH_PREFIXES = PRIVATE_ROUTE_PREFIXES

# Raw downloadable assets: landing pages are indexed; direct CSV files are not in sitemap.
PUBLIC_TEMPLATE_CSV_PATHS: tuple[str, ...] = (
    "/templates/google-merchant-center-feed-template.csv",
    "/templates/sample-product-feed-before.csv",
    "/templates/sample-product-feed-after.csv",
)


def production_base_url() -> Optional[str]:
    """Return https production base or None when not configured for production."""
    base = site_base_url().rstrip("/")
    if not base.startswith("https://"):
        return None
    host = (urlparse(base).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return None
    if "staging." in host or host.startswith("dev.") or ".dev." in host:
        return None
    return base


def robots_disallow_lines() -> tuple[str, ...]:
    """Disallow prefixes for robots.txt wildcard group."""
    return PRIVATE_ROUTE_PREFIXES


def private_route_fragments() -> tuple[str, ...]:
    """Substring fragments forbidden in sitemap, llms.txt, RSS, and QA scans."""
    return PRIVATE_ROUTE_PREFIXES


def is_private_path(path: str) -> bool:
    p = path if path.startswith("/") else f"/{path}"
    return any(p == pref.rstrip("/") or p.startswith(pref) for pref in PRIVATE_ROUTE_PREFIXES)


def is_public_canonical_url(url: str) -> bool:
    """True when URL is an indexable production marketing URL."""
    u = (url or "").strip()
    if not u:
        return False
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return False
    base = production_base_url()
    if not base:
        return False
    if not u.startswith(base):
        return False
    path = parsed.path or "/"
    if is_private_path(path):
        return False
    if path.startswith("/templates/") and path.endswith(".csv"):
        return False
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1") or "staging." in host:
        return False
    return True


def static_public_paths() -> List[str]:
    return [path for path, _, _ in PUBLIC_SITEMAP_STATIC]


def collect_public_page_urls(db: Any, *, include_blog: bool = True, limit: int = 500) -> List[str]:
    """Absolute canonical URLs for sitemap, IndexNow, and RSS sources."""
    from .services import db_repository as repo

    base = site_base_url().rstrip("/")
    urls: List[str] = []
    seen: Set[str] = set()

    def add(path: str) -> None:
        if is_private_path(path):
            return
        loc = f"{base}{path}"
        if loc not in seen:
            seen.add(loc)
            urls.append(loc)

    for path in static_public_paths():
        add(path)

    if include_blog:
        articles = repo.list_blog_articles_published(db, limit=limit)
        for article in articles:
            slug = (article.get("slug") or "").strip()
            if slug:
                add(f"/blog/{quote(slug, safe='')}")

    return urls


def filter_production_public_urls(urls: Iterable[str]) -> tuple[List[str], List[str]]:
    """Return (accepted, rejected) URL lists."""
    accepted: List[str] = []
    rejected: List[str] = []
    for url in urls:
        if is_public_canonical_url(url):
            accepted.append(url)
        else:
            rejected.append(url)
    return accepted, rejected
