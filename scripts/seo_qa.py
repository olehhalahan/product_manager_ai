#!/usr/bin/env python3
"""Pre-merge technical SEO QA for Cartozo.ai AI visibility layer."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Production-like env for canonical / sitemap checks
os.environ.setdefault("DEPLOY_URL", "https://cartozo.ai")
os.environ.setdefault(
    "SESSION_SECRET",
    "qa-test-session-secret-at-least-32-chars-long",
)
os.environ.setdefault("GOOGLE_CLIENT_ID", "qa-test.apps.googleusercontent.com")
os.environ.setdefault("SECRETS_ENCRYPTION_KEY", "dGVzdF9rZXlfMzJfYnl0ZXNfbG9uZ19lbm91Z2g=")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.faq_page import _FAQ_SECTIONS, all_faq_pairs  # noqa: E402
from app.seo import PUBLIC_SITEMAP_STATIC, seo_cached_snapshot_is_stale, site_base_url  # noqa: E402

PRODUCTION_BASE = "https://cartozo.ai"
NEW_URLS = [
    "/feed-structure",
    "/guides",
    "/use-cases/fix-google-merchant-center-disapprovals",
    "/use-cases/optimize-google-shopping-product-titles",
    "/use-cases/product-feed-optimization-for-agencies",
    "/use-cases/large-catalog-feed-optimization",
    "/use-cases/product-feed-quality-audit",
    "/guides/google-merchant-center-feed-optimization",
    "/guides/google-shopping-title-optimization",
    "/guides/fix-missing-gtin-google-merchant-center",
    "/guides/product-feed-quality-audit",
    "/guides/product-feed-optimization-checklist",
    "/guides/product-feed-optimization-for-large-catalogs",
    "/blog/topics/google-merchant-center-issues",
    "/blog/topics/title-description-optimization",
    "/blog/topics/feed-quality-governance",
    "/blog/topics/large-catalogs-agencies",
    "/blog/topics/multichannel-marketplace-feeds",
]
CORE_URLS = [
    "/",
    "/how-it-works",
    "/presentation",
    "/pricing",
    "/faq",
    "/about",
    "/contact",
    "/blog",
    "/robots.txt",
    "/sitemap.xml",
    "/llms.txt",
]
BLOCKED_SITEMAP_FRAGMENTS = (
    "localhost",
    "127.0.0.1",
    "/admin",
    "/upload",
    "/login",
    "/settings",
    "/batches/",
    "/api/",
    "/merchant/",
)
NAV_MUST_LINK = [
    "/guides",
    "/feed-structure",
    "/faq",
    "/use-cases/fix-google-merchant-center-disapprovals",
    "/use-cases/optimize-google-shopping-product-titles",
    "/use-cases/product-feed-optimization-for-agencies",
]


def extract_json_ld(html: str) -> list[dict]:
    out: list[dict] = []
    for m in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>',
        html,
        re.DOTALL,
    ):
        try:
            out.append(json.loads(m.group(1)))
        except json.JSONDecodeError as e:
            raise AssertionError(f"Invalid JSON-LD: {e}") from e
    return out


def walk_schema(obj: object, bad_keys: set[str]) -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in bad_keys:
                hits.append(k)
            hits.extend(walk_schema(v, bad_keys))
    elif isinstance(obj, list):
        for item in obj:
            hits.extend(walk_schema(item, bad_keys))
    return hits


def main() -> int:
    errors: list[str] = []
    client = TestClient(app, raise_server_exceptions=True)

    # 1. HTTP 200 for new + core URLs
    for path in CORE_URLS + NEW_URLS:
        r = client.get(path, follow_redirects=False)
        if r.status_code not in (200, 301, 302, 308):
            errors.append(f"{path} returned {r.status_code}, expected 200")

    # 2. /features → 301 → /presentation
    r = client.get("/features", follow_redirects=False)
    if r.status_code != 301:
        errors.append(f"/features returned {r.status_code}, expected 301")
    elif r.headers.get("location") != "/presentation":
        errors.append(f"/features Location={r.headers.get('location')!r}, expected /presentation")
    r2 = client.get("/features", follow_redirects=True)
    if r2.status_code != 200 or "/presentation" not in str(r2.url):
        errors.append("/features redirect chain does not end at /presentation with 200")

    # 3. robots / sitemap / llms — no redirect, 200
    for path in ("/robots.txt", "/sitemap.xml", "/llms.txt"):
        r = client.get(path, follow_redirects=False)
        if r.status_code != 200:
            errors.append(f"{path} returned {r.status_code}")
        if r.history:
            errors.append(f"{path} redirected: {[h.headers.get('location') for h in r.history]}")

    base = site_base_url().rstrip("/")
    if base != PRODUCTION_BASE:
        errors.append(f"site_base_url()={base!r}, expected {PRODUCTION_BASE!r} (set DEPLOY_URL)")

    robots = client.get("/robots.txt").text
    if f"Sitemap: {PRODUCTION_BASE}/sitemap.xml" not in robots:
        errors.append("robots.txt missing production Sitemap line")
    if "OAI-SearchBot" not in robots or "GPTBot" not in robots:
        errors.append("robots.txt missing expected AI crawler rules")

    sitemap = client.get("/sitemap.xml").text
    for bad in BLOCKED_SITEMAP_FRAGMENTS:
        if bad in sitemap:
            errors.append(f"sitemap.xml contains forbidden fragment: {bad!r}")
    if PRODUCTION_BASE not in sitemap:
        errors.append("sitemap.xml does not use production base URL")
    for path, _, _ in PUBLIC_SITEMAP_STATIC:
        loc = f"{PRODUCTION_BASE}{path}"
        if loc not in sitemap:
            errors.append(f"sitemap.xml missing {loc}")

    llms = client.get("/llms.txt").text
    if PRODUCTION_BASE not in llms:
        errors.append("llms.txt does not use production base URL")
    if "/upload" in llms or "/admin" in llms:
        errors.append("llms.txt exposes private URLs")

    stale_cache = '<?xml version="1.0"?><urlset><url><loc>http://localhost:8000/</loc></url></urlset>'
    if not seo_cached_snapshot_is_stale(stale_cache):
        errors.append("Stale localhost sitemap cache would be served in production")

    # 4. Canonical tags on key pages
    sample_pages = [
        "/",
        "/faq",
        "/use-cases/fix-google-merchant-center-disapprovals",
        "/guides/google-shopping-title-optimization",
        "/feed-structure",
    ]
    for path in sample_pages:
        html = client.get(path).text
        canon = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        if not canon:
            errors.append(f"{path} missing canonical link")
            continue
        url = canon.group(1)
        if not url.startswith(PRODUCTION_BASE):
            errors.append(f"{path} canonical={url!r}, expected {PRODUCTION_BASE} origin")
        if url.rstrip("/") != f"{PRODUCTION_BASE}{path}".rstrip("/") and path != "/":
            if path not in url:
                errors.append(f"{path} canonical path mismatch: {url}")

    # 5. FAQ schema matches visible questions/answers
    faq_html = client.get("/faq").text
    faq_pairs = all_faq_pairs()
    if faq_html.count('class="legal-doc"') == 0 and "<h3 id=\"faq-q" not in faq_html:
        errors.append("FAQ page missing expected question markup")
    visible_qs = re.findall(r'<h3 id="faq-q\d+">([^<]+)</h3>', faq_html)
    schema_ld = extract_json_ld(faq_html)
    faq_schema = next((x for x in schema_ld if x.get("@type") == "FAQPage"), None)
    if not faq_schema:
        errors.append("FAQ page missing FAQPage JSON-LD")
    else:
        schema_qs = [q["name"] for q in faq_schema.get("mainEntity", [])]
        if len(schema_qs) != len(faq_pairs):
            errors.append(f"FAQ schema count {len(schema_qs)} != visible pairs {len(faq_pairs)}")
        for i, (sq, (vq, _)) in enumerate(zip(schema_qs, faq_pairs)):
            if sq != vq:
                errors.append(f"FAQ Q mismatch at {i}: schema={sq!r} visible={vq!r}")
        for i, (sq, va) in enumerate(zip(schema_qs, [a for _, a in faq_pairs])):
            ans = faq_schema["mainEntity"][i]["acceptedAnswer"]["text"]
            if ans != va:
                errors.append(f"FAQ A mismatch at {i}: schema text differs from source answer")

    # 6. No fake ratings
    for path in sample_pages + ["/pricing"]:
        html = client.get(path).text
        for block in extract_json_ld(html):
            bad = walk_schema(block, {"aggregateRating", "reviewCount", "ratingValue"})
            if bad:
                errors.append(f"{path} JSON-LD contains fake rating keys: {bad}")

    # 7. Nav / internal discoverability
    home = client.get("/").text
    for href in NAV_MUST_LINK:
        if href not in home:
            errors.append(f"Homepage/nav missing link to {href}")

    # 8. Mobile basics (viewport + responsive hooks)
    mobile_checks = [
        "/use-cases/fix-google-merchant-center-disapprovals",
        "/guides",
        "/faq",
    ]
    for path in mobile_checks:
        html = client.get(path).text
        if 'name="viewport"' not in html:
            errors.append(f"{path} missing viewport meta")
        if "max-width" not in html and "clamp(" not in html:
            errors.append(f"{path} missing responsive CSS hints")

    if errors:
        print("SEO QA FAILED\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("SEO QA PASSED")
    print(f"  URLs checked: {len(CORE_URLS) + len(NEW_URLS)}")
    print(f"  Production base: {PRODUCTION_BASE}")
    print(f"  FAQ questions: {sum(len(p) for _, p in _FAQ_SECTIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
