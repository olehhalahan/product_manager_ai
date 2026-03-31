"""Topic → visual theme and stable layout variant (deterministic per slug)."""

from __future__ import annotations

import hashlib
from typing import Dict, List, Tuple

# (theme_id, keyword needles in title/topic/keywords/type)
_THEME_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("disapprovals", ("disapprov", "rejected", "violation", "suspended")),
    ("gtin", ("gtin", "identifier", "mpn", "barcode", "unique product")),
    ("merchant_errors", ("merchant center", "gmc", "diagnostic", "shopping")),
    ("feed_optimization", ("feed", "csv", "catalog", "listing", "xml")),
    ("titles_descriptions", ("title", "description", "snippet", "copy")),
    ("localization", ("translat", "locali", "language", "locale", "multi-country")),
    ("scaling", ("scale", "growth", "bulk", "million", "enterprise")),
    ("automation", ("automat", "workflow", "pipeline", "batch")),
]

THEME_LABELS: Dict[str, str] = {
    "disapprovals": "Disapprovals",
    "gtin": "Identifiers",
    "merchant_errors": "Merchant Center",
    "feed_optimization": "Feed optimization",
    "titles_descriptions": "Titles & descriptions",
    "localization": "Localization",
    "scaling": "Catalog scale",
    "automation": "Automation",
    "feed_optimization_default": "Product data",
}

# Accent + gradient stops for CSS variables
THEME_STYLE: Dict[str, Dict[str, str]] = {
    "disapprovals": {"accent": "#f87171", "g0": "rgba(248,113,113,0.35)", "g1": "rgba(15,23,42,0)"},
    "gtin": {"accent": "#22D3EE", "g0": "rgba(34,211,238,0.28)", "g1": "rgba(15,23,42,0)"},
    "merchant_errors": {"accent": "#a78bfa", "g0": "rgba(167,139,250,0.3)", "g1": "rgba(15,23,42,0)"},
    "feed_optimization": {"accent": "#4F46E5", "g0": "rgba(79,70,229,0.35)", "g1": "rgba(15,23,42,0)"},
    "titles_descriptions": {"accent": "#34d399", "g0": "rgba(52,211,153,0.25)", "g1": "rgba(15,23,42,0)"},
    "localization": {"accent": "#fbbf24", "g0": "rgba(251,191,36,0.22)", "g1": "rgba(15,23,42,0)"},
    "scaling": {"accent": "#818cf8", "g0": "rgba(129,140,248,0.3)", "g1": "rgba(15,23,42,0)"},
    "automation": {"accent": "#06b6d4", "g0": "rgba(6,182,212,0.28)", "g1": "rgba(15,23,42,0)"},
    "feed_optimization_default": {"accent": "#4F46E5", "g0": "rgba(79,70,229,0.28)", "g1": "rgba(15,23,42,0)"},
}


def resolve_theme_key(title: str, topic: str, keywords: str, article_type: str) -> str:
    blob = f"{title or ''} {topic or ''} {keywords or ''} {article_type or ''}".lower()
    for key, needles in _THEME_RULES:
        if any(n in blob for n in needles):
            return key
    return "feed_optimization_default"


def layout_variant_for_slug(slug: str) -> str:
    h = int(hashlib.sha256((slug or "").encode()).hexdigest()[:8], 16)
    return ("a", "b", "c")[h % 3]


def prompt_visual_label_for_theme(theme_key: str) -> str:
    """Short phrase for LLM visual context (replaces inlined cheap diagram copy)."""
    label = THEME_LABELS.get(theme_key, "Product feed")
    return f"{label} — Cartozo-style feed workflow (hero graphic, not inline diagram)."


def theme_style(theme_key: str) -> Dict[str, str]:
    return THEME_STYLE.get(theme_key) or THEME_STYLE["feed_optimization_default"]
