"""Canonical base URL and reusable <head> fragments for public SEO pages."""
from __future__ import annotations

import html
import json
import os
from datetime import date
from typing import Any, List, Optional, Tuple
from urllib.parse import quote

from fastapi import Request

# When DEPLOY_URL is unset (local dev), canonical/og:sitemap use this absolute origin — not request.host (avoids 127.0.0.1:random in metadata).
_LOCAL_DEV_SITE_BASE = "http://localhost:8000"

BRAND_NAME = "Cartozo.ai"
SUPPORT_EMAIL = "support@cartozo.ai"
BRAND_DESCRIPTION = (
    "Cartozo.ai is an AI-powered product feed optimization platform for e-commerce teams, "
    "performance marketers, and agencies working with Google Merchant Center and Google Shopping feeds."
)

# Public marketing URLs for sitemap (path, priority, changefreq).
PUBLIC_SITEMAP_STATIC: List[Tuple[str, str, str]] = [
    ("/", "1.0", "weekly"),
    ("/how-it-works", "0.9", "monthly"),
    ("/feed-structure", "0.85", "monthly"),
    ("/features", "0.85", "monthly"),
    ("/presentation", "0.8", "monthly"),
    ("/pricing", "0.9", "monthly"),
    ("/faq", "0.7", "monthly"),
    ("/contact", "0.8", "monthly"),
    ("/about", "0.6", "yearly"),
    ("/blog", "0.9", "daily"),
    ("/guides", "0.85", "monthly"),
    ("/blog/topics/google-merchant-center-issues", "0.75", "weekly"),
    ("/blog/topics/title-description-optimization", "0.75", "weekly"),
    ("/blog/topics/feed-quality-governance", "0.75", "weekly"),
    ("/blog/topics/large-catalogs-agencies", "0.75", "weekly"),
    ("/blog/topics/multichannel-marketplace-feeds", "0.75", "weekly"),
    ("/use-cases/fix-google-merchant-center-disapprovals", "0.85", "monthly"),
    ("/use-cases/optimize-google-shopping-product-titles", "0.85", "monthly"),
    ("/use-cases/product-feed-optimization-for-agencies", "0.85", "monthly"),
    ("/use-cases/large-catalog-feed-optimization", "0.85", "monthly"),
    ("/use-cases/product-feed-quality-audit", "0.85", "monthly"),
    ("/guides/google-merchant-center-feed-optimization", "0.85", "monthly"),
    ("/guides/google-shopping-title-optimization", "0.85", "monthly"),
    ("/guides/fix-missing-gtin-google-merchant-center", "0.85", "monthly"),
    ("/guides/product-feed-quality-audit", "0.85", "monthly"),
    ("/guides/product-feed-optimization-checklist", "0.85", "monthly"),
    ("/guides/product-feed-optimization-for-large-catalogs", "0.85", "monthly"),
    ("/terms", "0.4", "yearly"),
    ("/privacy", "0.4", "yearly"),
    ("/cookies", "0.4", "yearly"),
    ("/refund-policy", "0.4", "yearly"),
]


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
    base = site_base_url().rstrip("/")
    obj: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "url": url,
        "description": (description or "")[:500],
        "author": {"@type": "Organization", "@id": f"{base}/#organization", "name": BRAND_NAME},
        "publisher": {"@id": f"{base}/#organization"},
        "mainEntityOfPage": url,
    }
    if date_published and len(date_published) >= 10:
        obj["datePublished"] = date_published[:10]
    if date_modified and len(date_modified) >= 10:
        obj["dateModified"] = date_modified[:10]
    elif date_published and len(date_published) >= 10:
        obj["dateModified"] = date_published[:10]
    if image and str(image).strip():
        obj["image"] = str(image).strip()
    return json_ld_script(obj)


def organization_json_ld_graph(*, logo_url: str = "") -> str:
    """Sitewide Organization + WebSite + SoftwareApplication @graph."""
    base = site_base_url().rstrip("/")
    logo = (logo_url or f"{base}/assets/logo-dark.png").strip()
    graph: dict[str, Any] = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{base}/#organization",
                "name": BRAND_NAME,
                "url": f"{base}/",
                "logo": logo,
                "description": BRAND_DESCRIPTION,
                "email": SUPPORT_EMAIL,
            },
            {
                "@type": "WebSite",
                "@id": f"{base}/#website",
                "url": f"{base}/",
                "name": BRAND_NAME,
                "publisher": {"@id": f"{base}/#organization"},
            },
            {
                "@type": "SoftwareApplication",
                "@id": f"{base}/#software",
                "name": BRAND_NAME,
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "Web",
                "description": BRAND_DESCRIPTION,
                "url": f"{base}/",
                "offers": [
                    {"@type": "Offer", "name": "Basic", "price": "5", "priceCurrency": "USD", "priceSpecification": {"@type": "UnitPriceSpecification", "price": "5", "priceCurrency": "USD", "unitText": "MONTH"}},
                    {"@type": "Offer", "name": "Starter", "price": "19", "priceCurrency": "USD", "priceSpecification": {"@type": "UnitPriceSpecification", "price": "19", "priceCurrency": "USD", "unitText": "MONTH"}},
                    {"@type": "Offer", "name": "Growth", "price": "49", "priceCurrency": "USD", "priceSpecification": {"@type": "UnitPriceSpecification", "price": "49", "priceCurrency": "USD", "unitText": "MONTH"}},
                    {"@type": "Offer", "name": "Pro", "price": "99", "priceCurrency": "USD", "priceSpecification": {"@type": "UnitPriceSpecification", "price": "99", "priceCurrency": "USD", "unitText": "MONTH"}},
                ],
            },
        ],
    }
    return json_ld_script(graph)


def breadcrumb_json_ld(*, items: list[tuple[str, str]]) -> str:
    elements = []
    for i, (name, url) in enumerate(items, start=1):
        elements.append(
            {
                "@type": "ListItem",
                "position": i,
                "name": name,
                "item": url,
            }
        )
    return json_ld_script(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": elements,
        }
    )


def web_page_json_ld(
    *,
    url: str,
    name: str,
    description: str,
    date_published: str = "",
    date_modified: str = "",
) -> str:
    base = site_base_url().rstrip("/")
    obj: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "@id": f"{url}#webpage",
        "url": url,
        "name": name,
        "description": (description or "")[:500],
        "isPartOf": {"@id": f"{base}/#website"},
        "publisher": {"@id": f"{base}/#organization"},
    }
    if date_published and len(date_published) >= 10:
        obj["datePublished"] = date_published[:10]
    if date_modified and len(date_modified) >= 10:
        obj["dateModified"] = date_modified[:10]
    return json_ld_script(obj)


def seo_cached_snapshot_is_stale(cached: str) -> bool:
    """True when admin-cached robots/sitemap was built for a different origin (e.g. localhost)."""
    c = (cached or "").strip()
    if not c:
        return False
    base = site_base_url().rstrip("/")
    if not base:
        return False
    if base.startswith("https://") and ("localhost" in c or "127.0.0.1" in c):
        return True
    return base not in c


def build_robots_txt_body(base: str) -> str:
    """Public robots.txt with AI crawler rules."""
    b = base.rstrip("/")
    return f"""User-agent: *
Allow: /

Sitemap: {b}/sitemap.xml

# OpenAI / ChatGPT Search
User-agent: OAI-SearchBot
Allow: /

User-agent: ChatGPT-User
Allow: /

# Block model training; allow search bots above
User-agent: GPTBot
Disallow: /

# Anthropic / Claude Search
User-agent: Claude-SearchBot
Allow: /

User-agent: Claude-User
Allow: /

User-agent: ClaudeBot
Disallow: /

# Perplexity
User-agent: PerplexityBot
Allow: /

User-agent: Perplexity-User
Allow: /

# Google Search / AI Overviews
User-agent: Googlebot
Allow: /

# Microsoft / Bing / Copilot
User-agent: bingbot
Allow: /

# App areas — block for all bots
User-agent: *
Disallow: /admin
Disallow: /api/
Disallow: /articles/
Disallow: /batches/
Disallow: /upload
Disallow: /settings
Disallow: /login
Disallow: /auth/
Disallow: /merchant/
Disallow: /docs
Disallow: /logout
"""


def build_llms_txt_body(base: str) -> str:
    """Curated llms.txt for AI agents."""
    b = base.rstrip("/")
    today = date.today().isoformat()
    lines = [
        "# Cartozo.ai",
        "",
        f"> {BRAND_DESCRIPTION} It analyzes product feed data, detects weak or missing attributes, improves product titles and descriptions around shopper search intent, assigns feed quality scores, and exports a Merchant-ready CSV.",
        "",
        f"Support: {SUPPORT_EMAIL}",
        f"Last updated: {today}",
        "",
        "## Core product pages",
        f"- {b}/ — Overview and workflow",
        f"- {b}/how-it-works — CSV upload to optimized Merchant-ready export",
        f"- {b}/feed-structure — Google Merchant product feed fields",
        f"- {b}/features — Product capabilities",
        f"- {b}/pricing — SaaS plans (Basic $5, Starter $19, Growth $49, Pro $99 per month)",
        f"- {b}/faq — Product, Merchant Center, workflow, pricing, data, and support",
        f"- {b}/contact — Contact and support",
        "",
        "## Key use cases",
        f"- {b}/use-cases/fix-google-merchant-center-disapprovals",
        f"- {b}/use-cases/optimize-google-shopping-product-titles",
        f"- {b}/use-cases/product-feed-optimization-for-agencies",
        f"- {b}/use-cases/large-catalog-feed-optimization",
        f"- {b}/use-cases/product-feed-quality-audit",
        "",
        "## Guides",
        f"- {b}/guides/google-merchant-center-feed-optimization",
        f"- {b}/guides/fix-missing-gtin-google-merchant-center",
        f"- {b}/guides/product-feed-quality-audit",
        f"- {b}/guides/google-shopping-title-optimization",
        f"- {b}/guides/product-feed-optimization-checklist",
        f"- {b}/guides/product-feed-optimization-for-large-catalogs",
        "",
        "## Blog",
        f"- {b}/blog — Articles on feed quality, Merchant Center, and optimization",
        "",
    ]
    return "\n".join(lines) + "\n"
