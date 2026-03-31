"""Canonical base URL and reusable <head> fragments for public SEO pages."""
from __future__ import annotations

import html
import json
import os
from typing import Any, Optional
from urllib.parse import quote

from fastapi import Request

# When DEPLOY_URL is unset (local dev), canonical/og:sitemap use this absolute origin — not request.host (avoids 127.0.0.1:random in metadata).
_LOCAL_DEV_SITE_BASE = "http://localhost:8000"


def site_base_url() -> str:
    """
    Absolute site origin with no trailing slash.

    Production: set DEPLOY_URL (e.g. https://cartozo.ai).
    Local: defaults to http://localhost:8000 if DEPLOY_URL is empty.
    """
    u = (os.getenv("DEPLOY_URL") or "").strip().rstrip("/")
    return u if u else _LOCAL_DEV_SITE_BASE


def public_site_base(request: Request) -> str:
    """Same as site_base_url(). Request is kept for call-site compatibility."""
    return site_base_url()


def canonical_url_for_request(request: Request) -> str:
    """Full canonical URL for the current path (no query string). Uses DEPLOY_URL via site_base_url()."""
    base = site_base_url().rstrip("/")
    path = request.url.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def canonical_url_blog_article(slug: str) -> str:
    """Absolute /blog/{slug} URL for SEO (slug encoded for path safety)."""
    s = (slug or "").strip()
    return f"{site_base_url().rstrip('/')}/blog/{quote(s, safe='')}"


def esc_attr(s: str) -> str:
    return html.escape(s or "", quote=True)


def head_canonical_og_url_type(*, canonical_url: str, og_type: str = "website") -> str:
    """Use when the page already has full og:title / twitter; avoids duplicate social tags."""
    cu = esc_attr(canonical_url)
    ot = esc_attr(og_type)
    return (
        f'    <link rel="canonical" href="{cu}"/>\n'
        f'    <meta property="og:url" content="{cu}"/>\n'
        f'    <meta property="og:type" content="{ot}"/>\n'
    )


def head_canonical_social(
    *,
    canonical_url: str,
    og_title: str,
    og_description: str,
    og_image: str = "",
    og_site_name: str = "",
    og_type: str = "website",
    og_image_width: Optional[int] = None,
    og_image_height: Optional[int] = None,
) -> str:
    """Canonical + og:url/type + optional og:image/site_name + Twitter card (full block)."""
    cu = esc_attr(canonical_url)
    ot = esc_attr(og_title)
    od = esc_attr(og_description)
    oi = esc_attr(og_image)
    osn = esc_attr(og_site_name)
    lines = [
        f'    <link rel="canonical" href="{cu}"/>',
        f'    <meta property="og:url" content="{cu}"/>',
        f'    <meta property="og:type" content="{esc_attr(og_type)}"/>',
    ]
    if og_site_name:
        lines.append(f'    <meta property="og:site_name" content="{osn}"/>')
    lines.extend(
        [
            f'    <meta property="og:title" content="{ot}"/>',
            f'    <meta property="og:description" content="{od}"/>',
        ]
    )
    if og_image.strip():
        lines.append(f'    <meta property="og:image" content="{oi}"/>')
        if og_image_width is not None:
            lines.append(f'    <meta property="og:image:width" content="{int(og_image_width)}"/>')
        if og_image_height is not None:
            lines.append(f'    <meta property="og:image:height" content="{int(og_image_height)}"/>')
    lines.extend(
        [
            '    <meta name="twitter:card" content="summary_large_image"/>',
            f'    <meta name="twitter:title" content="{ot}"/>',
            f'    <meta name="twitter:description" content="{od}"/>',
        ]
    )
    if og_image.strip():
        lines.append(f'    <meta name="twitter:image" content="{oi}"/>')
    return "\n".join(lines) + "\n"


def json_ld_script(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    payload = payload.replace("<", "\\u003c")
    return f'    <script type="application/ld+json">{payload}</script>\n'


def website_json_ld(*, site_url: str, name: str) -> str:
    return json_ld_script(
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": name,
            "url": site_url.rstrip("/") + "/",
        }
    )


def faq_page_json_ld(*, questions: list[tuple[str, str]]) -> str:
    """Schema.org FAQPage from (question, answer) pairs (plain text)."""
    main_entity: list[dict[str, Any]] = []
    for q, a in questions:
        main_entity.append(
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
        )
    return json_ld_script({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": main_entity})


def blog_posting_json_ld(
    *,
    headline: str,
    url: str,
    description: str,
    date_published: str,
    date_modified: str | None = None,
    image: Optional[str] = None,
) -> str:
    obj: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": headline,
        "url": url,
        "description": (description or "")[:500],
    }
    if date_published and len(date_published) >= 10:
        obj["datePublished"] = date_published[:10]
    if date_modified and len(date_modified) >= 10:
        obj["dateModified"] = date_modified[:10]
    if image and str(image).strip():
        obj["image"] = str(image).strip()
    return json_ld_script(obj)
