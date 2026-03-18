"""
Google Merchant Center product data specification validator.
Checks required fields, length limits, formatting rules, and quality signals.
"""
import re
from typing import List, Tuple

from ..models import ProductResult

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
    title = result.optimized_title or p.title or ""
    desc = result.optimized_description or p.description or ""
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
