"""Canonical base URL and reusable <head> fragments for public SEO pages."""
from __future__ import annotations

import html
import json
import os
from typing import Any

from fastapi import Request


def public_site_base(request: Request) -> str:
    """Site origin for canonical links, og:url, sitemap (set DEPLOY_URL in production)."""
    u = (os.getenv("DEPLOY_URL") or "").strip().rstrip("/")
    if u:
        return u
    return str(request.base_url).rstrip("/")


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
    return json_ld_script(obj)
