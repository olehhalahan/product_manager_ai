"""LLM step 1: extract search intents + product summary (JSON only)."""

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from .extraction_normalize import reparse_json_from_raw, try_validate_extraction
from .prompt_defaults import DEFAULT_EXTRACTION_SYSTEM
from .schemas import IntentExtractionResult, ProductSnapshot

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM = DEFAULT_EXTRACTION_SYSTEM


def build_extraction_user_message(snapshot: ProductSnapshot) -> str:
    import json

    payload: Dict[str, Any] = {
        "current_title": snapshot.current_title,
        "current_description": snapshot.current_description,
        "brand": snapshot.brand,
        "category_or_product_type": snapshot.product_type,
        "color": snapshot.color,
        "material": snapshot.material,
        "size": snapshot.size,
        "condition": snapshot.condition,
        "optional_attributes": snapshot.optional_attributes,
    }
    return (
        "Analyze this product for Shopping search positioning. "
        "Propose search intents strictly grounded in these fields:\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def extract_intents_with_retries(
    complete_json_fn: Callable[[str, str, int], Tuple[Optional[dict], str]],
    snapshot: ProductSnapshot,
    max_attempts: int = 2,
    *,
    extraction_system: Optional[str] = None,
) -> Tuple[Optional[IntentExtractionResult], str, int, list[str]]:
    """
    complete_json_fn(system, user, attempt) -> (parsed dict | None, raw str).

    Returns (model_or_none, last_raw, attempts_used, last_error_tags); tags empty on success.
    """
    system = (extraction_system or "").strip() or EXTRACTION_SYSTEM
    base_user = build_extraction_user_message(snapshot)
    last_raw = ""
    last_failure_tags: list[str] = []
    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            user = base_user
        else:
            snippet = last_raw[:1800] + ("…" if len(last_raw) > 1800 else "")
            hint = ", ".join(last_failure_tags[:6]) if last_failure_tags else "see excerpt"
            user = (
                base_user
                + "\n\n---\nYour previous reply was not valid JSON or did not match the required schema.\n"
                f"Issues detected: {hint}\n"
                "Respond with ONLY one JSON object as specified in the system message.\n"
                "No markdown. No code fences. No text outside the JSON.\n"
                'Use "" and [] instead of null for empty string/array fields.\n\n'
                "Previous output to fix:\n"
                + snippet
            )
        logger.info("positioning.extract attempt=%s", attempt)
        parsed, raw = complete_json_fn(system, user, attempt)
        last_raw = raw or last_raw
        if not parsed and last_raw:
            parsed = reparse_json_from_raw(last_raw)
            if parsed:
                logger.info("positioning.extract repaired JSON via reparse (attempt=%s)", attempt)
        if not parsed:
            last_failure_tags = ["json_parse_error:after_llm"]
            logger.warning(
                "positioning.extract no JSON dict (attempt=%s excerpt=%s)",
                attempt,
                (last_raw[:400].replace("\n", " ") if last_raw else ""),
            )
            continue
        model, tags = try_validate_extraction(parsed, IntentExtractionResult)
        if model is not None:
            return model, last_raw, attempt, []
        last_failure_tags = tags
        logger.warning(
            "positioning.extract validation failed (attempt=%s): %s",
            attempt,
            tags,
        )
    return None, last_raw, max_attempts, last_failure_tags
