"""Deterministic Merchant title + description from extraction + rule-selected intents (no LLM)."""

from __future__ import annotations

import re
from typing import List, Tuple

from ..ai_provider import AIProvider
from .schemas import IntentExtractionResult, ProductSnapshot, SearchIntentModel

_TYPE_CORE = frozenset({"core", "core_product", "product"})
_TYPE_USE = frozenset({"use_case", "commercial", "audience"})
_TYPE_ATTR = frozenset({"attribute", "style", "problem_solving", "modifier"})


def _norm_intent_type(raw: str) -> str:
    return (raw or "").strip().lower().replace("-", "_").replace(" ", "_")


def _first_intent_by_type(
    selected: List[SearchIntentModel], types: frozenset
) -> str:
    for m in selected:
        nt = _norm_intent_type(m.type)
        if nt in types:
            return (m.intent or "").strip()
        if nt == "core_product" and ("core" in types or "core_product" in types):
            return (m.intent or "").strip()
    return ""


def _core_phrase(
    extraction: IntentExtractionResult,
    selected: List[SearchIntentModel],
    snapshot: ProductSnapshot,
) -> str:
    s = extraction.product_summary
    c = (s.core_product or "").strip()
    if c:
        return c
    hit = _first_intent_by_type(selected, _TYPE_CORE)
    if hit:
        return hit
    t = (snapshot.current_title or "").strip()
    return t or "Product"


def _use_case_phrase(
    extraction: IntentExtractionResult,
    selected: List[SearchIntentModel],
) -> str:
    u = (extraction.product_summary.primary_use_case or "").strip()
    if u:
        return u
    return _first_intent_by_type(selected, _TYPE_USE)


def _attribute_phrase(
    extraction: IntentExtractionResult,
    selected: List[SearchIntentModel],
    snapshot: ProductSnapshot,
) -> str:
    ka = extraction.product_summary.key_attributes or []
    for a in ka:
        t = (str(a) or "").strip()
        if t:
            return t
    hit = _first_intent_by_type(selected, _TYPE_ATTR)
    if hit:
        return hit
    for label in (snapshot.color, snapshot.material, snapshot.size):
        t = (label or "").strip()
        if t:
            return t
    return ""


def _brand_ok(snapshot: ProductSnapshot, core: str, use_c: str, attr: str) -> str:
    b = (snapshot.brand or "").strip()
    if not b:
        return ""
    blob = f"{core} {use_c} {attr}".lower()
    if b.lower() in blob:
        return ""
    return b


def build_merchant_title_template(
    extraction: IntentExtractionResult,
    selected: List[SearchIntentModel],
    snapshot: ProductSnapshot,
    *,
    max_len: int = 150,
) -> str:
    """Assemble title from summary + selected intents (Shopping-style, <= max_len)."""
    core = _core_phrase(extraction, selected, snapshot)
    use_c = _use_case_phrase(extraction, selected)
    attr = _attribute_phrase(extraction, selected, snapshot)
    brand = _brand_ok(snapshot, core, use_c, attr)

    parts: List[str] = []
    if use_c and attr:
        parts.append(f"{core} for {use_c} – {attr}")
    elif use_c:
        parts.append(f"{core} for {use_c}")
    elif attr:
        parts.append(f"{core} – {attr}")
    else:
        parts.append(core)

    base = " ".join(p for p in parts if p).strip()
    base = re.sub(r"\s{2,}", " ", base)

    if brand:
        cand = f"{base} – {brand}"
        if len(cand) <= max_len:
            base = cand
        else:
            cand2 = f"{base} {brand}"
            base = AIProvider._clean_title(cand2, max_len)

    return AIProvider._clean_title(base, max_len)


def build_merchant_description_template(
    extraction: IntentExtractionResult,
    selected: List[SearchIntentModel],
    snapshot: ProductSnapshot,
) -> str:
    """Short factual description from snapshot + intents (no LLM)."""
    core = _core_phrase(extraction, selected, snapshot)
    use_c = _use_case_phrase(extraction, selected)
    brand = (snapshot.brand or "").strip()
    snippets: List[str] = []

    head = core
    if brand and brand.lower() not in head.lower():
        head = f"{core} by {brand}"
    snippets.append(head + ".")

    if use_c:
        snippets.append(f"Ideal for {use_c}.")

    detail_bits: List[str] = []
    for a in (extraction.product_summary.key_attributes or [])[:4]:
        t = (str(a) or "").strip()
        if t:
            detail_bits.append(t)
    for label, val in (
        ("Color", snapshot.color),
        ("Material", snapshot.material),
        ("Size", snapshot.size),
    ):
        v = (val or "").strip()
        if v:
            detail_bits.append(f"{label}: {v}")
    for k, v in list((snapshot.optional_attributes or {}).items())[:6]:
        kk = (k or "").strip()
        vv = (str(v) or "").strip()
        if kk and vv and f"{kk}: {vv}" not in detail_bits:
            detail_bits.append(f"{kk}: {vv}")

    if detail_bits:
        snippets.append(" ".join(detail_bits[:8]) + ".")

    intent_line = [m.intent for m in selected[:4] if (m.intent or "").strip()]
    if intent_line:
        snippets.append("Search angles: " + ", ".join(intent_line) + ".")

    legacy = (snapshot.current_description or "").strip()
    if legacy and len(legacy) < 400:
        cleaned = re.sub(r"\s+", " ", legacy)
        snippets.append(cleaned)

    body = " ".join(snippets)
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > 5000:
        body = body[:4997].rsplit(".", 1)[0] + "."
    return body
