"""Coerce LLM extraction JSON toward IntentExtractionResult before/after Pydantic."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from ..llm_json import parse_json_object_from_text

_ALLOWED_INTENT_TYPES = {
    "core",
    "use_case",
    "attribute",
    "style",
    "problem_solving",
    "audience",
}

_TYPE_ALIASES = {
    "": "attribute",
    "other": "attribute",
    "general": "attribute",
    "modifier": "attribute",
    "core": "core",
    "core_product": "core",
    "core product": "core",
    "product": "core",
    "use_case": "use_case",
    "use case": "use_case",
    "commercial": "use_case",
    "usecase": "use_case",
    "attribute": "attribute",
    "attr": "attribute",
    "style": "style",
    "problem_solving": "problem_solving",
    "problem solving": "problem_solving",
    "problem-solving": "problem_solving",
    "audience": "audience",
    "comparison": "use_case",
    "compatibility": "attribute",
}


def _clamp_score(v: Any) -> int:
    try:
        if v is None:
            return 5
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return 5
    return max(1, min(10, n))


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _normalize_intent_type(raw: Any) -> str:
    key = _as_str(raw).lower().replace("-", " ")
    key = re.sub(r"\s+", " ", key)
    mapped = _TYPE_ALIASES.get(key)
    if mapped:
        return mapped
    if key in _ALLOWED_INTENT_TYPES:
        return key
    underscored = key.replace(" ", "_")
    if underscored in _ALLOWED_INTENT_TYPES:
        return underscored
    return "attribute"


def normalize_intent_extraction_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new dict with relaxed types; safe if keys are missing."""
    out: Dict[str, Any] = dict(data) if isinstance(data, dict) else {}

    ps = out.get("product_summary")
    if ps is None or not isinstance(ps, dict):
        ps = {}
    ka = ps.get("key_attributes")
    if ka is None:
        ka_list: List[Any] = []
    elif isinstance(ka, str):
        t = ka.strip()
        ka_list = [t] if t else []
    elif isinstance(ka, list):
        ka_list = ka
    else:
        ka_list = []
    summary = {
        "core_product": _as_str(ps.get("core_product")),
        "primary_use_case": _as_str(ps.get("primary_use_case")),
        "key_attributes": ka_list,
    }
    out["product_summary"] = summary

    raw_intents = out.get("search_intents")
    if raw_intents is None:
        raw_intents = []
    if isinstance(raw_intents, dict):
        raw_intents = [raw_intents]
    if not isinstance(raw_intents, list):
        raw_intents = []

    intents: List[Dict[str, Any]] = []
    for item in raw_intents:
        if not isinstance(item, dict):
            continue
        intents.append(
            {
                "intent": _as_str(item.get("intent")),
                "type": _normalize_intent_type(item.get("type")),
                "relevance_score": _clamp_score(item.get("relevance_score")),
                "commercial_score": _clamp_score(item.get("commercial_score")),
                "confidence_score": _clamp_score(item.get("confidence_score")),
                "reason": _as_str(item.get("reason")),
            }
        )
    out["search_intents"] = intents

    top = out.get("top_recommended_intents")
    if top is None:
        top = []
    if isinstance(top, str):
        top = [_as_str(top)] if _as_str(top) else []
    if isinstance(top, list):
        top = [_as_str(x) for x in top if _as_str(x)]
    else:
        top = []
    out["top_recommended_intents"] = top

    return out


def reparse_json_from_raw(raw: str) -> Optional[Dict[str, Any]]:
    """Second pass if API layer returned None — same as llm_json plus strip common wrappers."""
    if not raw or not str(raw).strip():
        return None
    return parse_json_object_from_text(raw)


def unwrap_json_value_if_wrapped(parsed: Any) -> Optional[Dict[str, Any]]:
    """If model wrapped payload in { "json": {...} } or { "result": {...} }, unwrap once."""
    if not isinstance(parsed, dict):
        return None
    if len(parsed) != 1:
        return parsed
    only_key = next(iter(parsed.keys()))
    if only_key.lower() in ("json", "data", "result", "output", "response"):
        inner = parsed[only_key]
        if isinstance(inner, dict):
            return inner
    return parsed


def validation_error_tags(e: ValidationError) -> List[str]:
    """Short machine-readable tags for logging and admin debug."""
    tags: List[str] = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        typ = str(err.get("type", ""))
        if "json_invalid" in typ or typ.startswith("json"):
            tags.append(f"json_invalid:{loc}")
        elif "missing" in typ:
            tags.append(f"missing_required_field:{loc}")
        elif "enum" in typ or "literal" in typ:
            tags.append(f"invalid_enum:{loc}")
        elif typ in ("greater_than_equal", "less_than_equal", "greater_than", "less_than"):
            tags.append(f"score_or_bound:{loc}")
        elif "int" in typ or "string" in typ or "bool" in typ or "type_error" in typ:
            tags.append(f"wrong_type:{loc}")
        else:
            tags.append(f"{typ or 'validation'}:{loc}")
    return tags


def try_validate_extraction(
    parsed: Optional[Dict[str, Any]],
    model_cls,
) -> Tuple[Optional[Any], List[str]]:
    """
    Unwrap common single-key wrappers, normalize, validate.
    Returns (model_or_none, error_tags).
    """
    if not parsed or not isinstance(parsed, dict):
        return None, ["json_parse_error:root"]
    candidate = unwrap_json_value_if_wrapped(parsed)
    if not isinstance(candidate, dict):
        return None, ["json_parse_error:unwrap"]
    norm = normalize_intent_extraction_dict(candidate)
    try:
        return model_cls.model_validate(norm), []
    except ValidationError as e:
        return None, validation_error_tags(e)


def normalize_final_generation_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    out = dict(data)
    for key in ("final_title", "final_description"):
        v = out.get(key)
        out[key] = "" if v is None else str(v).strip()
    for key in ("title_rationale", "intents_used", "intents_not_used"):
        v = out.get(key)
        if v is None:
            out[key] = []
        elif isinstance(v, str):
            t = str(v).strip()
            out[key] = [t] if t else []
        elif isinstance(v, list):
            out[key] = [str(x).strip() for x in v if str(x).strip()]
        else:
            out[key] = []
    return out


def try_validate_final_generation(
    parsed: Optional[Dict[str, Any]],
    model_cls,
) -> Tuple[Optional[Any], List[str]]:
    if not parsed or not isinstance(parsed, dict):
        return None, ["json_parse_error:root"]
    candidate = unwrap_json_value_if_wrapped(parsed)
    if not isinstance(candidate, dict):
        return None, ["json_parse_error:unwrap"]
    norm = normalize_final_generation_dict(candidate)
    try:
        model = model_cls.model_validate(norm)
        if (model.final_title or "").strip():
            return model, []
        return None, ["missing_required_field:final_title"]
    except ValidationError as e:
        return None, validation_error_tags(e)
