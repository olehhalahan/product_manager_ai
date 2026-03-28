"""LLM step 2: assemble Merchant title + description from selected intents."""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .extraction_normalize import reparse_json_from_raw, try_validate_final_generation
from .prompt_defaults import DEFAULT_ASSEMBLY_SYSTEM
from .schemas import FinalGenerationResult, ProductSnapshot, SearchIntentModel

logger = logging.getLogger(__name__)

ASSEMBLER_SYSTEM = DEFAULT_ASSEMBLY_SYSTEM


def build_assembler_user_message(
    snapshot: ProductSnapshot,
    selected: List[SearchIntentModel],
    all_intent_phrases: List[str],
) -> str:
    sel_payload = [
        {
            "intent": m.intent,
            "type": m.type,
            "relevance_score": m.relevance_score,
            "commercial_score": m.commercial_score,
            "confidence_score": m.confidence_score,
        }
        for m in selected
    ]
    body: Dict[str, Any] = {
        "product_snapshot": {
            "current_title": snapshot.current_title,
            "current_description": snapshot.current_description,
            "brand": snapshot.brand,
            "category_or_product_type": snapshot.product_type,
            "color": snapshot.color,
            "material": snapshot.material,
            "size": snapshot.size,
            "condition": snapshot.condition,
            "optional_attributes": snapshot.optional_attributes,
        },
        "selected_intents": sel_payload,
        "all_candidate_intents": all_intent_phrases,
    }
    return (
        "Compose final listing copy grounded in snapshot facts and aligned to these intents:\n\n"
        f"{json.dumps(body, ensure_ascii=False, indent=2)}"
    )


def assemble_content_with_retries(
    complete_json_fn: Callable[[str, str, int], Tuple[Optional[dict], str]],
    snapshot: ProductSnapshot,
    selected: List[SearchIntentModel],
    all_intent_phrases: List[str],
    max_attempts: int = 2,
    *,
    assembly_system: Optional[str] = None,
) -> Tuple[Optional[FinalGenerationResult], str, int, list[str]]:
    system = (assembly_system or "").strip() or ASSEMBLER_SYSTEM
    base_user = build_assembler_user_message(snapshot, selected, all_intent_phrases)
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
                + "\n\n---\nYour previous reply was not valid JSON or was missing required fields.\n"
                f"Issues detected: {hint}\n"
                "Respond with ONLY one JSON object per the system schema.\n"
                "No markdown. No code fences.\n"
                'Use "" and [] instead of null.\n\n'
                "Previous output to fix:\n"
                + snippet
            )
        logger.info("positioning.assemble attempt=%s", attempt)
        parsed, raw = complete_json_fn(system, user, attempt)
        last_raw = raw or last_raw
        if not parsed and last_raw:
            parsed = reparse_json_from_raw(last_raw)
            if parsed:
                logger.info("positioning.assemble repaired JSON via reparse (attempt=%s)", attempt)
        if not parsed:
            last_failure_tags = ["json_parse_error:after_llm"]
            continue
        model, tags = try_validate_final_generation(parsed, FinalGenerationResult)
        if model is not None:
            return model, last_raw, attempt, []
        last_failure_tags = tags
        logger.warning("positioning.assemble validation failed (attempt=%s): %s", attempt, tags)
    return None, last_raw, max_attempts, last_failure_tags
