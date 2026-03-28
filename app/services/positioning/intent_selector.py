"""Rule-based intent selection for v1 (dedupe, thresholds, priority, cap)."""

import re
from collections import defaultdict
from typing import Dict, List, Tuple

from .schemas import IntentExtractionResult, ProductSnapshot, SearchIntentModel

_TYPE_ORDER = {
    "core_product": 0,
    "core": 0,
    "product": 0,
    "use_case": 1,
    "commercial": 1,
    "audience": 1,
    "attribute": 2,
    "style": 2,
    "problem_solving": 2,
    "modifier": 2,
    "comparison": 3,
    "other": 4,
}

_STOP = {
    "a", "an", "the", "for", "and", "or", "with", "to", "of", "in", "on",
}


def _normalize_intent_phrase(s: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _STOP]
    return " ".join(sorted(words))


def _combined_score(m: SearchIntentModel) -> int:
    return m.relevance_score * 10 + m.commercial_score + m.confidence_score


def _type_rank(t: str) -> int:
    return _TYPE_ORDER.get((t or "").strip().lower(), 4)


def _weak_snapshot(snapshot: ProductSnapshot) -> bool:
    tot = len(snapshot.current_title or "") + len(snapshot.current_description or "")
    return tot < 40


def select_intents(
    extraction: IntentExtractionResult,
    snapshot: ProductSnapshot,
    max_intents_for_title: int = 3,
) -> Tuple[List[SearchIntentModel], List[Dict[str, str]]]:
    """
    Returns (selected_models, rejected) where rejected items have keys intent, reason.
    """
    min_rel = 8 if _weak_snapshot(snapshot) else 7
    min_conf = 8 if _weak_snapshot(snapshot) else 7

    rejected: List[Dict[str, str]] = []

    groups: Dict[str, List[SearchIntentModel]] = defaultdict(list)
    for m in extraction.search_intents:
        phrase = (m.intent or "").strip()
        if not phrase:
            rejected.append({"intent": "", "reason": "empty intent"})
            continue
        groups[_normalize_intent_phrase(phrase)].append(m)

    deduped: List[SearchIntentModel] = []
    for _norm, items in groups.items():
        best = max(items, key=_combined_score)
        for m in items:
            if m is not best:
                rejected.append(
                    {
                        "intent": m.intent,
                        "reason": f"duplicate intent (kept: {best.intent})",
                    }
                )
        deduped.append(best)

    candidates: List[SearchIntentModel] = []
    for m in deduped:
        phrase = (m.intent or "").strip()
        if m.relevance_score < min_rel:
            rejected.append(
                {
                    "intent": phrase,
                    "reason": f"relevance {m.relevance_score} < {min_rel}",
                }
            )
            continue
        if m.confidence_score < min_conf:
            rejected.append(
                {
                    "intent": phrase,
                    "reason": f"confidence {m.confidence_score} < {min_conf}",
                }
            )
            continue
        candidates.append(m)

    def sort_key(m: SearchIntentModel):
        combined = -(m.relevance_score * 10 + m.commercial_score + m.confidence_score)
        return (_type_rank(m.type), combined, -m.confidence_score)

    candidates.sort(key=sort_key)

    if not candidates:
        return [], rejected

    selected = candidates[:max_intents_for_title]
    for m in candidates[max_intents_for_title:]:
        rejected.append(
            {
                "intent": m.intent,
                "reason": f"not in top {max_intents_for_title} after ranking",
            }
        )

    return selected, rejected
