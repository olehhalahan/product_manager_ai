"""
Writter: SEO article generation, slugging, visual templates (no image LLM), internal links.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import openai

    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    openai = None

# Short label (legacy / compact)
STRUCTURE_BY_TYPE: Dict[str, str] = {
    "problem_solving": "Problem → Consequences → Solution → CTA",
    "feature_presentation": "Problem → Feature → How it works → Benefits",
    "informational": "Introduction → Main sections → Conclusion",
    "use_cases": "Context → How they used it → Results",
    "comparison": "X vs Y → When to choose → Trade-offs → Product fit → CTA",
    "checklist_template": "Checklist → Steps → Tips → Download/try CTA",
}

# Full blueprints for the model (content frameworks)
BLUEPRINT_BY_TYPE: Dict[str, str] = {
    "problem_solving": """Sections to cover (in order):
1) Pain — what breaks / hurts for the reader
2) Why common approaches fail
3) Practical solution (step-by-step)
4) Product-assisted workflow — how Cartozo.ai fits (honest, not hype)
5) CTA — clear next step""",
    "feature_presentation": """Sections to cover (in order):
1) Who the feature is for
2) Problem it solves
3) How it works (clear mechanics)
4) Before / after contrast
5) Limitations / when not to use
6) CTA""",
    "informational": """Sections to cover (in order):
1) Define the topic and who it matters to
2) Break into sub-questions (H2/H3)
3) Examples or scenarios
4) Common mistakes
5) Conclusion with takeaway""",
    "use_cases": """Sections to cover (in order):
1) Who the user / company is
2) The job-to-be-done
3) How the service was used (workflow)
4) Measurable outcome (even directional metrics)
5) CTA""",
    "comparison": """Sections to cover (in order):
1) X vs Y — honest framing
2) When to choose what
3) Trade-offs
4) Where Cartozo.ai fits (if relevant)
5) CTA""",
    "checklist_template": """Sections to cover (in order):
1) Short intro — why this checklist
2) Numbered checklist (high save/share value)
3) Optional template wording
4) Pitfalls
5) CTA""",
}

ARTICLE_TYPE_LABELS: Dict[str, str] = {
    "problem_solving": "Problem Solving",
    "feature_presentation": "Feature Presentation",
    "informational": "Informational",
    "use_cases": "Use Cases",
    "comparison": "Comparison",
    "checklist_template": "Checklist / template",
}

VALID_ARTICLE_TYPES = frozenset(ARTICLE_TYPE_LABELS.keys())

# Single "Primary goal" dropdown — system derives CTA, tone bias, score tweaks
PRIMARY_GOAL_LABELS: Dict[str, str] = {
    "organic_traffic": "Organic traffic",
    "qualified_traffic": "Qualified traffic",
    "product_awareness": "Product awareness",
    "signups_trials": "Signups / trials",
    "demo_requests": "Demo requests",
    "product_education": "Product education",
    "existing_users": "Existing users education",
    "retention": "Customer retention",
}
VALID_PRIMARY_GOALS = frozenset(PRIMARY_GOAL_LABELS.keys())

# Smart rule presets (checkboxes) → prompt lines
RULE_PRESET_MESSAGES: Dict[str, str] = {
    "preset_internal_links": "Use 2–4 internal links to related Cartozo blog posts where relevant.",
    "preset_mention_product": "Mention Cartozo.ai in the solution section where it fits naturally (no hype).",
    "preset_practical_tone": "Keep tone practical and specific; prefer steps and examples over adjectives.",
    "preset_no_hype": "Avoid hype, superlatives, and vague claims.",
    "preset_faq_if_relevant": "Add a short FAQ or objection-handling subsection if it fits the topic.",
    "preset_cta_end": "Place a clear CTA paragraph near the end (class writter-cta).",
}

# Default section headings for outline preview (user does not pick blueprint — type drives this)
OUTLINE_HEADINGS_BY_TYPE: Dict[str, List[str]] = {
    "problem_solving": [
        "What causes the issue",
        "How to diagnose it",
        "Step-by-step fix",
        "How to prevent recurrence",
        "Where automation / Cartozo helps",
    ],
    "feature_presentation": [
        "Who this is for",
        "Problem it solves",
        "How it works",
        "Before and after",
        "Limits and when not to use",
    ],
    "informational": [
        "What this topic means for merchants",
        "Key sub-questions",
        "Examples",
        "Common mistakes",
        "Takeaways",
    ],
    "use_cases": [
        "Context",
        "Job to be done",
        "Workflow",
        "Outcome",
        "Next step",
    ],
    "comparison": [
        "Framing",
        "When to choose A vs B",
        "Trade-offs",
        "Fit for Cartozo",
    ],
    "checklist_template": [
        "Why this checklist",
        "Checklist",
        "Tips",
        "Pitfalls",
    ],
}

# Settings keys (DB) — admin-defined extra instructions per article type
WRITTER_PROMPT_SETTING_BY_TYPE: Dict[str, str] = {
    "problem_solving": "writter_prompt_problem_solving",
    "feature_presentation": "writter_prompt_feature_presentation",
    "informational": "writter_prompt_informational",
    "use_cases": "writter_prompt_use_cases",
    "comparison": "writter_prompt_comparison",
    "checklist_template": "writter_prompt_checklist_template",
}

GENERATION_MODE_PARAMS: Dict[str, Dict[str, Any]] = {
    "fast": {"max_tokens": 2600, "temperature": 0.5},
    "standard": {"max_tokens": 4096, "temperature": 0.65},
    "authority": {"max_tokens": 4500, "temperature": 0.7},
}


def get_writter_type_prompt(settings: Dict[str, str], article_type: str) -> str:
    """Extra prompt fragment from Settings for this article type (may be empty)."""
    sk = WRITTER_PROMPT_SETTING_BY_TYPE.get(article_type or "")
    if not sk:
        return ""
    return (settings.get(sk) or "").strip()

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


def slugify(topic: str, keywords: str, max_len: int = 72) -> str:
    """SEO-friendly slug from topic + keywords (lowercase, hyphen-separated)."""
    parts = []
    for chunk in (topic or "", keywords or ""):
        for w in re.findall(r"[a-zA-Z0-9]+", chunk.lower()):
            if len(w) > 1 or w.isdigit():
                parts.append(w)
    if not parts:
        parts = ["article"]
    base = "-".join(parts[:12])[:max_len].strip("-")
    if not base:
        base = "article"
    return base


def ensure_unique_slug(check_exists, initial: str) -> str:
    """Append -2, -3 if slug taken. check_exists(slug) -> bool."""

    s = initial[:200]
    if not check_exists(s):
        return s
    n = 2
    while n < 1000:
        cand = f"{s[:180]}-{n}"
        if not check_exists(cand):
            return cand
        n += 1
    return f"{s[:160]}-{hashlib.sha256(s.encode()).hexdigest()[:8]}"


def rules_to_prompt_lines(rules: Optional[List[Dict[str, Any]]]) -> str:
    if not rules:
        return ""
    lines = []
    for r in rules:
        kind = (r.get("kind") or "").strip()
        if kind == "must_reference_url":
            lines.append(f"- Must reference / cite this URL: {r.get('url', '')}")
        elif kind == "must_include_keyword":
            lines.append(f"- Must include keyword: {r.get('value', '')}")
        elif kind == "tone":
            lines.append(f"- Tone: {r.get('value', 'professional')}")
        elif kind == "audience":
            lines.append(f"- Target audience: {r.get('value', 'e-commerce owners')}")
        elif kind in RULE_PRESET_MESSAGES:
            lines.append(f"- {RULE_PRESET_MESSAGES[kind]}")
        else:
            lines.append(f"- {json.dumps(r, ensure_ascii=False)}")
    return "\n".join(lines)


def build_visual_options(
    topic: str,
    keywords: str,
    *,
    seed: int = 0,
    layout: str = "horizontal",
) -> List[Dict[str, str]]:
    """
    Token-efficient: predefined SVG diagrams (no image API).
    `seed` rotates palettes/labels; `layout` is horizontal | vertical | compact.
    Returns 3 variants with label + html for preview/embed.
    """
    base = ((topic or "") + (keywords or "")).strip() or "feed"
    h0 = int(hashlib.md5(base.encode("utf-8")).hexdigest()[:8], 16)
    mix = (h0 + int(seed) * 7919) & 0xFFFFFFFF
    t_short = (topic or "Product flow")[:48]
    layout = (layout or "horizontal").lower().strip()
    if layout not in ("horizontal", "vertical", "compact"):
        layout = "horizontal"

    palettes = [
        [("#4F46E5", "#22D3EE"), ("#6366f1", "#a78bfa"), ("#0ea5e9", "#4ade80")],
        [("#7c3aed", "#38bdf8"), ("#db2777", "#f472b6"), ("#059669", "#34d399")],
        [("#1d4ed8", "#fbbf24"), ("#b45309", "#fcd34d"), ("#0e7490", "#67e8f9")],
        [("#4338ca", "#a5b4fc"), ("#be123c", "#fda4af"), ("#047857", "#6ee7b7")],
    ]
    pal = palettes[(mix + seed) % len(palettes)]

    label_sets = [
        ["Feed → optimization → channel", "Pipeline: ingest, enrich, publish", "Data flow overview"],
        ["Source → process → destination", "Sync, map, publish", "End-to-end flow"],
        ["Ingest → enrich → export", "Rules & AI layer", "Channel output"],
        ["Upload → optimize → live", "Quality gates", "Performance path"],
    ]
    labels = label_sets[(mix // 7 + seed) % len(label_sets)]

    def pick_colors(variant: int) -> Tuple[str, str]:
        i = (variant + seed + mix) % 3
        return pal[i][0], pal[i][1]

    def svg_horizontal(variant: int, uid: str) -> str:
        c1, c2 = pick_colors(variant)
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 140" role="img" aria-label="Diagram">
  <rect width="480" height="140" fill="transparent"/>
  <rect x="10" y="40" width="100" height="48" rx="8" fill="{c1}" opacity="0.9"/>
  <text x="60" y="70" text-anchor="middle" fill="white" font-size="11" font-family="system-ui,sans-serif">CSV / Feed</text>
  <path d="M120 64 L160 64" stroke="{c2}" stroke-width="3" marker-end="url(#{uid}m)"/>
  <rect x="170" y="40" width="110" height="48" rx="8" fill="{c2}" opacity="0.85"/>
  <text x="225" y="70" text-anchor="middle" fill="#0f172a" font-size="11" font-family="system-ui,sans-serif">Optimize</text>
  <path d="M290 64 L330 64" stroke="{c1}" stroke-width="3" marker-end="url(#{uid}m)"/>
  <rect x="340" y="40" width="120" height="48" rx="8" fill="{c1}" opacity="0.75"/>
  <text x="400" y="70" text-anchor="middle" fill="white" font-size="11" font-family="system-ui,sans-serif">Merchant</text>
  <defs><marker id="{uid}m" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><polygon points="0 0, 8 4, 0 8" fill="{c1}"/></marker></defs>
  <text x="240" y="120" text-anchor="middle" fill="#64748b" font-size="10" font-family="system-ui,sans-serif">{t_short}</text>
</svg>"""

    def svg_vertical(variant: int, uid: str) -> str:
        c1, c2 = pick_colors(variant)
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 200" role="img" aria-label="Diagram">
  <rect width="280" height="200" fill="transparent"/>
  <rect x="70" y="8" width="140" height="44" rx="8" fill="{c1}" opacity="0.92"/>
  <text x="140" y="36" text-anchor="middle" fill="white" font-size="11" font-family="system-ui,sans-serif">CSV / Feed</text>
  <path d="M140 52 L140 72" stroke="{c2}" stroke-width="3" marker-end="url(#{uid}mv)"/>
  <rect x="65" y="76" width="150" height="44" rx="8" fill="{c2}" opacity="0.88"/>
  <text x="140" y="104" text-anchor="middle" fill="#0f172a" font-size="11" font-family="system-ui,sans-serif">Optimize</text>
  <path d="M140 120 L140 140" stroke="{c1}" stroke-width="3" marker-end="url(#{uid}mv)"/>
  <rect x="60" y="144" width="160" height="44" rx="8" fill="{c1}" opacity="0.78"/>
  <text x="140" y="172" text-anchor="middle" fill="white" font-size="11" font-family="system-ui,sans-serif">Merchant</text>
  <defs><marker id="{uid}mv" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><polygon points="0 0, 8 4, 0 8" fill="{c1}"/></marker></defs>
</svg>"""

    def svg_compact(variant: int, uid: str) -> str:
        c1, c2 = pick_colors(variant)
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 100" role="img" aria-label="Diagram">
  <rect width="480" height="100" fill="transparent"/>
  <rect x="12" y="28" width="88" height="36" rx="6" fill="{c1}"/>
  <text x="56" y="50" text-anchor="middle" fill="white" font-size="10" font-family="system-ui,sans-serif">Feed</text>
  <text x="108" y="52" fill="#64748b" font-size="14">→</text>
  <rect x="124" y="28" width="96" height="36" rx="6" fill="{c2}"/>
  <text x="172" y="50" text-anchor="middle" fill="#0f172a" font-size="10" font-family="system-ui,sans-serif">AI</text>
  <text x="232" y="52" fill="#64748b" font-size="14">→</text>
  <rect x="248" y="28" width="100" height="36" rx="6" fill="{c1}" opacity="0.85"/>
  <text x="298" y="50" text-anchor="middle" fill="white" font-size="10" font-family="system-ui,sans-serif">GMC</text>
  <text x="240" y="84" text-anchor="middle" fill="#64748b" font-size="9" font-family="system-ui,sans-serif">{t_short[:40]}</text>
</svg>"""

    def svg_for_variant(i: int) -> str:
        uid = f"w{abs(seed)}_{layout}_{i}_{mix % 10000}"
        if layout == "vertical":
            return svg_vertical(i, uid)
        if layout == "compact":
            return svg_compact(i, uid)
        return svg_horizontal(i, uid)

    out = []
    for i in range(3):
        out.append(
            {
                "id": str(i),
                "label": labels[i % len(labels)],
                "html": f'<figure class="writter-visual" data-variant="{i}" data-layout="{layout}">{svg_for_variant(i)}</figure>',
            }
        )
    return out


def estimate_metrics_heuristic(keywords: str, topic: str) -> Dict[str, Any]:
    """Cheap estimates when LLM unavailable (display only)."""
    kws = [x.strip() for x in (keywords or "").split(",") if x.strip()]
    n = max(3, len(topic or "") // 8 + len(kws) * 400)
    imp = min(500_000, 8000 + n * 120)
    ctr = round(0.02 + (len(kws) % 5) * 0.003, 3)
    clicks = int(imp * ctr)
    conv = max(1, clicks // 80)
    return {
        "estimated_impressions": imp,
        "estimated_ctr": ctr,
        "estimated_clicks": clicks,
        "potential_conversions": conv,
    }


def score_article_opportunity(
    *,
    topic: str,
    keywords: str,
    article_type: str,
    audience: str = "",
    country_language: str = "",
    business_goal: str = "",
    internal_article_count: int = 0,
    primary_goal: str = "",
) -> Dict[str, Any]:
    """
    Heuristic opportunity scoring before generation (admin guidance, not a ranking guarantee).
    Minimal rules from product spec: problem-intent, product fit, internal links, long-tail, generic, weak tie-in.
    """
    t = (topic or "").strip()
    kw_line = (keywords or "").strip()
    kws = [x.strip().lower() for x in kw_line.split(",") if x.strip()]
    tl = t.lower()

    problem_markers = (
        "how to",
        "fix",
        "error",
        "why",
        "not working",
        "issue",
        "problem",
        "disapprov",
        "failed",
        "warning",
    )
    strong_problem = any(m in tl for m in problem_markers)

    product_markers = (
        "feed",
        "merchant",
        "gmc",
        "catalog",
        "sku",
        "product data",
        "csv",
        "shopping",
        "cartozo",
        "title",
        "description",
        "attribute",
    )
    product_blob = f"{tl} {kw_line.lower()}"
    product_fit = any(m in product_blob for m in product_markers)

    topic_words = [w for w in re.findall(r"[a-zA-Z]{3,}", t)]
    long_tail = len(topic_words) >= 4 or len(kws) >= 3

    generic_commodity = (len(topic_words) <= 2 and len(kws) == 0) or (
        len(topic_words) <= 3 and re.search(r"\b(best|top|ultimate|complete guide)\b", tl)
    )

    if article_type in ("informational", "checklist_template"):
        info_vs_commercial = 72
    elif article_type in ("feature_presentation", "comparison"):
        info_vs_commercial = 42
    else:
        info_vs_commercial = 55

    if any(x in tl for x in ("buy", "pricing", "discount", "coupon")):
        info_vs_commercial = max(20, info_vs_commercial - 25)

    if strong_problem:
        search_intent = "problem-solving / informational"
    elif article_type == "comparison":
        search_intent = "commercial comparison"
    elif "feature" in article_type:
        search_intent = "commercial evaluation"
    else:
        search_intent = "informational"

    angles: List[str] = []
    if strong_problem or "faq" in tl or "question" in tl:
        angles.append("FAQ / problem-led")
    if "vs" in tl or article_type == "comparison":
        angles.append("Comparison")
    if long_tail:
        angles.append("Long-tail / specific query")
    if article_type == "use_cases":
        angles.append("Use case / proof-led")
    if not angles:
        angles.append("SEO article")

    difficulty = 35
    if long_tail:
        difficulty += 8
    if generic_commodity:
        difficulty += 25
    if not product_fit:
        difficulty += 15
    difficulty = max(5, min(95, difficulty))

    value_score = 50
    breakdown: List[str] = []
    if strong_problem:
        value_score += 30
        breakdown.append("+30 strong problem-intent")
    if product_fit:
        value_score += 20
        breakdown.append("+20 product / feed context")
    if internal_article_count >= 2:
        value_score += 15
        breakdown.append("+15 internal articles available for linking")
    elif internal_article_count == 1:
        value_score += 8
        breakdown.append("+8 one internal article for linking")
    if long_tail:
        value_score += 15
        breakdown.append("+15 long-tail signals")
    if generic_commodity:
        value_score -= 25
        breakdown.append("-25 topic may be too generic / commodity")
    if not product_fit:
        value_score -= 30
        breakdown.append("-30 weak obvious tie-in to product domain")

    pg = (primary_goal or "").strip()
    if pg in ("signups_trials", "demo_requests"):
        value_score += 5
        breakdown.append("+5 primary goal: conversion / demo")
    elif pg in ("organic_traffic", "qualified_traffic"):
        value_score += 3
        breakdown.append("+3 primary goal: traffic / discovery")
    elif pg in ("product_awareness", "product_education"):
        value_score += 4
        breakdown.append("+4 primary goal: awareness / education")
    elif pg in ("existing_users", "retention"):
        value_score += 2
        breakdown.append("+2 primary goal: retention / existing users")

    value_score = max(0, min(100, value_score))

    return {
        "search_intent": search_intent,
        "informational_vs_commercial_score": info_vs_commercial,
        "suggested_angles": angles,
        "product_fit_likelihood": 80 if product_fit else 25,
        "estimated_difficulty": difficulty,
        "estimated_value_score": value_score,
        "score_breakdown": breakdown,
        "audience_note": (audience or "")[:500],
        "country_language": (country_language or "")[:200],
        "business_goal": (business_goal or "")[:500],
        "primary_goal": pg,
    }


def _goal_to_narrative(primary_goal: str) -> str:
    return PRIMARY_GOAL_LABELS.get(primary_goal, "Grow relevant organic traffic")


def infer_audience_heuristic(topic: str, keywords: str, article_type: str) -> str:
    """Cheap default audience from topic/keywords (no LLM)."""
    tl = f"{topic} {keywords}".lower()
    if any(x in tl for x in ("shopify", "woocommerce", "store")):
        return "E-commerce store operators (SMB), often on Shopify or similar"
    if any(x in tl for x in ("agency", "marketer", "seo")):
        return "Marketing / SEO specialists and growth teams"
    if "enterprise" in tl or "large" in tl:
        return "Mid-market and enterprise e-commerce teams"
    return "SMB e-commerce merchants and feed/catalog managers"


def cta_direction_for_goal(primary_goal: str) -> str:
    g = (primary_goal or "").strip()
    if g in ("signups_trials",):
        return "Strong trial CTA — link to /upload or signup; quantify time-to-value."
    if g in ("demo_requests",):
        return "Soft-gate demo CTA — contact or book; keep educational tone first."
    if g in ("product_awareness", "product_education"):
        return "Product-aware CTA — explain what Cartozo does + link to product areas."
    if g in ("existing_users", "retention"):
        return "Help existing users succeed — link to docs, in-app paths, or support."
    if g == "qualified_traffic":
        return "Qualified traffic — precise CTA for readers who already match ICP."
    return "Balanced SEO CTA — try the tool + one clear next step."


def recommend_visual_kind(topic: str, keywords: str, article_type: str) -> Dict[str, str]:
    """Suggest visual mode for UI (SVG flow vs comparison vs checklist)."""
    blob = f"{topic} {keywords}".lower()
    if article_type == "comparison" or " vs " in blob:
        return {"kind": "comparison", "label": "Comparison cards (A vs B)", "layout": "horizontal"}
    if article_type == "checklist_template" or "checklist" in blob:
        return {"kind": "checklist", "label": "Step / checklist strip", "layout": "compact"}
    if any(x in blob for x in ("dashboard", "metric", "kpi", "report")):
        return {"kind": "dashboard", "label": "Dashboard-style bars", "layout": "horizontal"}
    return {"kind": "process", "label": "Process diagram (flow)", "layout": "horizontal"}


def recommend_evidence_lines(topic: str, keywords: str, article_type: str) -> List[str]:
    """What proof types fit this article (shown in wizard before asking for URLs)."""
    tl = f"{topic} {keywords}".lower()
    lines = [
        "One concrete screenshot or UI reference (if applicable to the topic)",
        "One short numeric example or range (even if illustrative)",
        "One workflow or before/after diagram aligned with the visual section",
    ]
    if "disapprov" in tl or "error" in tl or "issue" in tl:
        lines.insert(0, "Screenshot or description of the GMC / feed error surface")
    if article_type in ("use_cases", "problem_solving"):
        lines.append("Optional: 2–3 sentence customer-style scenario")
    return lines


def build_outline_headings(article_type: str, topic: str) -> List[str]:
    base = list(OUTLINE_HEADINGS_BY_TYPE.get(article_type, OUTLINE_HEADINGS_BY_TYPE["informational"]))
    short = (topic or "").strip()
    if short:
        base[0] = f"{base[0]} ({short[:70]})"
    return base


def build_article_plan(
    *,
    topic: str,
    keywords: str,
    article_type: str,
    primary_goal: str,
    audience_override: str = "",
    country_language_override: str = "",
    business_goal_override: str = "",
    settings_defaults: Dict[str, str],
    internal_article_count: int,
    internal_link_suggestions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Full smart plan: inferred audience, defaults, outline, proof list, visual hint, CTA direction, opportunity score.
    """
    pg = (primary_goal or "organic_traffic").strip()
    if pg not in VALID_PRIMARY_GOALS:
        pg = "organic_traffic"

    aud = (audience_override or "").strip() or settings_defaults.get("writter_default_audience") or ""
    if not aud:
        aud = infer_audience_heuristic(topic, keywords, article_type)

    cl = (country_language_override or "").strip() or settings_defaults.get("writter_default_country_language") or ""
    if not cl:
        cl = "US / English"

    bg = (business_goal_override or "").strip() or _goal_to_narrative(pg)

    opp = score_article_opportunity(
        topic=topic,
        keywords=keywords,
        article_type=article_type,
        audience=aud,
        country_language=cl,
        business_goal=bg,
        internal_article_count=internal_article_count,
        primary_goal=pg,
    )

    outline = build_outline_headings(article_type, topic)
    evidence_lines = recommend_evidence_lines(topic, keywords, article_type)
    visual_rec = recommend_visual_kind(topic, keywords, article_type)
    cta_dir = cta_direction_for_goal(pg)

    checklist = [
        {"id": "screenshots", "label": "Use product / UI screenshots", "default_on": True},
        {"id": "diagram", "label": "Include a workflow diagram", "default_on": True},
        {"id": "metrics", "label": "Add one numeric example or metric", "default_on": True},
        {"id": "use_case", "label": "Add a short use-case scenario", "default_on": False},
    ]

    return {
        "primary_goal": pg,
        "primary_goal_label": PRIMARY_GOAL_LABELS.get(pg, pg),
        "inferred_audience": aud,
        "country_language": cl,
        "business_goal_interpretation": bg,
        "search_intent_summary": opp.get("search_intent"),
        "blueprint_outline": outline,
        "recommended_visual": visual_rec,
        "cta_direction": cta_dir,
        "recommended_proof": evidence_lines,
        "proof_checklist": checklist,
        "opportunity": opp,
        "internal_link_suggestions": internal_link_suggestions[:8],
        "intent_notes": (
            f"Strong problem-solving intent with {PRIMARY_GOAL_LABELS.get(pg, 'growth')} focus."
            if "problem" in (topic or "").lower()
            else f"Content aligned with {PRIMARY_GOAL_LABELS.get(pg, 'growth')} — keep proof concrete."
        ),
    }


def evidence_to_prompt_fragment(evidence: Optional[Dict[str, Any]]) -> str:
    """Turn admin evidence payload into prompt instructions (mandatory proof layer)."""
    if not evidence or not isinstance(evidence, dict):
        return ""
    lines: List[str] = []
    plan_lines = evidence.get("recommended_proof_plan")
    if isinstance(plan_lines, list) and plan_lines:
        lines.append("Recommended proof types for this topic (include at least one concrete block):")
        for s in plan_lines[:12]:
            if s:
                lines.append(f"  - {str(s)[:500]}")

    use_sh = bool(evidence.get("use_product_screenshots"))
    add_dia = bool(evidence.get("add_diagram"))
    add_met = bool(evidence.get("add_metrics"))
    add_uc = bool(evidence.get("add_use_case"))

    urls = evidence.get("screenshot_urls") or []
    if isinstance(urls, list) and urls:
        lines.append("Screenshots / uploads (describe and reference in copy; use <figure> and meaningful alt text):")
        for u in urls[:12]:
            if u:
                lines.append(f"  - {str(u)[:500]}")
    elif use_sh:
        lines.append(
            "Include a plausible product screenshot callout (describe a realistic feed/Merchant UI area if no URL is given)."
        )

    screens = evidence.get("product_screen_ids") or []
    if isinstance(screens, list) and screens:
        lines.append("Product UI areas to reference: " + ", ".join(str(x) for x in screens[:20]))

    m = (evidence.get("metrics_manual") or "").strip()
    if m:
        lines.append("Metrics / numbers to include (use exactly or paraphrase clearly): " + m[:2000])
    elif add_met:
        lines.append("Include at least one numeric example, percentage, or range (even if illustrative).")

    scen = (evidence.get("customer_scenario") or "").strip()
    if scen:
        lines.append("Customer scenario to ground the article: " + scen[:2000])
    elif add_uc:
        lines.append("Include a short 2–3 sentence customer-style scenario.")

    q = (evidence.get("quote") or "").strip()
    if q:
        lines.append("Quote / testimonial to attribute: " + q[:1500])
    d = (evidence.get("diagram_note") or "").strip()
    if d:
        lines.append("Diagram / workflow note (align narrative with this): " + d[:1500])
    elif add_dia:
        lines.append("Include a clear workflow or before/after diagram (can use the existing figure/visual section).")

    if not lines:
        return ""
    return "EVIDENCE / PROOF (must appear in the article — at least one concrete block: example, metric, scenario, quote, or diagram callout):\n" + "\n".join(lines)


def suggest_internal_link_placements(
    topic: str,
    keywords: str,
    siblings: List[Dict[str, str]],
    *,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Rank published articles by simple token overlap; suggest anchor text from title."""
    blob = f"{topic} {keywords}".lower()
    words = {w for w in re.findall(r"[a-z]{3,}", blob) if len(w) > 2}
    out: List[Dict[str, Any]] = []
    for s in siblings:
        title = (s.get("title") or "").strip()
        slug = (s.get("slug") or "").strip()
        if not title or not slug:
            continue
        tw = {w for w in re.findall(r"[a-z]{3,}", title.lower()) if len(w) > 2}
        overlap = len(words & tw)
        if overlap < 1:
            continue
        anchor = title[:120]
        out.append(
            {
                "slug": slug,
                "title": title,
                "anchor_suggestion": anchor,
                "relevance": overlap,
            }
        )
    out.sort(key=lambda x: -int(x.get("relevance") or 0))
    return out[:limit]


def run_seo_quality_audit(
    *,
    content_html: str,
    title: str,
    meta_description: str,
    slug: str,
    keywords: str,
    h1: str = "",
) -> Dict[str, Any]:
    """
    Pre-publish SEO QA (heuristic). Returns checks, sub-scores, verdict.
    """
    html = content_html or ""
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = re.sub(r"\s+", " ", plain).strip()
    intro = plain[:420].lower()
    title_l = (title or "").lower()
    h1_l = (h1 or "").lower()
    slug_l = (slug or "").lower()
    kws = [x.strip().lower() for x in (keywords or "").split(",") if len(x.strip()) > 2]

    h1_in_body = len(re.findall(r"<h1\b", html, re.I))
    # Public /blog/{slug} renders title as H1 outside content_html; treat provided h1 as page H1.
    if h1_in_body == 0 and (h1 or "").strip():
        h1_count = 1
    else:
        h1_count = h1_in_body
    checks: List[Dict[str, Any]] = []

    def add(cid: str, ok: bool, detail: str):
        checks.append({"id": cid, "ok": ok, "detail": detail})

    add("h1_single", h1_count == 1, f"H1 count: {h1_count} (body + template; want exactly one page H1)")

    kw_in_title = any(k in title_l for k in kws) if kws else True
    kw_in_h1 = any(k in h1_l for k in kws) if kws else True
    kw_intro = any(k in intro for k in kws) if kws else True
    kw_slug = any(k.replace(" ", "-") in slug_l or k in slug_l for k in kws) if kws else True
    add("keyword_title", kw_in_title, "Primary keyword in title" if kws else "No keywords to check")
    add("keyword_h1", kw_in_h1, "Primary keyword in H1" if kws else "—")
    add("keyword_intro", kw_intro, "Keyword in intro" if kws else "—")
    add("keyword_slug", kw_slug, "Keyword reflected in slug" if kws else "—")

    md = (meta_description or "").strip()
    md_ok = 120 <= len(md) <= 200
    add("meta_length", md_ok, f"Meta description length {len(md)} chars (aim ~150–165)")

    internal_n = len(re.findall(r'href=["\']/blog/', html, re.I))
    add("internal_links", internal_n >= 2, f"Internal /blog/ links: {internal_n} (aim 2+)")

    ext = 0
    for m in re.finditer(r"""href\s*=\s*["'](https?://[^"']+)""", html, re.I):
        u = m.group(1).lower()
        if "/blog/" in u or "cartozo.ai" in u:
            continue
        ext += 1
    add("external_refs", ext >= 1 or internal_n >= 3, f"External reference links: {ext} (optional; add when citing sources)")

    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    alts = [x for x in imgs if re.search(r'\balt=["\'][^"\']{4,}', x, re.I)]
    add("img_alt", len(imgs) == 0 or len(alts) >= len(imgs), f"Images with descriptive alt: {len(alts)}/{len(imgs)}")

    kw_density = 0.0
    if kws and plain:
        hits = sum(plain.lower().count(k) for k in kws)
        wc = max(1, len(re.findall(r"\w+", plain)))
        kw_density = hits / wc
    spam = kw_density > 0.12 and len(kws) >= 2
    add("keyword_spam", not spam, f"Keyword density heuristic ok ({kw_density:.3f})")

    has_cta = bool(re.search(r"class\s*=\s*[\"'][^\"']*writter-cta", html, re.I))
    add("cta", has_cta, "CTA block (class writter-cta)")

    has_summary = bool(re.search(r"<h2[^>]*>\s*(summary|takeaways|key points)", html, re.I))
    add("summary_block", has_summary or len(re.findall(r"<h2\b", html, re.I)) >= 3, "Summary or multiple H2 sections")

    paras = re.split(r"</p\s*>", html, flags=re.I)
    short_generic = sum(1 for p in paras if len(re.sub(r"<[^>]+>", "", p).strip()) < 40)
    add("thin_paragraphs", short_generic <= max(2, len(paras) // 5), f"Very short paragraphs: {short_generic}")

    # Sub-scores 0–100
    seo = 55
    if h1_count == 1:
        seo += 10
    if kw_in_title and kw_in_h1:
        seo += 8
    if md_ok:
        seo += 8
    if internal_n >= 2:
        seo += 10
    if not spam:
        seo += 6
    seo = max(0, min(100, seo))

    words = len(re.findall(r"\w+", plain))
    sents = max(1, len(re.split(r"[.!?]+", plain)))
    avg_len = words / sents
    readability = 72
    if 12 <= avg_len <= 22:
        readability += 12
    elif avg_len > 28:
        readability -= 15
    if words >= 500:
        readability += 8
    readability = max(0, min(100, readability))

    originality = 62
    if words >= 700:
        originality += 12
    if len(re.findall(r"<h2\b", html, re.I)) >= 4:
        originality += 10
    originality = max(0, min(100, originality))

    evidence = 40
    if re.search(r"\b\d{1,3}[.,]?\d*\s*%|\b\d{2,}\b", plain):
        evidence += 15
    if re.search(r"(for example|case study|scenario|screenshot|figure)", plain, re.I):
        evidence += 20
    if re.search(r"<blockquote\b|faq", plain, re.I):
        evidence += 12
    evidence = max(0, min(100, evidence))

    product_relevance = 58
    if re.search(r"(feed|merchant|catalog|sku|csv|cartozo)", plain, re.I):
        product_relevance += 25
    product_relevance = max(0, min(100, product_relevance))

    overall = int(round((seo + readability + originality + evidence + product_relevance) / 5))

    if overall >= 78 and seo >= 70:
        verdict = "Good to publish"
    elif overall < 52 or seo < 48:
        verdict = "Draft only"
    else:
        verdict = "Needs human edit"

    schema_hints: List[str] = ["Article"]
    if re.search(r"faq|frequently asked", plain, re.I):
        schema_hints.append("FAQPage (only if FAQ content is real and visible)")
    schema_hints.append("BreadcrumbList for /blog/…")
    if product_relevance >= 70:
        schema_hints.append("Organization / Product (if honestly describing the product)")

    return {
        "checks": checks,
        "scores": {
            "seo": seo,
            "readability": readability,
            "originality": originality,
            "evidence": evidence,
            "product_relevance": product_relevance,
            "overall": overall,
        },
        "verdict": verdict,
        "schema_recommendations": schema_hints,
    }


def publish_blocked_by_quality(metrics_json: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return error message if publish should be blocked (anti-thin safeguards)."""
    if not metrics_json:
        return None
    seo = metrics_json.get("seo_qa") if isinstance(metrics_json, dict) else None
    if not isinstance(seo, dict):
        return None
    verdict = (seo.get("verdict") or "").strip()
    overall = (seo.get("scores") or {}).get("overall")
    if verdict == "Draft only":
        return "Publish blocked: SEO QA verdict is “Draft only”. Edit content or run regeneration, then review checks."
    if isinstance(overall, int) and overall < 42:
        return f"Publish blocked: overall quality score is {overall}/100 (minimum 42 for auto-publish)."
    return None


def _parse_json_obj(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    # strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def generate_article_with_ai(
    *,
    api_key: str,
    article_type: str,
    topic: str,
    keywords: str,
    rules: Optional[List[Dict[str, Any]]],
    internal_context: List[Dict[str, str]],
    visual_label: str,
    type_prompt_extra: str = "",
    generation_mode: str = "standard",
    audience: str = "",
    country_language: str = "",
    business_goal: str = "",
    evidence: Optional[Dict[str, Any]] = None,
    opportunity_plan: Optional[Dict[str, Any]] = None,
    internal_link_suggestions: Optional[List[Dict[str, Any]]] = None,
    outline_sections: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Returns (payload, metrics_dict).
    payload keys: seo_title, meta_description, h1, content_html, structure_outline, cta_html, internal_links
    """
    structure = STRUCTURE_BY_TYPE.get(article_type, STRUCTURE_BY_TYPE["informational"])
    blueprint = BLUEPRINT_BY_TYPE.get(article_type, BLUEPRINT_BY_TYPE["informational"])
    if outline_sections:
        blueprint = "Section flow (use these as the core H2 structure; adapt wording to the topic):\n" + "\n".join(
            f"- {x}" for x in outline_sections if (x or "").strip()
        )
    rules_block = rules_to_prompt_lines(rules)
    others = "\n".join(f'- Related article: "{x["title"]}" → /blog/{x["slug"]}' for x in internal_context[:15])

    sug = internal_link_suggestions or []
    sug_lines = "\n".join(
        f'- Prefer linking to "{s.get("title")}" → /blog/{s.get("slug")} (suggested anchor: {s.get("anchor_suggestion", "")[:100]})'
        for s in sug[:8]
        if s.get("slug")
    )

    type_extra_block = ""
    if (type_prompt_extra or "").strip():
        type_extra_block = f"""

--- Additional instructions for this article type (from admin Settings — must be followed together with topic, keywords, rules, and visual below) ---
{type_prompt_extra.strip()}
--- End type-specific instructions ---
"""

    opp_block = ""
    if opportunity_plan and isinstance(opportunity_plan, dict):
        cta_hint = (opportunity_plan.get("cta_direction") or "").strip()
        cta_line = f"\n- CTA direction: {cta_hint}" if cta_hint else ""
        opp_block = f"""
Opportunity analysis (honor intent; do not contradict without reason):
- Search intent: {opportunity_plan.get("search_intent", "")}
- Info vs commercial (0–100, higher = more informational): {opportunity_plan.get("informational_vs_commercial_score", "")}
- Suggested angles: {", ".join(opportunity_plan.get("suggested_angles") or [])}
- Product fit likelihood: {opportunity_plan.get("product_fit_likelihood", "")}
- Estimated difficulty (higher = harder): {opportunity_plan.get("estimated_difficulty", "")}
- Estimated value score: {opportunity_plan.get("estimated_value_score", "")}{cta_line}
"""

    ctx_block = ""
    if (audience or "").strip() or (country_language or "").strip() or (business_goal or "").strip():
        ctx_block = f"""
Audience: {audience or "(not specified)"}
Country / language: {country_language or "(default: English)"}
Business goal: {business_goal or "(not specified)"}
"""

    evidence_block = evidence_to_prompt_fragment(evidence)
    if not evidence_block.strip():
        evidence_block = (
            "EVIDENCE / PROOF: No evidence was provided in the form. "
            "Still include at least one concrete block: a numeric example, a mini before/after, a short FAQ addressing objections, "
            "or a labeled figure description (not generic filler)."
        )

    mode = GENERATION_MODE_PARAMS.get(generation_mode, GENERATION_MODE_PARAMS["standard"])
    max_tokens = int(mode.get("max_tokens", 4096))
    temperature = float(mode.get("temperature", 0.65))

    mode_extra = ""
    if generation_mode == "fast":
        mode_extra = "Mode: FAST — shorter sections, fewer words, still structured and on-topic."
    elif generation_mode == "authority":
        mode_extra = (
            "Mode: AUTHORITY — longer, denser sections; include FAQ or objection handling where natural; "
            "strong internal links; clear expert tone. Suggest JSON-LD types in the metrics JSON field schema_hints only as hints."
        )
    else:
        mode_extra = "Mode: STANDARD — balanced SEO article length and structure."

    system = """You are an expert SEO content writer for Cartozo.ai (e-commerce product feed optimization).
Write in English unless the topic clearly requires another language.
Return ONLY valid JSON, no markdown. All HTML must be safe semantic tags: section, h2, h3, p, ul, li, strong, a (href only relative /blog/... or https://).
You MUST respect the user's topic, keywords, editor rules, evidence, and visual description — never ignore them in favor of generic filler."""

    user = f"""Create one blog article.

Article type: {article_type}
Compact structure: {structure}
Content blueprint (follow sections in order; adapt headings to the topic):
{blueprint}

Topic: {topic}
Keywords (use naturally): {keywords}
{ctx_block}
{opp_block}
Editor rules:
{rules_block or "- (none)"}

Related posts for internal linking (use 2–4 links where relevant):
{others or "- (none yet)"}

Prioritized internal link suggestions (use these slugs first when relevant):
{sug_lines or "- (no suggestions)"}

Visual placed in article (describe near top; align copy with this diagram): {visual_label}
{type_extra_block}

{evidence_block}

{mode_extra}

JSON schema:
{{
  "seo_title": "max 120 chars",
  "meta_description": "150-160 chars, compelling",
  "h1": "main heading",
  "structure_outline": [{{"level": 2, "title": "..."}}, ...],
  "content_html": "full HTML body (no html/head/body wrapper). Include sections matching the structure. Add a clear CTA paragraph with class=writter-cta linking to / or /upload.",
  "cta_html": "optional short CTA block HTML",
  "metrics": {{
    "estimated_impressions": <integer>,
    "estimated_ctr": <float 0-1>,
    "estimated_clicks": <integer>,
    "potential_conversions": <integer>,
    "schema_hints": ["Article", "..."]
  }}
}}

The "metrics" object must be analytically reasoned from: the topic and search intent, keyword list (comma-separated), implied niche/competition, and article type — not arbitrary round numbers. Briefly justify internally; output numbers only in JSON."""

    metrics: Dict[str, Any] = estimate_metrics_heuristic(keywords, topic)
    if not HAS_OPENAI or not api_key:
        return _fallback_article(topic, keywords, blueprint, metrics), metrics

    client = openai.OpenAI(api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = _parse_json_obj(raw) or {}
    except Exception:
        return _fallback_article(topic, keywords, blueprint, metrics), metrics

    if not data.get("content_html"):
        return _fallback_article(topic, keywords, blueprint, metrics), metrics

    m = data.get("metrics") or {}
    if isinstance(m, dict):
        metrics = {
            "estimated_impressions": int(m.get("estimated_impressions", metrics["estimated_impressions"])),
            "estimated_ctr": float(m.get("estimated_ctr", metrics["estimated_ctr"])),
            "estimated_clicks": int(m.get("estimated_clicks", metrics["estimated_clicks"])),
            "potential_conversions": int(m.get("potential_conversions", metrics["potential_conversions"])),
        }
        if isinstance(m.get("schema_hints"), list):
            metrics["schema_hints"] = m["schema_hints"][:12]

    payload = {
        "seo_title": (data.get("seo_title") or topic)[:200],
        "meta_description": (data.get("meta_description") or "")[:320],
        "h1": data.get("h1") or topic,
        "structure_outline": data.get("structure_outline"),
        "content_html": data.get("content_html") or "",
        "cta_html": data.get("cta_html") or "",
        "internal_links": [],
    }
    return payload, metrics


def _fallback_article(topic: str, keywords: str, blueprint: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    kws = keywords or "optimization"
    body = f"""<section><h2>Overview</h2><p>This article covers <strong>{topic}</strong> for teams working on product feeds and e-commerce SEO. Keywords: {kws}.</p></section>
<section><h2>Structure</h2><p>We follow this blueprint: {blueprint[:400]}.</p></section>
<section><h2>Key takeaways</h2><ul><li>Clarify the problem and context.</li><li>Apply structured optimization to titles and descriptions.</li><li>Measure results in Merchant Center.</li></ul></section>
<section class="writter-cta"><p><a href="/upload">Try Cartozo.ai</a> — optimize your feed with AI.</p></section>"""
    return {
        "seo_title": (topic[:110] + " | Cartozo.ai")[:120],
        "meta_description": f"Learn about {topic[:120]}. Practical guidance for e-commerce feeds.",
        "h1": topic[:200],
        "structure_outline": [{"level": 2, "title": "Overview"}, {"level": 2, "title": "Key takeaways"}],
        "content_html": body,
        "cta_html": "",
        "internal_links": [],
    }


def estimate_article_quality(
    *,
    title: str,
    meta_description: str,
    content_html: str,
    keywords: str,
    internal_links_count: int = 0,
) -> Dict[str, Any]:
    """
    Heuristic 0–100 quality score for admin analytics (not a search ranking guarantee).
    """
    score = 38
    hints: List[str] = []
    t = (title or "").strip()
    m = (meta_description or "").strip()
    plain = re.sub(r"<[^>]+>", " ", content_html or "")
    plain = re.sub(r"\s+", " ", plain).strip()
    words = len(re.findall(r"\w+", plain))
    h2 = len(re.findall(r"<h2\b", content_html or "", re.I))
    h3 = len(re.findall(r"<h3\b", content_html or "", re.I))
    has_cta = bool(re.search(r"class\s*=\s*[\"'][^\"']*writter-cta", content_html or "", re.I))
    kws = [x.strip().lower() for x in (keywords or "").split(",") if x.strip()]
    plain_l = plain.lower()
    kw_hits = sum(1 for k in kws if k and k in plain_l)

    if 38 <= len(t) <= 72:
        score += 14
        hints.append("Title length in a good SEO range")
    elif len(t) > 0:
        score += 5
        hints.append("Consider shortening or lengthening the title (≈40–70 chars)")

    if 145 <= len(m) <= 168:
        score += 14
        hints.append("Meta description length fits typical SERP snippets")
    elif len(m) > 0:
        score += 4
        hints.append("Aim for ~150–160 characters in meta description")

    if words >= 450:
        score += 12
        hints.append("Substantial body copy")
    elif words >= 250:
        score += 6
        hints.append("Add depth (target 500+ words for competitive topics)")
    else:
        hints.append("Content may be thin — expand with examples and steps")

    if h2 >= 2:
        score += 8
        hints.append("Clear section headings (H2)")
    if h3 >= 1:
        score += 4

    if internal_links_count >= 2:
        score += 10
        hints.append("Internal links to related posts")
    elif internal_links_count == 1:
        score += 4

    if kw_hits >= min(2, len(kws)) and kws:
        score += 8
        hints.append("Keywords appear in the body")
    elif kws:
        score += 2
        hints.append("Weave target keywords more naturally")

    if has_cta:
        score += 6
        hints.append("CTA block present")

    score = max(0, min(100, score))

    if score >= 80:
        label = "Strong"
        color = "#4ade80"
    elif score >= 62:
        label = "Good"
        color = "#22D3EE"
    elif score >= 45:
        label = "Fair"
        color = "#fbbf24"
    else:
        label = "Needs work"
        color = "#f87171"

    return {
        "score": score,
        "label": label,
        "color": color,
        "word_count": words,
        "h2_count": h2,
        "h3_count": h3,
        "keyword_coverage": kw_hits,
        "hints": hints[:6],
    }


def generate_admin_blog_insights(
    api_key: str,
    *,
    title: str,
    meta_description: str,
    topic: str,
    keywords: str,
    article_type: str,
    content_html: str,
    metrics_json: Dict[str, Any],
    views: int,
    sessions: int,
    avg_time_s: float,
    avg_scroll: float,
    cta_clicks: int,
    internal_links_n: int,
) -> Optional[Dict[str, Any]]:
    """
    OpenAI-driven analytics narrative for the admin blog sidebar.
    Returns dict with quality_score, quality_label, quality_color, summary, engagement_analysis,
    projections_analysis, recommendations (list), or None if unavailable.
    """
    if not HAS_OPENAI or not api_key:
        return None

    plain = re.sub(r"<[^>]+>", " ", content_html or "")
    plain = re.sub(r"\s+", " ", plain).strip()[:12000]
    m = metrics_json or {}
    user = f"""Analyze this published blog article for an admin dashboard.

Article type: {article_type}
Title: {title}
Meta description: {meta_description}
Topic (as submitted): {topic}
Keywords (comma-separated): {keywords}

Stored projection metrics (from generation): {json.dumps(m, ensure_ascii=False)}

Live analytics (aggregated):
- views (total): {views}
- analytics sessions (beacons): {sessions}
- avg time on page (seconds): {avg_time_s:.2f}
- avg scroll depth (%): {avg_scroll:.1f}
- CTA clicks: {cta_clicks}
- internal links count: {internal_links_n}

Article body (plain text, truncated):
{plain}

Return ONLY valid JSON:
{{
  "quality_score": <integer 0-100>,
  "quality_label": "<short label e.g. Strong / Good / Fair / Needs work>",
  "quality_color": "<hex color for UI e.g. #4ade80>",
  "summary": "<2-4 sentences: overall SEO/content assessment>",
  "engagement_analysis": "<2-4 sentences interpreting the live metrics vs expectations>",
  "projections_analysis": "<2-4 sentences: are the stored projection metrics plausible given topic/keywords; suggest if they should be refreshed>",
  "recommendations": ["<actionable item 1>", "<item 2>", "<item 3>"],
  "hints": ["<short tip 1>", "<short tip 2>"]
}}"""

    try:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an SEO and content analytics assistant. Be specific and analytical. "
                    "Use only the data provided. Do not invent traffic numbers beyond what is given.",
                },
                {"role": "user", "content": user},
            ],
            max_tokens=1800,
            temperature=0.35,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = _parse_json_obj(raw) or {}
    except Exception:
        return None

    if not data:
        return None
    try:
        qs = int(data.get("quality_score", 0))
        qs = max(0, min(100, qs))
    except (TypeError, ValueError):
        return None

    out: Dict[str, Any] = {
        "quality_score": qs,
        "quality_label": str(data.get("quality_label") or "—")[:80],
        "quality_color": str(data.get("quality_color") or "#94a3b8")[:32],
        "summary": str(data.get("summary") or "")[:2000],
        "engagement_analysis": str(data.get("engagement_analysis") or "")[:2000],
        "projections_analysis": str(data.get("projections_analysis") or "")[:2000],
        "recommendations": data.get("recommendations") if isinstance(data.get("recommendations"), list) else [],
        "hints": data.get("hints") if isinstance(data.get("hints"), list) else [],
    }
    return out


def inject_internal_links(
    html: str,
    siblings: List[Dict[str, str]],
    max_links: int = 5,
) -> Tuple[str, List[Dict[str, str]]]:
    """
    Add links to other articles where phrases match titles (simple heuristic).
    siblings: [{"slug","title"}, ...]
    """
    if not html or not siblings:
        return html, []

    used: List[Dict[str, str]] = []
    out = html
    n = 0
    for art in siblings:
        if n >= max_links:
            break
        title = (art.get("title") or "").strip()
        slug = (art.get("slug") or "").strip()
        if len(title) < 6:
            continue
        if title.lower() in out.lower():
            continue
        # first occurrence of a significant word from title (not inside HTML tags; no variable-width lookbehind — not supported by Python re)
        words = [w for w in re.findall(r"[A-Za-z]{4,}", title)][:3]
        for w in words:
            pat = re.compile(rf"\b({re.escape(w)})\b", re.IGNORECASE)
            replaced = False
            for m in pat.finditer(out):
                start = m.start()
                before = out[:start]
                last_lt = before.rfind("<")
                last_gt = before.rfind(">")
                if last_lt > last_gt:
                    continue
                out = out[: m.start()] + f'<a href="/blog/{slug}">{m.group(1)}</a>' + out[m.end() :]
                used.append({"slug": slug, "title": title, "anchor": w})
                n += 1
                replaced = True
                break
            if replaced:
                break
    return out, used


# ─── Cheap visual template router (no LLM image — structured HTML/CSS) ─────────

CHEAP_VISUAL_LABELS: Dict[str, str] = {
    "timeline": "Timeline",
    "comparison_cards": "Comparison cards",
    "feature_steps": "Feature steps",
    "problem_solution": "Problem / solution",
    "dashboard_mock": "Dashboard mock",
    "process_diagram": "Process diagram",
}


def classify_cheap_visual_template(description: str, topic: str) -> str:
    """Map free-text visual intent to a template key (keyword + heuristic)."""
    blob = f"{description or ''} {topic or ''}".lower()
    if any(x in blob for x in ("timeline", "chronolog", "roadmap", "phase")):
        return "timeline"
    if any(x in blob for x in (" vs ", "versus", "compare", "x or y", "which is better")):
        return "comparison_cards"
    if any(x in blob for x in ("step", "workflow", "pipeline", "stage")):
        return "feature_steps"
    if any(x in blob for x in ("problem", "pain", "solution", "before", "after")):
        return "problem_solution"
    if any(x in blob for x in ("dashboard", "metric", "kpi", "chart")):
        return "dashboard_mock"
    if any(x in blob for x in ("process", "diagram", "flow", "loop")):
        return "process_diagram"
    return "feature_steps"


def render_cheap_visual_html(template: str, topic: str, keywords: str, seed: int = 0) -> str:
    """Render a token-cheap HTML figure for embedding (no image API)."""

    def html_escape(s: str) -> str:
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    kw = (keywords or "").split(",")[0].strip()[:60] if keywords else ""
    h = int(hashlib.md5(f"{template}:{topic}:{keywords}:{seed}".encode()).hexdigest()[:8], 16)
    pal = ["#4F46E5", "#22D3EE", "#a78bfa", "#34d399", "#fbbf24"]
    c1, c2, c3 = pal[h % len(pal)], pal[(h + 2) % len(pal)], pal[(h + 4) % len(pal)]

    t = html_escape((topic or "Topic")[:100])
    kw_esc = html_escape(kw)

    if template == "timeline":
        inner = f"""<div class="writter-cheap-tpl writter-cheap-timeline" role="img" aria-label="Timeline diagram">
  <div class="wct-row"><span class="wct-dot" style="background:{c1}"></span><div><strong>Source</strong><p class="wct-muted">{kw_esc or "Feed ingest"}</p></div></div>
  <div class="wct-line" style="background:linear-gradient({c1},{c2})"></div>
  <div class="wct-row"><span class="wct-dot" style="background:{c2}"></span><div><strong>Optimize</strong><p class="wct-muted">{t}</p></div></div>
  <div class="wct-line" style="background:linear-gradient({c2},{c3})"></div>
  <div class="wct-row"><span class="wct-dot" style="background:{c3}"></span><div><strong>Publish</strong><p class="wct-muted">Channels</p></div></div>
</div>"""
    elif template == "comparison_cards":
        inner = f"""<div class="writter-cheap-tpl writter-cheap-compare" role="img" aria-label="Comparison">
  <div class="wct-card" style="border-color:{c1}"><h4 class="wct-h">Option A</h4><p>Manual spreadsheets</p></div>
  <div class="wct-card" style="border-color:{c2}"><h4 class="wct-h">Option B</h4><p>{t}</p></div>
</div>"""
    elif template == "problem_solution":
        inner = f"""<div class="writter-cheap-tpl writter-cheap-ps" role="img" aria-label="Problem solution">
  <div class="wct-ps p" style="border-left:4px solid {c1}"><strong>Problem</strong><p>Broken titles, policy issues, thin descriptions.</p></div>
  <div class="wct-ps s" style="border-left:4px solid {c2}"><strong>Solution</strong><p>{t} — structured enrichment and validation.</p></div>
</div>"""
    elif template == "dashboard_mock":
        inner = f"""<div class="writter-cheap-tpl writter-cheap-dash" role="img" aria-label="Dashboard mock">
  <div class="wct-bar" style="height:40px;background:{c1};width:72%;border-radius:6px;"></div>
  <div class="wct-bar" style="height:28px;background:{c2};width:55%;margin-top:8px;border-radius:6px;"></div>
  <p class="wct-muted" style="margin-top:10px;">{t}</p>
</div>"""
    elif template == "process_diagram":
        inner = f"""<div class="writter-cheap-tpl writter-cheap-process" role="img" aria-label="Process">
  <span class="wct-pill" style="background:{c1}">Ingest</span><span class="wct-arrow">→</span>
  <span class="wct-pill" style="background:{c2}">Rules</span><span class="wct-arrow">→</span>
  <span class="wct-pill" style="background:{c3}">Export</span>
</div>"""
    else:  # feature_steps
        inner = f"""<div class="writter-cheap-tpl writter-cheap-steps" role="img" aria-label="Steps">
  <ol class="wct-ol">
    <li style="border-left:3px solid {c1}"><strong>Upload</strong> your feed</li>
    <li style="border-left:3px solid {c2}"><strong>Enrich</strong> {kw_esc or "titles & attributes"}</li>
    <li style="border-left:3px solid {c3}"><strong>Sync</strong> to Merchant Center</li>
  </ol>
</div>"""

    return f"""<figure class="writter-cheap-visual" data-template="{html_escape(template)}">
<style>
.writter-cheap-visual {{ margin:16px 0; padding:16px; border-radius:12px; background:rgba(79,70,229,.06); border:1px solid rgba(255,255,255,.1); }}
[data-theme="light"] .writter-cheap-visual {{ background:#f8fafc; border-color:rgba(15,23,42,.1); }}
.wct-muted {{ color:#94a3b8; font-size:.88rem; margin:.35rem 0 0; }}
.wct-row {{ display:flex; gap:12px; align-items:flex-start; }}
.wct-dot {{ width:12px; height:12px; border-radius:99px; margin-top:6px; flex-shrink:0; }}
.wct-line {{ width:2px; height:16px; margin-left:5px; }}
.wct-card {{ flex:1; padding:12px; border-radius:10px; border:2px solid; background:rgba(0,0,0,.15); }}
.wct-h {{ margin:0 0 6px; font-size:1rem; }}
.writter-cheap-compare {{ display:flex; gap:12px; flex-wrap:wrap; }}
.wct-ps {{ padding:12px; margin:8px 0; border-radius:8px; background:rgba(0,0,0,.12); }}
.writter-cheap-process {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
.wct-pill {{ padding:6px 12px; border-radius:99px; color:#fff; font-size:.85rem; }}
.wct-arrow {{ color:#64748b; }}
.wct-ol {{ margin:0; padding-left:20px; }}
.wct-ol li {{ margin:8px 0; padding-left:8px; }}
</style>
{inner}
<figcaption style="font-size:.78rem;color:#64748b;margin-top:10px;">Template: {html_escape(CHEAP_VISUAL_LABELS.get(template, template))}</figcaption>
</figure>"""


def route_cheap_visual(description: str, topic: str, keywords: str, seed: int = 0) -> Dict[str, Any]:
    """LLM-free: classify + render."""
    tpl = classify_cheap_visual_template(description, topic)
    return {
        "template": tpl,
        "label": CHEAP_VISUAL_LABELS.get(tpl, tpl),
        "html": render_cheap_visual_html(tpl, topic, keywords, seed=seed),
    }


# ─── Extended anti-spam (message or None) ───────────────────────────────────────


def extended_creation_blocked_message(
    *,
    same_topic_count: int,
    same_primary_keyword_count: int,
    author_24h_count: int,
    similar_title_pairs: int = 0,
) -> Optional[str]:
    if same_topic_count >= 10:
        return "Too many articles with the same topic (anti-spam)."
    if same_primary_keyword_count >= 8:
        return "Too many articles targeting the same primary keyword."
    if author_24h_count >= 15:
        return "Rate limit: at most 15 new articles per 24 hours for this account."
    if similar_title_pairs >= 20:
        return "Too many near-duplicate titles detected."
    return None


# ─── CTR variants, refresh, conversion blocks, GSC hints ─────────────────────────


def generate_ctr_variants(
    api_key: str,
    *,
    title: str,
    meta_description: str,
    topic: str,
    keywords: str,
    content_excerpt: str,
) -> Optional[Dict[str, Any]]:
    """3 titles, 3 metas, 2 intro hooks, 2 CTA styles — JSON only."""
    if not HAS_OPENAI or not api_key:
        return None
    user = f"""Article context:
Title: {title}
Meta: {meta_description}
Topic: {topic}
Keywords: {keywords}
Excerpt (plain): {content_excerpt[:3500]}

Return ONLY JSON:
{{
  "title_variants": ["...", "...", "..."],
  "meta_variants": ["...", "...", "..."],
  "intro_hooks": ["...", "..."],
  "cta_styles": ["<p class=\\"writter-cta\\">...</p>", "<p class=\\"writter-cta\\">...</p>"]
}}
Each title ≤120 chars; meta ~150–165 chars; hooks 1–2 sentences."""
    try:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an SEO copywriter. JSON only."},
                {"role": "user", "content": user},
            ],
            max_tokens=1200,
            temperature=0.75,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = _parse_json_obj(raw)
        if not data:
            return None
        return {
            "title_variants": data.get("title_variants") or [],
            "meta_variants": data.get("meta_variants") or [],
            "intro_hooks": data.get("intro_hooks") or [],
            "cta_styles": data.get("cta_styles") or [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


REFRESH_ACTIONS = frozenset(
    {"intro", "title", "cta", "faq", "evidence", "clarity"}
)


def refresh_article_partial(
    api_key: str,
    *,
    action: str,
    article_type: str,
    topic: str,
    keywords: str,
    title: str,
    meta_description: str,
    content_html: str,
    type_prompt_extra: str = "",
) -> Optional[Dict[str, str]]:
    """Returns patches: seo_title, meta_description, content_html (full or fragment to merge by caller)."""
    if action not in REFRESH_ACTIONS or not HAS_OPENAI or not api_key:
        return None
    plain = re.sub(r"<[^>]+>", " ", content_html or "")
    plain = re.sub(r"\s+", " ", plain).strip()[:8000]
    user = f"""Action: {action}
Article type: {article_type}
Topic: {topic}
Keywords: {keywords}
Current title: {title}
Current meta: {meta_description}
Extra type instructions: {type_prompt_extra[:1500]}

Current HTML body:
{plain}

Return ONLY JSON with keys depending on action:
- intro: {{ "content_html_prefix": "<section>... new intro paragraphs ...</section>" }}  (replace first section only in caller)
- title: {{ "seo_title": "...", "meta_description": "..." }}
- cta: {{ "cta_html": "..." }}
- faq: {{ "faq_html": "<section>...</section>" }}
- evidence: {{ "evidence_html": "<section>...</section>" }}
- clarity: {{ "content_html": "full revised HTML body preserving structure" }}

Use semantic HTML: section, h2, h3, p, ul, li, class writter-cta for CTAs."""
    try:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You improve SEO blog HTML for Cartozo.ai. JSON only."},
                {"role": "user", "content": user},
            ],
            max_tokens=3000 if action == "clarity" else 1800,
            temperature=0.55,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = _parse_json_obj(raw)
        if not data:
            return None
        out: Dict[str, str] = {}
        for k in ("seo_title", "meta_description", "content_html", "content_html_prefix", "cta_html", "faq_html", "evidence_html"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
        return out or None
    except Exception:
        return None


def conversion_blocks_html() -> str:
    """Static conversion-intent strip (admin can append to article)."""
    return """<section class="writter-conversion-blocks" data-writter-conversion="1">
<h2>Next steps</h2>
<div class="writter-conv-grid">
  <div class="writter-conv-card"><h3>Try the tool</h3><p>Upload a sample feed and see optimized titles in minutes.</p><p class="writter-cta"><a href="/upload">Start free</a></p></div>
  <div class="writter-conv-card"><h3>See example output</h3><p>Preview how enriched attributes look before publishing.</p><p class="writter-cta"><a href="/">View product</a></p></div>
  <div class="writter-conv-card"><h3>Book a walkthrough</h3><p>Short demo tailored to your catalog and channels.</p><p class="writter-cta"><a href="/contact">Contact</a></p></div>
</div>
</section>"""


def gsc_feedback_suggestions(gsc: Dict[str, Any]) -> Dict[str, Any]:
    """Heuristic suggestions from imported Search Console metrics (no API call here)."""
    imp = float(gsc.get("impressions") or 0)
    clicks = float(gsc.get("clicks") or 0)
    ctr = float(gsc.get("ctr") or 0)
    pos = float(gsc.get("avg_position") or 0)
    queries = gsc.get("queries") if isinstance(gsc.get("queries"), list) else []
    suggestions: List[str] = []
    if imp > 500 and ctr < 0.015:
        suggestions.append("Low CTR vs impressions — test new title/meta (CTR variants).")
    if imp > 200 and pos > 8:
        suggestions.append("Average position is weak — expand headings and FAQ for target queries.")
    if clicks > 50 and ctr > 0.04:
        suggestions.append("Strong CTR — add conversion blocks and internal links to related pillars.")
    if len(queries) > 0 and isinstance(queries[0], dict):
        top_q = queries[0].get("query") or ""
        if top_q:
            suggestions.append(f"Add a short FAQ for query: “{str(top_q)[:80]}”.")
    return {
        "signals": {
            "impressions": imp,
            "clicks": clicks,
            "ctr": ctr,
            "avg_position": pos,
        },
        "suggestions": suggestions[:8],
    }
