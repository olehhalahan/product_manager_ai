from typing import Dict, List

from ..models import NormalizedProduct, ProductAction


def _is_inactive(product: NormalizedProduct) -> bool:
    if not product.status_raw:
        return False
    val = product.status_raw.lower()
    return any(token in val for token in ["inactive", "disabled", "archived", "out_of_stock"])


def decide_actions_for_products(
    products: List[NormalizedProduct],
    mode: str = "optimize",
) -> Dict[str, ProductAction]:
    """
    Decide what to do with each product.
    mode="optimize" — process all active products (user explicitly asked).
    mode="translate" — translate all active products.
    mode="smart" — only process products that need improvement (cost-saving).
    """
    actions: Dict[str, ProductAction] = {}

    for i, p in enumerate(products):
        pid = p.id or f"_row_{i}"
        if not p.id:
            p.id = pid

        if _is_inactive(p):
            actions[pid] = ProductAction.SKIP
            continue

        if mode == "translate":
            actions[pid] = ProductAction.TRANSLATE
        elif mode == "optimize":
            if not p.title and not p.description:
                actions[pid] = ProductAction.GENERATE_NEW
            else:
                actions[pid] = ProductAction.IMPROVE_EXISTING
        else:
            actions[pid] = ProductAction.IMPROVE_EXISTING

    return actions

