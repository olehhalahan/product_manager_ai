from typing import Dict, List, Optional

from ..models import NormalizedProduct


INTERNAL_FIELDS = [
    "id", "title", "description", "category", "brand", "language",
    "image_url", "status_raw", "price", "sale_price", "currency",
    "color", "size", "material", "weight", "gtin", "mpn",
    "condition", "gender", "age_group", "url", "target_country",
]

AUTO_FIELD_MAP = {
    # ID
    "product_id": "id",
    "id": "id",
    "sku": "id",
    "item_id": "id",
    "article_number": "id",
    "artikelnummer": "id",
    "variant_id": "id",
    "item_group_id": "id",
    "external_id": "id",
    # Title
    "current_title": "title",
    "title": "title",
    "product_name": "title",
    "name": "title",
    "item_title": "title",
    "product_title": "title",
    "heading": "title",
    # Description
    "current_description": "description",
    "description": "description",
    "product_description": "description",
    "body": "description",
    "body_html": "description",
    "long_description": "description",
    "short_description": "description",
    "summary": "description",
    # Category
    "category": "category",
    "product_type": "category",
    "google_product_category": "category",
    "product_category": "category",
    "type": "category",
    # Brand
    "brand": "brand",
    "manufacturer": "brand",
    "vendor": "brand",
    "brand_name": "brand",
    # Language
    "language": "language",
    "lang": "language",
    "locale": "language",
    # Image
    "image_url": "image_url",
    "image": "image_url",
    "image_link": "image_url",
    "main_image": "image_url",
    "picture": "image_url",
    "photo": "image_url",
    "featured_image": "image_url",
    # Status
    "status": "status_raw",
    "availability": "status_raw",
    "active": "status_raw",
    "published": "status_raw",
    "is_active": "status_raw",
    # Price
    "price": "price",
    "regular_price": "price",
    "list_price": "price",
    "sale_price": "sale_price",
    "special_price": "sale_price",
    "discount_price": "sale_price",
    # Currency
    "currency": "currency",
    "currency_code": "currency",
    # Color
    "color": "color",
    "colour": "color",
    # Size
    "size": "size",
    "dimensions": "size",
    # Material
    "material": "material",
    "fabric": "material",
    # Weight
    "weight": "weight",
    "shipping_weight": "weight",
    # GTIN / MPN
    "gtin": "gtin",
    "ean": "gtin",
    "upc": "gtin",
    "isbn": "gtin",
    "barcode": "gtin",
    "mpn": "mpn",
    # Condition
    "condition": "condition",
    # Gender / Age
    "gender": "gender",
    "sex": "gender",
    "age_group": "age_group",
    # URL
    "url": "url",
    "link": "url",
    "product_url": "url",
    "canonical_url": "url",
    "handle": "url",
    # Target country (ISO or name) for Merchant / shipping region
    "country": "target_country",
    "target_country": "target_country",
    "shipping_country": "target_country",
    "ship_to_country": "target_country",
    "country_of_sale": "target_country",
    "sale_country": "target_country",
    "country_code": "target_country",
}


def guess_mapping(csv_columns: List[str]) -> Dict[str, str]:
    """Given CSV column names, return best-guess {csv_column: internal_field} mapping."""
    mapping: Dict[str, str] = {}
    used_internal: set = set()
    for col in csv_columns:
        target = AUTO_FIELD_MAP.get(col.lower().strip())
        if target and target not in used_internal:
            mapping[col] = target
            used_internal.add(target)
    return mapping


def normalize_records(
    rows: List[Dict[str, str]],
    custom_mapping: Optional[Dict[str, str]] = None,
) -> List[NormalizedProduct]:
    normalized: List[NormalizedProduct] = []
    for row in rows:
        mapped: Dict[str, str] = {}
        attributes: Dict[str, str] = {}

        for key, value in row.items():
            if custom_mapping:
                target = custom_mapping.get(key)
            else:
                target = AUTO_FIELD_MAP.get(key.lower().strip())

            if target:
                mapped[target] = value
            else:
                if value:
                    attributes[key] = value

        mapped.setdefault("id", "")
        mapped.setdefault("title", "")

        product = NormalizedProduct(
            id=mapped.get("id", ""),
            title=mapped.get("title", ""),
            description=mapped.get("description", ""),
            category=mapped.get("category"),
            brand=mapped.get("brand"),
            language=mapped.get("language"),
            image_url=mapped.get("image_url"),
            status_raw=mapped.get("status_raw"),
            price=mapped.get("price"),
            sale_price=mapped.get("sale_price"),
            currency=mapped.get("currency"),
            color=mapped.get("color"),
            size=mapped.get("size"),
            material=mapped.get("material"),
            weight=mapped.get("weight"),
            gtin=mapped.get("gtin"),
            mpn=mapped.get("mpn"),
            condition=mapped.get("condition"),
            gender=mapped.get("gender"),
            age_group=mapped.get("age_group"),
            url=mapped.get("url"),
            target_country=mapped.get("target_country"),
            attributes=attributes,
            original_row=row,
        )
        normalized.append(product)

    return normalized

