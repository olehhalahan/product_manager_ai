"""
Google Merchant Center product data specification validator.
Checks required fields, length limits, formatting rules, and quality signals.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from ..models import NormalizedProduct, ProductResult

VALID_AVAILABILITY = {"in_stock", "in stock", "out_of_stock", "out of stock", "preorder", "backorder"}
VALID_CONDITION = {"new", "refurbished", "used"}
VALID_AGE_GROUP = {"newborn", "infant", "toddler", "kids", "adult"}
VALID_GENDER = {"male", "female", "unisex"}

PROMO_PHRASES = [
    "free shipping", "buy now", "best price", "click here",
    "limited time", "order now", "sale", "discount", "% off",
    "cheap", "lowest price", "act now", "hurry",
]

FORBIDDEN_PHRASES = {
    "100% guaranteed", "best on the market",
}


def _severity(is_error: bool) -> str:
    return "error" if is_error else "warning"


GTIN_EXEMPT_TYPES = {
    "custom", "handmade", "vintage", "private_label",
    "bundle", "digital", "services", "promotional",
}


def validate_gmc(result: ProductResult, product_type: str = "standard") -> Tuple[List[str], List[str]]:
    """
    Validate a product result against Google Merchant Center specification.
    Returns (errors, warnings) where errors are spec violations and
    warnings are quality recommendations.
    Rules adapt based on product_type (e.g. custom products skip GTIN).
    """
    errors: List[str] = []
    warnings: List[str] = []
    p = result.product
    title = result.effective_title()
    desc = result.effective_description()
    gtin_required = product_type not in GTIN_EXEMPT_TYPES

    # ── Required fields ──────────────────────────────────────────────
    if not (p.id or "").strip():
        errors.append("Missing required field: id")

    if not title.strip():
        errors.append("Missing required field: title")

    if not desc.strip():
        errors.append("Missing required field: description")

    if not (p.url or "").strip():
        errors.append("Missing required field: link (product URL)")

    if not (p.image_url or "").strip():
        errors.append("Missing required field: image_link")

    if not (p.price or "").strip():
        if product_type not in ("digital", "services"):
            errors.append("Missing required field: price")

    if not (p.brand or "").strip():
        if product_type not in ("custom", "handmade", "vintage"):
            warnings.append("Missing recommended field: brand")

    if not (p.condition or "").strip():
        warnings.append("Missing recommended field: condition")

    if gtin_required:
        if not (p.gtin or "").strip() and not (p.mpn or "").strip():
            warnings.append("Missing identifier: provide gtin or mpn")

    # ── Title checks ─────────────────────────────────────────────────
    if title:
        if len(title) > 150:
            errors.append(f"Title too long: {len(title)} chars (max 150)")
        elif len(title) > 70:
            warnings.append(f"Title length {len(title)} chars — recommended ≤70 for best display")

        if title == title.upper() and len(title) > 5:
            warnings.append("Title is ALL CAPS — use proper capitalization")

        if re.search(r"[!]{2,}|[?]{2,}|[.]{3,}", title):
            warnings.append("Title has excessive punctuation")

        title_lower = title.lower()
        for phrase in PROMO_PHRASES:
            if phrase in title_lower:
                errors.append(f"Title contains promotional text: \"{phrase}\"")
                break

    # ── Description checks ───────────────────────────────────────────
    if desc:
        if len(desc) > 5000:
            errors.append(f"Description too long: {len(desc)} chars (max 5000)")

        if len(desc) < 80:
            warnings.append(f"Description very short: {len(desc)} chars — aim for 150+ for better SEO")

        if title and desc.strip().lower() == title.strip().lower():
            errors.append("Description is identical to title")

        desc_lower = desc.lower()
        for phrase in PROMO_PHRASES:
            if phrase in desc_lower:
                warnings.append(f"Description contains promotional text: \"{phrase}\"")
                break

    # ── URL checks ───────────────────────────────────────────────────
    url = (p.url or "").strip()
    if url:
        if not url.startswith(("http://", "https://")):
            errors.append("Product URL must start with http:// or https://")
        if not url.startswith("https://"):
            warnings.append("Product URL should use https://")

    image_url = (p.image_url or "").strip()
    if image_url:
        if not image_url.startswith(("http://", "https://")):
            errors.append("Image URL must start with http:// or https://")
        ext = image_url.rsplit(".", 1)[-1].lower().split("?")[0] if "." in image_url else ""
        if ext and ext not in ("jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff"):
            warnings.append(f"Image format .{ext} may not be accepted — use jpg, png, or webp")

    # ── Price checks ─────────────────────────────────────────────────
    price_str = (p.price or "").strip()
    if price_str:
        cleaned = re.sub(r"[^\d.,]", "", price_str)
        if cleaned:
            try:
                val = float(cleaned.replace(",", "."))
                if val <= 0:
                    errors.append("Price must be greater than 0")
            except ValueError:
                warnings.append(f"Could not parse price value: {price_str[:30]}")

    sale_str = (p.sale_price or "").strip()
    if sale_str and price_str:
        try:
            pv = float(re.sub(r"[^\d.,]", "", price_str).replace(",", "."))
            sv = float(re.sub(r"[^\d.,]", "", sale_str).replace(",", "."))
            if sv >= pv:
                warnings.append("Sale price should be lower than regular price")
        except (ValueError, ZeroDivisionError):
            pass

    # ── Enumerated field checks ──────────────────────────────────────
    avail = (p.status_raw or "").strip().lower()
    if avail and avail not in VALID_AVAILABILITY:
        warnings.append(f"Availability \"{p.status_raw}\" not standard — expected: in_stock, out_of_stock, preorder, backorder")

    cond = (p.condition or "").strip().lower()
    if cond and cond not in VALID_CONDITION:
        warnings.append(f"Condition \"{p.condition}\" not standard — expected: new, refurbished, used")

    gender = (p.gender or "").strip().lower()
    if gender and gender not in VALID_GENDER:
        warnings.append(f"Gender \"{p.gender}\" not standard — expected: male, female, unisex")

    age = (p.age_group or "").strip().lower()
    if age and age not in VALID_AGE_GROUP:
        warnings.append(f"Age group \"{p.age_group}\" not standard — expected: newborn, infant, toddler, kids, adult")

    # ── GTIN format check ────────────────────────────────────────────
    gtin = (p.gtin or "").strip()
    if gtin:
        digits = re.sub(r"\D", "", gtin)
        if len(digits) not in (8, 12, 13, 14):
            warnings.append(f"GTIN \"{gtin}\" length unusual — expected 8, 12, 13, or 14 digits")

    # ── Forbidden phrases ────────────────────────────────────────────
    full_text = f"{title} {desc}".lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in full_text:
            warnings.append(f"Contains forbidden phrase: \"{phrase}\"")

    return errors, warnings


def validate_title(title: str) -> List[Tuple[str, str]]:
    """
    Validate a single title string against GMC rules.
    Returns list of (severity, message) tuples.
    """
    issues: List[Tuple[str, str]] = []
    title = (title or "").strip()

    if not title:
        issues.append(("error", "Title is empty"))
        return issues

    if len(title) > 150:
        issues.append(("error", f"Too long: {len(title)} chars (max 150)"))
    elif len(title) > 70:
        issues.append(("warn", f"{len(title)} chars — best under 70"))

    if title == title.upper() and len(title) > 5:
        issues.append(("warn", "ALL CAPS"))

    if re.search(r"[!]{2,}|[?]{2,}|[.]{3,}", title):
        issues.append(("warn", "Excessive punctuation"))

    title_lower = title.lower()
    for phrase in PROMO_PHRASES:
        if phrase in title_lower:
            issues.append(("error", f"Promotional: \"{phrase}\""))
            break

    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in title_lower:
            issues.append(("warn", f"Forbidden: \"{phrase}\""))

    return issues


def validate_description(desc: str, title: str = "") -> List[Tuple[str, str]]:
    """
    Validate a single description string against GMC rules.
    Returns list of (severity, message) tuples.
    """
    issues: List[Tuple[str, str]] = []
    desc = (desc or "").strip()

    if not desc:
        issues.append(("error", "Description is empty"))
        return issues

    if len(desc) > 5000:
        issues.append(("error", f"Too long: {len(desc)} chars (max 5000)"))

    if len(desc) < 80:
        issues.append(("warn", f"Too short: {len(desc)} chars — aim for 150+"))

    if title and desc.lower() == title.strip().lower():
        issues.append(("error", "Same as title"))

    desc_lower = desc.lower()
    for phrase in PROMO_PHRASES:
        if phrase in desc_lower:
            issues.append(("warn", f"Promotional: \"{phrase}\""))
            break

    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in desc_lower:
            issues.append(("warn", f"Forbidden: \"{phrase}\""))

    return issues


def validate_product_result(result: ProductResult) -> List[str]:
    """Legacy wrapper — returns combined error strings for backward compat."""
    errs, warns = validate_gmc(result)
    return errs + warns


def merge_review_warnings(result: ProductResult) -> List[Tuple[str, str]]:
    """
    Merge row error, GMC errors/warnings, and notes into deduplicated (severity, text)
    tuples — same logic as the batch review warnings column.
    """
    severity_by_text: dict = {}
    order: List[str] = []

    def bump(sev: str, text: object) -> None:
        t = (str(text) if text is not None else "").strip()
        if not t:
            return
        if t not in severity_by_text:
            order.append(t)
        prev = severity_by_text.get(t, "warn")
        if sev == "error" or prev == "error":
            severity_by_text[t] = "error"
        else:
            severity_by_text[t] = "warn"

    if result.error:
        bump("error", result.error)
    for e in result.gmc_errors:
        bump("error", e)
    for w in result.gmc_warnings:
        bump("warn", w)
    if result.notes:
        for part in re.split(r"[\n;|]+", result.notes):
            bump("warn", part)
    return [(severity_by_text[t], t) for t in order]


def refresh_product_gmc_validation(result: ProductResult, product_type: str) -> None:
    """Re-run GMC validation after inline edits and store on the result."""
    errs, warns = validate_gmc(result, product_type)
    result.gmc_errors = errs
    result.gmc_warnings = warns


def feed_data_fix_field_specs(
    merged_warnings: List[Tuple[str, str]],
    product: NormalizedProduct,
    product_type: str = "standard",
) -> List[Dict[str, Any]]:
    """
    Which NormalizedProduct attributes should get inline fix inputs on the review table,
    based on warnings/errors and on product_type (e.g. GTIN+MPN when required and both empty).
    """
    seen: set = set()
    out: List[Dict[str, Any]] = []

    def add(attr: str, label: str, control: str = "text", options: Optional[List[str]] = None) -> None:
        if attr in seen:
            return
        seen.add(attr)
        raw_val = getattr(product, attr, None) or ""
        entry: Dict[str, Any] = {
            "attr": attr,
            "label": label,
            "control": control,
            "value": str(raw_val),
        }
        if options is not None:
            entry["options"] = options
        out.append(entry)

    # GMC expects GTIN or MPN for non–GTIN-exempt product types; show both fields when neither is set.
    if product_type not in GTIN_EXEMPT_TYPES:
        no_gtin = not (product.gtin or "").strip()
        no_mpn = not (product.mpn or "").strip()
        if no_gtin and no_mpn:
            add("gtin", "GTIN")
            add("mpn", "MPN")

    for _sev, text in merged_warnings:
        t = text

        if "Missing required field: price" in t or "Price must be greater than 0" in t:
            add("price", "Price")
        if "Could not parse price value" in t:
            add("price", "Price")

        if "Missing required field: link (product URL)" in t or (
            "Product URL must start with" in t and "image" not in t.lower()
        ):
            add("url", "Product URL")

        if (
            "Missing required field: image_link" in t
            or "Image URL must start with" in t
            or ("Image format" in t and "may not be accepted" in t)
        ):
            add("image_url", "Image URL")

        if "Availability " in t and "not standard" in t:
            add("status_raw", "Availability")

        if "Missing recommended field: brand" in t:
            add("brand", "Brand")

        if "Missing recommended field: condition" in t or (
            "not standard" in t and t.startswith("Condition ")
        ):
            add(
                "condition",
                "Condition",
                "select",
                ["new", "refurbished", "used"],
            )

        tl = t.lower()
        if "missing identifier" in tl and "gtin" in tl and "mpn" in tl:
            add("gtin", "GTIN")
            add("mpn", "MPN")
        elif "provide gtin or mpn" in tl:
            add("gtin", "GTIN")
            add("mpn", "MPN")

        if "GTIN " in t and "length unusual" in t:
            add("gtin", "GTIN")

    return out
