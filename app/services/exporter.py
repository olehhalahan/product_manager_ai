import csv
import re
from typing import List, TextIO

from ..models import Batch, ProductAction, ProductResult, ProductStatus


def generate_result_csv(batch: Batch, buffer: TextIO) -> None:
    """
    Primary product feed CSV aligned with Google Merchant Center product data spec.
    Values match Merchant API push (optimized → translated → original).
    Skipped (inactive) rows are omitted.
    """
    generate_merchant_feed_csv(batch.products, buffer)


def _format_raw_price(raw: str, currency: str) -> str:
    """Format one price field as \"10.00 USD\" for GMC CSV."""
    price_raw = (raw or "").strip()
    if not price_raw:
        return ""
    cur = (currency or "USD").strip().upper()
    cleaned = price_raw
    for token in ("USD", "EUR", "GBP", "UAH", "PLN"):
        cleaned = re.sub(rf"\b{token}\b", "", cleaned, flags=re.I)
    cleaned = cleaned.replace("$", "").replace("€", "").replace("£", "").strip()
    m = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
    if not m:
        return ""
    num = m.group(1).replace(",", ".")
    parts = num.split(".")
    if len(parts) > 2:
        num = "".join(parts[:-1]) + "." + parts[-1]
    try:
        val = f"{float(num):.2f}"
    except ValueError:
        return ""
    return f"{val} {cur}"


def _gmc_availability(status_raw: str | None) -> str:
    s = (status_raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if s in ("out_of_stock", "outofstock"):
        return "out of stock"
    if s in ("preorder", "pre_order"):
        return "preorder"
    if s in ("backorder", "back_order"):
        return "backorder"
    return "in stock"


def _gmc_condition(raw: str | None) -> str:
    if not raw or not str(raw).strip():
        return "new"
    s = str(raw).strip().lower()
    if s in ("refurbished", "refurb"):
        return "refurbished"
    if s in ("used",):
        return "used"
    return "new"


def _feed_results(products: List[ProductResult]) -> List[ProductResult]:
    return [r for r in products if r.status != ProductStatus.SKIPPED and r.action != ProductAction.SKIP]


_GMC_FEED_FIELDNAMES = [
    "id",
    "title",
    "description",
    "link",
    "image_link",
    "additional_image_link",
    "availability",
    "price",
    "sale_price",
    "brand",
    "gtin",
    "mpn",
    "condition",
    "google_product_category",
    "gender",
    "age_group",
    "color",
    "size",
    "material",
]


def generate_merchant_feed_csv(products: List[ProductResult], buffer: TextIO) -> None:
    writer = csv.DictWriter(buffer, fieldnames=_GMC_FEED_FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    for result in _feed_results(products):
        p = result.product
        cur = (p.currency or "USD").strip().upper()
        title = result.effective_title()[:150]
        desc = result.effective_description()[:5000]

        regular = _format_raw_price(p.price or "", cur)
        sale = _format_raw_price(p.sale_price or "", cur)
        price_col = regular or sale
        sale_col = sale if regular and sale else ""

        extra_img = (p.attributes.get("additional_image_link") or p.attributes.get("additional_image") or "").strip()
        if not extra_img and p.original_row:
            for k in ("additional_image_link", "additional image link", "additionalImageLink"):
                v = (p.original_row.get(k) or "").strip()
                if v:
                    extra_img = v
                    break

        g_cat = (p.category or "").strip()

        row = {
            "id": (p.id or "").strip(),
            "title": title,
            "description": desc if desc else title[:5000],
            "link": (p.url or "").strip(),
            "image_link": (p.image_url or "").strip(),
            "additional_image_link": extra_img,
            "availability": _gmc_availability(p.status_raw),
            "price": price_col,
            "sale_price": sale_col,
            "brand": (p.brand or "").strip(),
            "gtin": re.sub(r"\D", "", str(p.gtin))[:50] if (p.gtin or "").strip() else "",
            "mpn": (p.mpn or "").strip()[:70],
            "condition": _gmc_condition(p.condition),
            "google_product_category": g_cat,
            "gender": (p.gender or "").strip().lower(),
            "age_group": (p.age_group or "").strip().lower(),
            "color": (p.color or "").strip(),
            "size": (p.size or "").strip(),
            "material": (p.material or "").strip(),
        }
        writer.writerow(row)
