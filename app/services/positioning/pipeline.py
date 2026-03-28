"""
Orchestrate positioning: extract intents -> rule select -> template or LLM assemble -> fallbacks.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Set, Tuple

from ...models import NormalizedProduct, ProductResult
from ..ai_provider import AIProvider
from .content_assembler import assemble_content_with_retries
from .intent_extractor import extract_intents_with_retries
from .intent_selector import select_intents
from .schemas import (
    IntentExtractionResult,
    confidence_summary,
    extraction_to_debug_dict,
    snapshot_from_normalized_product,
)
from .template_assembler import (
    build_merchant_description_template,
    build_merchant_title_template,
)

logger = logging.getLogger(__name__)

PositioningMode = Literal["fast", "deep"]

_EXTRACTION_ATTEMPTS = 2
_ASSEMBLY_ATTEMPTS_DEEP = 2


def _listing_strong_enough(
    snapshot,
    *,
    want_title: bool,
    want_desc: bool,
) -> bool:
    if want_title and len((snapshot.current_title or "").strip()) < 30:
        return False
    if want_desc and len((snapshot.current_description or "").strip()) < 55:
        return False
    n = len(snapshot.optional_attributes or {})
    for f in (snapshot.color, snapshot.material, snapshot.size, snapshot.condition):
        if (f or "").strip():
            n += 1
    if n < 2:
        return False
    return True


def _template_title_from_summary(
    extraction: IntentExtractionResult,
    snapshot,
) -> str:
    s = extraction.product_summary
    core = (s.core_product or snapshot.current_title or "Product").strip()
    parts: List[str] = [core]
    if (s.primary_use_case or "").strip():
        parts.append(f"for {s.primary_use_case.strip()}")
    if s.key_attributes:
        parts.append(f"- {s.key_attributes[0]}")
    return AIProvider._clean_title(" ".join(parts), 150)


def run_positioning_pipeline(
    ai: AIProvider,
    product: NormalizedProduct,
    *,
    optimize_fields: Set[str],
    mode: PositioningMode = "fast",
    skip_strong_listings: bool = True,
) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
    """
    Returns (title, description, positioning_debug_dict).
    Fast mode (batch default): one extraction LLM call (plus at most one repair), template assembly, rules fallback.
    Deep mode: extraction + LLM assembly (for single-SKU / premium).
    """
    log_lines: List[str] = []
    positioning: Dict[str, Any] = {
        "pipeline_log": log_lines,
        "fallback_used": None,
        "positioning_mode": mode,
    }

    want_title = "title" in optimize_fields
    want_desc = "description" in optimize_fields
    if not want_title and not want_desc:
        return None, None, positioning

    snapshot = snapshot_from_normalized_product(product)

    if mode == "fast" and skip_strong_listings and _listing_strong_enough(
        snapshot, want_title=want_title, want_desc=want_desc
    ):
        positioning["routing"] = "skipped_already_strong"
        log_lines.append("routing: strong listing, skip AI pipeline")
        # Leave optimized_* unset so review UI and scoring use originals.
        return None, None, positioning

    def complete_fn(sys_p: str, usr_p: str, attempt: int):
        return ai.complete_chat_json(
            system=sys_p,
            user=usr_p,
            temperature=0.26 if attempt == 1 else 0.12,
            max_tokens=2800 if attempt == 1 else 3200,
        )

    extraction, ext_raw, ext_attempts, ext_err_tags = extract_intents_with_retries(
        complete_fn,
        snapshot,
        max_attempts=_EXTRACTION_ATTEMPTS,
        extraction_system=ai.positioning_extraction_system_prompt(),
    )
    log_lines.append(f"extract: attempts={ext_attempts} ok={extraction is not None}")
    if ext_err_tags:
        positioning["extraction_last_error_tags"] = ext_err_tags
        log_lines.append(f"extract: last_errors={' | '.join(ext_err_tags[:8])}")

    def rules_fallback(reason: str) -> Tuple[str, str]:
        positioning["fallback_used"] = "rules_fallback"
        log_lines.append(f"fallback rules: {reason}")
        t = (
            ai.generate_title(product, allow_llm=False)
            if want_title
            else (product.title or "")
        )
        d = (
            ai.generate_description(product, allow_llm=False)
            if want_desc
            else (product.description or "")
        )
        return t, d

    def legacy_rewrite_llm(reason: str) -> Tuple[str, str]:
        positioning["fallback_used"] = "legacy_rewrite"
        log_lines.append(f"fallback legacy_rewrite: {reason}")
        t = ai.generate_title(product, allow_llm=True) if want_title else (product.title or "")
        d = (
            ai.generate_description(product, allow_llm=True)
            if want_desc
            else (product.description or "")
        )
        return t, d

    if not extraction:
        positioning["extraction"] = extraction_to_debug_dict(
            None, ext_raw[:1200] if ext_raw else ""
        )
        if mode == "fast":
            t, d = rules_fallback("intent extraction failed or invalid JSON")
        else:
            t, d = legacy_rewrite_llm("intent extraction failed or invalid JSON")
        return (t if want_title else None), (d if want_desc else None), positioning

    positioning["extraction"] = extraction_to_debug_dict(extraction)
    positioning["product_summary"] = extraction.product_summary.model_dump(mode="json")
    positioning["extracted_intents"] = [
        m.model_dump(mode="json") for m in extraction.search_intents
    ]

    selected_models, rejected = select_intents(extraction, snapshot)
    positioning["selected_intents"] = [m.model_dump(mode="json") for m in selected_models]
    positioning["rejected_intents"] = rejected
    positioning["confidence_summary"] = confidence_summary(selected_models)
    log_lines.append(f"select: selected={len(selected_models)} rejected={len(rejected)}")

    all_phrases = [m.intent for m in extraction.search_intents if m.intent]

    # ----- Fast path: template assembly only (max 1 LLM call done = extraction) -----
    if mode == "fast":
        positioning["assembly_mode"] = "template"
        if not selected_models:
            log_lines.append("no intents passed rules; template from summary only")
            tmpl_title = _template_title_from_summary(extraction, snapshot)
            tmpl_desc = (
                build_merchant_description_template(extraction, [], snapshot)
                if want_desc
                else (product.description or "")
            )
            return (
                tmpl_title if want_title else None,
                tmpl_desc if want_desc else None,
                positioning,
            )

        tmpl_title = build_merchant_title_template(
            extraction, selected_models, snapshot
        )
        tmpl_desc = (
            build_merchant_description_template(
                extraction, selected_models, snapshot
            )
            if want_desc
            else (product.description or "")
        )
        log_lines.append("assemble: template (no LLM)")
        return (
            tmpl_title if want_title else None,
            tmpl_desc if want_desc else None,
            positioning,
        )

    # ----- Deep path: LLM assembly (second call), capped retries -----
    positioning["assembly_mode"] = "llm"

    if not selected_models:
        positioning["fallback_used"] = "template_assembly"
        log_lines.append("no intents passed rules; template title + rules description if needed")
        tmpl_title = _template_title_from_summary(extraction, snapshot)
        tmpl_desc = (
            ai.generate_description(product, allow_llm=True)
            if want_desc
            else (product.description or "")
        )
        return (
            tmpl_title if want_title else None,
            tmpl_desc if want_desc else None,
            positioning,
        )

    final, asm_raw, asm_attempts, asm_err_tags = assemble_content_with_retries(
        complete_fn,
        snapshot,
        selected_models,
        all_phrases,
        max_attempts=_ASSEMBLY_ATTEMPTS_DEEP,
        assembly_system=ai.positioning_assembly_system_prompt(),
    )
    log_lines.append(f"assemble: attempts={asm_attempts} ok={final is not None}")
    if asm_err_tags:
        positioning["assembly_last_error_tags"] = asm_err_tags
        log_lines.append(f"assemble: last_errors={' | '.join(asm_err_tags[:8])}")

    if final:
        positioning["final_generation"] = final.model_dump(mode="json")
        positioning["intents_used"] = list(final.intents_used)
        positioning["intents_not_used"] = list(final.intents_not_used)
        title_out = AIProvider._clean_title((final.final_title or "").strip(), 150)
        desc_out = (final.final_description or "").strip()
        if not title_out and want_title:
            title_out = build_merchant_title_template(
                extraction, selected_models, snapshot
            )
            positioning["fallback_used"] = "template_title_after_empty_assembly"
            log_lines.append("assembler returned empty title; template used")
        return (
            title_out if want_title else None,
            desc_out if want_desc else None,
            positioning,
        )

    positioning["assembly_error"] = (asm_raw or "")[:2000]
    positioning["fallback_used"] = "template_assembly"
    log_lines.append("assembly failed; template + rules description fallback")
    tmpl_title = build_merchant_title_template(
        extraction, selected_models, snapshot
    )
    tmpl_desc = (
        ai.generate_description(product, allow_llm=True)
        if want_desc
        else (product.description or "")
    )
    return (
        tmpl_title if want_title else None,
        tmpl_desc if want_desc else None,
        positioning,
    )


def apply_feed_optimization(
    result: ProductResult,
    ai: AIProvider,
    optimize_fields: Set[str],
    *,
    positioning_mode: PositioningMode = "fast",
    skip_strong_listings: bool = True,
) -> None:
    """Mutate ProductResult with positioning pipeline outputs."""
    skip = False if positioning_mode == "deep" else skip_strong_listings
    title, desc, meta = run_positioning_pipeline(
        ai,
        result.product,
        optimize_fields=optimize_fields,
        mode=positioning_mode,
        skip_strong_listings=skip,
    )
    if title is not None:
        result.optimized_title = title
    if desc is not None:
        result.optimized_description = desc
    result.positioning = meta
