from typing import List, Set

from ..models import ProductResult


FORBIDDEN_PHRASES: Set[str] = {
    "100% guaranteed",
    "best on the market",
}


def validate_product_result(result: ProductResult) -> List[str]:
    errors: List[str] = []

    title = (result.optimized_title or "").strip()
    description = (result.optimized_description or "").strip()

    if title:
        if len(title) > 150:
            errors.append("Title exceeds 150 characters.")
        orig_title = result.product.title or ""
        if orig_title and _similar_text(orig_title, title) >= 0.95:
            errors.append("Title is too similar to original.")

    if description:
        if len(description) < 30:
            errors.append("Description too short.")

    lower_text = f"{title} {description}".lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in lower_text:
            errors.append(f"Forbidden phrase: {phrase}")

    return errors


def _similar_text(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    same = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            same += 1
    max_len = max(len(a), len(b))
    return same / max_len if max_len else 0.0
