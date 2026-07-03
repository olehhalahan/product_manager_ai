"""Public blog topic clusters for topical SEO and internal linking."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# slug, name, description, related (href, label) pairs
PUBLIC_BLOG_TOPICS: List[Dict[str, Any]] = [
    {
        "slug": "google-merchant-center-issues",
        "name": "Google Merchant Center issues",
        "description": "Disapprovals, missing GTIN, feed errors, required attributes, and policy-related data problems.",
        "related": [
            ("/use-cases/fix-google-merchant-center-disapprovals", "Fix Merchant Center disapprovals"),
            ("/guides/fix-missing-gtin-google-merchant-center", "Fix missing GTIN"),
            ("/feed-structure", "Feed structure reference"),
        ],
    },
    {
        "slug": "product-title-and-description-optimization",
        "name": "Product title and description optimization",
        "description": "Title structure, search intent, attributes, CTR impact, and before/after examples.",
        "related": [
            ("/use-cases/optimize-google-shopping-product-titles", "Optimize Shopping titles"),
            ("/guides/google-shopping-title-optimization", "Title optimization guide"),
        ],
    },
    {
        "slug": "feed-quality-and-data-governance",
        "name": "Feed quality and data governance",
        "description": "Feed audits, quality scores, data accuracy, version control, and update workflows.",
        "related": [
            ("/use-cases/product-feed-quality-audit", "Feed quality audit use case"),
            ("/guides/product-feed-quality-audit", "Feed quality audit guide"),
            ("/guides/product-feed-optimization-checklist", "Optimization checklist"),
        ],
    },
    {
        "slug": "large-catalogs-and-agencies",
        "name": "Large catalogs and agencies",
        "description": "Bulk processing, agency workflows, multi-client feeds, and large SKU catalogs.",
        "related": [
            ("/use-cases/large-catalog-feed-optimization", "Large catalog optimization"),
            ("/use-cases/product-feed-optimization-for-agencies", "Agency feed optimization"),
            ("/guides/product-feed-optimization-for-large-catalogs", "Large catalog guide"),
        ],
    },
    {
        "slug": "multichannel-and-marketplace-feeds",
        "name": "Multichannel and marketplace feeds",
        "description": "Google Shopping, marketplaces, feed localization, and international catalogs.",
        "related": [
            ("/guides/google-merchant-center-feed-optimization", "Merchant Center optimization"),
            ("/how-it-works", "How Cartozo.ai works"),
        ],
    },
]

# Legacy short slugs from early PR — 301 to canonical slugs above.
TOPIC_SLUG_REDIRECTS: Dict[str, str] = {
    "title-description-optimization": "product-title-and-description-optimization",
    "feed-quality-governance": "feed-quality-and-data-governance",
    "large-catalogs-agencies": "large-catalogs-and-agencies",
    "multichannel-marketplace-feeds": "multichannel-and-marketplace-feeds",
}

DEFAULT_CONTENT_CLUSTERS: List[Tuple[str, str, str]] = [
    (t["slug"], t["name"], t["description"]) for t in PUBLIC_BLOG_TOPICS
]


def topic_by_slug(slug: str) -> Dict[str, Any] | None:
    s = (slug or "").strip().lower()
    for t in PUBLIC_BLOG_TOPICS:
        if t["slug"] == s:
            return t
    return None


def resolve_topic_slug(slug: str) -> tuple[Dict[str, Any] | None, str | None]:
    """Return (topic, legacy_redirect_slug). redirect set when slug is an old alias."""
    s = (slug or "").strip().lower()
    if s in TOPIC_SLUG_REDIRECTS:
        return None, TOPIC_SLUG_REDIRECTS[s]
    t = topic_by_slug(s)
    return t, None


def related_links_for_cluster_slug(cluster_slug: str) -> List[Tuple[str, str]]:
    t = topic_by_slug(cluster_slug)
    if not t:
        return []
    return list(t.get("related") or [])
